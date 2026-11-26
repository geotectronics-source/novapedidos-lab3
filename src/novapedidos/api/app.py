"""Servicio FastAPI (contrato del Anexo).

    POST /v1/pedidos/interpretar  -> 200 pedido | 404 cliente inexistente | 422 solicitud inválida
                                     | 503 modelo de lenguaje no disponible (tras reintentos y respaldo)
    GET  /health                  -> 200 {"estado": "ok" | "degradado", "motivo": ...}

`crear_app()` permite inyectar el intérprete y el verificador de MLflow: así las pruebas usan un
extractor falso y nunca llaman al modelo.

Ejecutar:  uv run uvicorn novapedidos.api.app:app --port 8000
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse as _JSONResponseBase
from starlette.exceptions import HTTPException as StarletteHTTPException

from novapedidos import __version__
from novapedidos.api.esquemas import (
    ErrorCampo,
    EstadoServicio,
    RespuestaError,
    SolicitudInterpretar,
    traducir_error,
)
from novapedidos.config import Settings, get_settings
from novapedidos.dominio.catalogo import Catalogo, ClienteNoEncontrado
from novapedidos.dominio.modelos import RespuestaPedido
from novapedidos.llm.extractor import ErrorExtraccion, ExtractorLLM
from novapedidos.observabilidad.salud import EstadoDependencia, VerificadorMlflow
from novapedidos.observabilidad.trazas import Observabilidad, span
from novapedidos.observabilidad.trazas import activo as trazas_activas
from novapedidos.servicio import InterpreteDePedidos

log = logging.getLogger("novapedidos.api")
_raiz = logging.getLogger("novapedidos")
if not _raiz.handlers:  # uvicorn solo configura sus propios loggers
    _manejador = logging.StreamHandler()
    _manejador.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    _raiz.addHandler(_manejador)
    _raiz.setLevel(logging.INFO)
VENTANA_ERROR_LLM_S = 60  # /health reporta degradado si el modelo falló en el último minuto


class JSONResponse(_JSONResponseBase):
    """JSON con charset explícito: sin él, PowerShell 5.1 (Invoke-RestMethod) decodifica la respuesta como
    ISO-8859-1 y "¡Buenas tardes!" llega como "Â¡Buenas tardes!" (detectado probando el README)."""

    media_type = "application/json; charset=utf-8"


def _trazar_rechazo(request: Request, codigo: int, cuerpo: RespuestaError) -> None:
    """Las solicitudes rechazadas también dejan traza (auditoría Codex: un 422 no aparecía en MLflow).

    Solo se registran la ruta y los errores de validación, no el cuerpo recibido: puede ser enorme o
    no ser JSON. Si las trazas no están activas, `span` no hace nada.
    """
    entradas = {"metodo": request.method, "ruta": request.url.path}
    with span("solicitud_rechazada", "CHAIN", entradas) as s:
        s.salidas({"status": codigo, **cuerpo.model_dump()})


def _crear_interprete(settings: Settings) -> InterpreteDePedidos:
    catalogo = Catalogo.desde_directorio(settings.data_dir)
    return InterpreteDePedidos(catalogo, ExtractorLLM(settings, catalogo), settings.estrategia_resolucion)


def crear_app(
    settings: Settings | None = None,
    interprete: InterpreteDePedidos | None = None,
    verificador_mlflow: Callable[[], EstadoDependencia] | None = None,
    trazas: bool | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    # Por defecto hay trazas solo en el camino de producción (sin intérprete inyectado): las pruebas
    # no deben escribir en ningún servidor de MLflow.
    activar_trazas = settings.trazas_activas and interprete is None if trazas is None else trazas

    @asynccontextmanager
    async def ciclo_de_vida(app: FastAPI):
        app.state.interprete = interprete
        app.state.error_inicio = None
        app.state.ultimo_error_llm = None  # (instante, mensaje)
        app.state.verificar_mlflow = verificador_mlflow or VerificadorMlflow(
            settings.mlflow_tracking_uri, settings.mlflow_timeout_s
        )
        observabilidad = None
        if activar_trazas:  # en un hilo de fondo: MLflow caído no retrasa el arranque
            observabilidad = Observabilidad(settings.mlflow_tracking_uri, settings.mlflow_experimento)
            observabilidad.iniciar()
        app.state.observabilidad = observabilidad
        if app.state.interprete is None:
            try:
                app.state.interprete = _crear_interprete(settings)
                log.info("Catálogo y modelo listos (%s)", settings.modelo_llm)
            except Exception as e:  # datos faltantes, clave ausente...: el servicio sigue vivo y lo reporta
                app.state.error_inicio = str(e)
                log.error("No se pudo inicializar el intérprete: %s", e)
        yield
        if observabilidad:
            observabilidad.detener()

    app = FastAPI(
        title="NovaPedidos",
        version=__version__,
        description="Convierte mensajes de WhatsApp en pedidos estructurados para NovaDistribuidora.",
        lifespan=ciclo_de_vida,
        default_response_class=JSONResponse,
    )

    # ------------------------------------------------------------------ errores
    @app.exception_handler(RequestValidationError)
    async def _validacion(request: Request, exc: RequestValidationError) -> JSONResponse:
        errores = [traducir_error(e) for e in exc.errors()]
        resumen = "; ".join(f"{e.campo}: {e.mensaje}" for e in errores)
        cuerpo = RespuestaError(detail=f"Solicitud inválida. {resumen}", errores=errores)
        _trazar_rechazo(request, 422, cuerpo)
        return JSONResponse(status_code=422, content=cuerpo.model_dump())

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        # FastAPI responde 400 si el cuerpo no se puede decodificar (p. ej. JSON en cp1252 en vez de UTF-8,
        # típico de curl en Windows). Para el contrato es una solicitud inválida: 422 con explicación.
        if exc.status_code == 400 and "parsing the body" in str(exc.detail):
            cuerpo = RespuestaError(
                detail="Solicitud inválida. cuerpo: debe ser un objeto JSON codificado en UTF-8",
                errores=[ErrorCampo(campo="cuerpo", mensaje="debe ser un objeto JSON codificado en UTF-8")],
            )
            _trazar_rechazo(request, 422, cuerpo)
            return JSONResponse(status_code=422, content=cuerpo.model_dump())
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail}, headers=exc.headers)

    @app.exception_handler(Exception)
    async def _inesperado(request: Request, exc: Exception) -> JSONResponse:
        log.exception("Error no controlado")
        return JSONResponse(status_code=500, content={"detail": "Error interno del servicio"})

    # ------------------------------------------------------------------ endpoints
    @app.post(
        "/v1/pedidos/interpretar",
        response_model=RespuestaPedido,
        responses={
            404: {"model": RespuestaError},
            422: {"model": RespuestaError},
            503: {"model": RespuestaError},
        },
        summary="Interpreta los mensajes de un cliente y propone el pedido",
    )
    def interpretar(solicitud: SolicitudInterpretar, request: Request):
        estado = request.app.state
        if estado.interprete is None:
            return JSONResponse(
                status_code=503,
                content={"detail": f"El servicio no está inicializado: {estado.error_inicio}"},
            )
        try:
            resultado = estado.interprete.interpretar(
                solicitud.cliente_id, solicitud.fecha_hora, solicitud.mensajes
            )
        except ClienteNoEncontrado:
            return JSONResponse(
                status_code=404, content={"detail": f"El cliente {solicitud.cliente_id} no existe"}
            )
        except ErrorExtraccion as e:
            estado.ultimo_error_llm = (time.monotonic(), str(e))
            log.error("Modelo no disponible: %s", e)
            return JSONResponse(
                status_code=503,
                headers={"Retry-After": "5"},
                content={
                    "detail": "El modelo de lenguaje no está disponible en este momento; intente de nuevo."
                },
            )
        return resultado.respuesta

    @app.get("/health", response_model=EstadoServicio, summary="Estado del servicio y sus dependencias")
    def salud(request: Request) -> EstadoServicio:
        estado = request.app.state
        motivos: list[str] = []
        dependencias: dict[str, str] = {}

        if estado.interprete is None:
            dependencias["datos"] = "error"
            motivos.append(f"Intérprete no inicializado: {estado.error_inicio}")
        else:
            dependencias["datos"] = "ok"

        mlflow = estado.verificar_mlflow()
        dependencias["mlflow"] = "ok" if mlflow.disponible else "no_disponible"
        if not mlflow.disponible:
            motivos.append(mlflow.detalle)

        # Auditoría Codex: MLflow podía responder mientras el hilo de configuración aún no activaba las
        # trazas (las primeras solicitudes quedaban sin traza y /health decía "ok").
        if estado.observabilidad is None:
            dependencias["trazas"] = "desactivadas"  # TRAZAS_ACTIVAS=false (o pruebas): decisión explícita
        elif trazas_activas():
            dependencias["trazas"] = "ok"
        else:
            dependencias["trazas"] = "inicializando"
            motivos.append("Las trazas en MLflow aún no están activas (se reintenta en segundo plano)")

        ultimo = estado.ultimo_error_llm
        if ultimo and time.monotonic() - ultimo[0] < VENTANA_ERROR_LLM_S:
            dependencias["llm"] = "error_reciente"
            motivos.append("El modelo de lenguaje falló en el último minuto")
        else:
            dependencias["llm"] = "ok"

        modelo = getattr(getattr(estado.interprete, "extractor", None), "modelo", None)
        return EstadoServicio(
            estado="degradado" if motivos else "ok",
            motivo="; ".join(motivos) or None,
            dependencias=dependencias,
            version=__version__,
            modelo=modelo,
        )

    return app


app = crear_app()
