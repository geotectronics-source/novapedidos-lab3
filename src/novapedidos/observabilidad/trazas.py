"""Trazas en MLflow, diseñadas para que MLflow NUNCA bloquee ni rompa la API.

Mediciones que motivan el diseño (Inciso 7, ver DECISIONES.md):
- Con la configuración por defecto, `mlflow.set_experiment` contra un MLflow caído no terminó en 150 s
  (7 reintentos con espera exponencial). -> reintentos HTTP en 0, timeout de 2 s, y la configuración se
  hace en un HILO de fondo que reintenta cada 15 s hasta que MLflow responda.
- Con exportación asíncrona, trazar agrega ~1 ms por solicitud; si MLflow cae a mitad de la operación las
  solicitudes no se bloquean (las trazas de ese periodo se pierden con una advertencia en el log) y al
  volver MLflow la exportación se reanuda sola.

Uso desde el código de la aplicación:

    with span("resolucion", tipo="PARSER", entradas={...}) as s:
        ...
        s.salidas(resultado)

Si la observabilidad no está activa (pruebas, MLflow nunca disponible), `span` no hace nada.
"""

from __future__ import annotations

import logging
import os
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

# Deben fijarse ANTES de importar mlflow (algunas se leen al importar).
os.environ.setdefault("MLFLOW_ENABLE_ASYNC_TRACE_LOGGING", "true")
os.environ.setdefault("MLFLOW_HTTP_REQUEST_MAX_RETRIES", "0")
os.environ.setdefault("MLFLOW_HTTP_REQUEST_TIMEOUT", "2")
os.environ.setdefault("MLFLOW_ASYNC_TRACE_LOGGING_RETRY_TIMEOUT", "10")
os.environ.setdefault("MLFLOW_DISABLE_AGENT_HINT", "1")

import mlflow  # noqa: E402

log = logging.getLogger("novapedidos.observabilidad")
REINTENTO_CONFIGURACION_S = 15.0

_activo = False
_experimento_id: str | None = None
_lock = threading.Lock()


def activo() -> bool:
    return _activo


def experimento_id() -> str | None:
    return _experimento_id


class Observabilidad:
    """Configura MLflow en segundo plano y activa las trazas cuando el servidor responde."""

    def __init__(self, tracking_uri: str, experimento: str) -> None:
        self.tracking_uri = tracking_uri
        self.experimento = experimento
        self._detener = threading.Event()
        self._hilo: threading.Thread | None = None
        self.ultimo_error: str | None = None

    def iniciar(self) -> None:
        mlflow.set_tracking_uri(self.tracking_uri)
        self._hilo = threading.Thread(
            target=self._configurar_con_reintentos, name="mlflow-config", daemon=True
        )
        self._hilo.start()

    def _configurar_con_reintentos(self) -> None:
        global _activo, _experimento_id
        while not self._detener.is_set():
            try:
                exp = mlflow.set_experiment(self.experimento)
                mlflow.langchain.autolog(log_traces=True, silent=True)
                with _lock:
                    _experimento_id, _activo = exp.experiment_id, True
                self.ultimo_error = None
                log.info("Trazas activas en MLflow %s (experimento %s)", self.tracking_uri, exp.experiment_id)
                return
            except Exception as e:  # MLflow caído o lento: la API sigue sin trazas y se reintenta
                self.ultimo_error = f"{type(e).__name__}: {e}"[:300]
                log.warning(
                    "MLflow no disponible (%s); se reintenta en %.0f s",
                    self.tracking_uri,
                    REINTENTO_CONFIGURACION_S,
                )
                self._detener.wait(REINTENTO_CONFIGURACION_S)

    def detener(self, timeout_flush_s: float = 5.0) -> None:
        """Al apagar: deja de reintentar y envía las trazas pendientes (espera hasta timeout_flush_s)."""
        self._detener.set()
        if _activo:
            hilo = threading.Thread(target=_flush_seguro, daemon=True)
            hilo.start()
            hilo.join(timeout_flush_s)


def _flush_seguro() -> None:
    try:
        mlflow.flush_trace_async_logging()
    except Exception:  # pragma: no cover - solo al apagar
        log.debug("No se pudieron enviar las trazas pendientes", exc_info=True)


def desactivar() -> None:
    """Para pruebas: vuelve al modo sin trazas."""
    global _activo, _experimento_id
    with _lock:
        _activo, _experimento_id = False, None


# ------------------------------------------------------------------ API para la aplicación
class _Span:
    def __init__(self, real: Any | None) -> None:
        self._real = real

    def salidas(self, valor: Any) -> None:
        if self._real is not None:
            _seguro(self._real.set_outputs, valor)

    def atributos(self, **valores: Any) -> None:
        if self._real is not None:
            _seguro(self._real.set_attributes, valores)


@contextmanager
def span(nombre: str, tipo: str = "UNKNOWN", entradas: Any = None, **atributos: Any) -> Iterator[_Span]:
    """Span de MLflow si la observabilidad está activa; si no, un objeto que no hace nada.

    Cualquier error de MLflow se traga: la observabilidad nunca debe tumbar una solicitud.
    """
    if not _activo:
        yield _Span(None)
        return
    try:
        cm = mlflow.start_span(name=nombre, span_type=tipo)
        real = cm.__enter__()
    except Exception:
        log.debug("No se pudo abrir el span %s", nombre, exc_info=True)
        yield _Span(None)
        return
    envoltura = _Span(real)
    if entradas is not None:
        _seguro(real.set_inputs, entradas)
    if atributos:
        envoltura.atributos(**atributos)
    try:
        yield envoltura
    except BaseException as e:
        _seguro(cm.__exit__, type(e), e, e.__traceback__)
        raise
    else:
        _seguro(cm.__exit__, None, None, None)


def etiquetar_traza(tags: dict[str, Any] | None = None, metadata: dict[str, Any] | None = None) -> None:
    """Etiquetas filtrables en la UI de MLflow (estado, modelo, versión del prompt...)."""
    if _activo:
        _seguro(
            mlflow.update_current_trace,
            tags={k: str(v) for k, v in (tags or {}).items()},
            metadata={k: str(v) for k, v in (metadata or {}).items()},
        )


def _seguro(funcion, *args, **kwargs) -> None:
    try:
        funcion(*args, **kwargs)
    except Exception:
        log.debug("Error de MLflow ignorado en %s", getattr(funcion, "__name__", funcion), exc_info=True)
