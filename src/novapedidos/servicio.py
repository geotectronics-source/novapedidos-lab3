"""Pipeline completo: mensajes -> LLM (extracción) -> resolución a SKU -> motor de reglas -> mensaje.

    1. Validar el cliente ANTES de llamar al modelo (404 sin gastar tokens).
    2. Extractor (LLM, salida estructurada): es_pedido, lo de siempre, menciones.
    3. Cada mención -> SKU (estrategia híbrida) -> Operacion, o Pendiente si es ambigua / no existe.
    4. Motor determinista (dominio/motor.py) -> PedidoCalculado.
    5. Plantilla -> mensaje_cliente.

Devuelve también los detalles intermedios (extracción, resoluciones, costo) para trazas y evaluación.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime

from novapedidos.dominio.catalogo import Catalogo
from novapedidos.dominio.mensaje import redactar_mensaje
from novapedidos.dominio.modelos import Accion, Motivo, Operacion, Pendiente, RespuestaPedido, Unidad
from novapedidos.dominio.motor import construir_pedido
from novapedidos.llm.extractor import Extractor, ResultadoExtraccion
from novapedidos.llm.prompts import VERSION_PROMPT
from novapedidos.observabilidad.trazas import etiquetar_traza, span
from novapedidos.resolucion.combinar import Estrategia, resolver_mencion
from novapedidos.resolucion.resolutor import Resolucion, Resolutor, TipoResolucion

# "suelt" = "72 jaboncitos rosa sueltos": el cliente dice explícitamente que son unidades (caso propio PA11).
_SUELTAS = re.compile(
    r"\b(botell|latit|lata|bolsit|bolsa|unidad|paquet|suelt|sobres\b|sobrecit)", re.IGNORECASE
)
_DOCENAS = re.compile(r"\bdocenas?\b", re.IGNORECASE)
# "un fardo y medio", "media caja": fracción de la unidad de venta. ("litro y medio" es una presentación.)
_FRACCION_VENTA = re.compile(
    r"(?<!litro )\by medi[oa]\b|\bmedi[oa] (fardo|caja|display|quintal)", re.IGNORECASE
)
# Red de seguridad para correcciones que el modelo marque como "agregar" ("de arroz que sean 3").
_CORRECCION = re.compile(r"\b(que sean|que sea|mejor|corrij\w*|corrig\w*)\b", re.IGNORECASE)


def cantidad_y_unidad(texto: str, cantidad: float | None) -> tuple[int | None, Unidad] | None:
    """Cantidad entera en la unidad que corresponde, o None si no es convertible (no se redondea).

    - Fracción de la unidad de venta ("un fardo y medio") -> None (cantidad_no_convertible).
    - Docenas -> unidades sueltas ("media docena" = 6 sueltas; el motor verifica la división exacta).
    """
    unidad = unidad_desde_texto(texto)
    if unidad is Unidad.DOCENA:
        sueltas = (1 if cantidad is None else cantidad) * 12
        return (int(sueltas), Unidad.SUELTA) if float(sueltas).is_integer() else None
    if unidad is Unidad.VENTA and _FRACCION_VENTA.search(texto):
        return None
    if cantidad is not None and not float(cantidad).is_integer():
        return None
    return (None if cantidad is None else int(cantidad)), unidad


def unidad_desde_texto(texto: str) -> Unidad:
    """La unidad se valida con código sobre el texto LITERAL del cliente, no se confía al LLM.

    En la primera corrida, el modelo marcó "5 energía max 473 ml" como unidades sueltas (vio "473 ml").
    Política §2: sin una palabra de unidad suelta, la cantidad es en unidades de venta.
    ("sobre" en singular es parte del nombre "Shampoo Brisa sobre 10 ml", por eso solo cuenta "sobres".)
    """
    if _DOCENAS.search(texto):
        return Unidad.DOCENA
    if _SUELTAS.search(texto):
        return Unidad.SUELTA
    return Unidad.VENTA


def texto_sin_cantidad(texto: str, cantidad: float | None) -> str:
    """'arroz quintal: 2' -> 'arroz quintal'. Así el número del pedido no se confunde con una presentación."""
    if cantidad is None:
        return texto
    numero = re.escape(str(int(cantidad)) if float(cantidad).is_integer() else str(cantidad))
    medida = r"\s*(ml|l|lt|litros?|lb|libras?|g|gr|gramos?|rollos?)\b"  # "600 ml" es presentación
    return re.sub(rf"(?<![\d.,]){numero}(?![\d.,]|{medida})", " ", texto, count=1, flags=re.IGNORECASE)


@dataclass
class ResultadoInterpretacion:
    respuesta: RespuestaPedido
    extraccion: ResultadoExtraccion
    resoluciones: list[tuple[str, Resolucion]] = field(default_factory=list)  # (producto, resolución)


class InterpreteDePedidos:
    def __init__(
        self,
        catalogo: Catalogo,
        extractor: Extractor,
        estrategia: Estrategia | str = Estrategia.HIBRIDA,
        resolutor: Resolutor | None = None,
    ) -> None:
        self.catalogo = catalogo
        self.extractor = extractor
        self.estrategia = Estrategia(estrategia)
        self.resolutor = resolutor or Resolutor(catalogo)

    def interpretar(
        self, cliente_id: str, recibido: datetime, mensajes: Sequence[str]
    ) -> ResultadoInterpretacion:
        entradas = {
            "cliente_id": cliente_id,
            "fecha_hora": recibido.isoformat(timespec="minutes"),
            "mensajes": list(mensajes),
        }
        with span("interpretar_pedido", "CHAIN", entradas) as raiz:
            self.catalogo.cliente(cliente_id)  # lanza ClienteNoEncontrado antes de gastar tokens

            with span("extraccion", "CHAIN", {"mensajes": list(mensajes)}) as s:
                ext = self.extractor.extraer(mensajes)  # adentro: span del modelo (mlflow.langchain.autolog)
                s.salidas(ext.extraccion.model_dump())
                s.atributos(
                    modelo=ext.modelo, costo_usd=ext.costo_usd, tokens_entrada=ext.tokens_entrada,
                    tokens_salida=ext.tokens_salida, intentos=ext.intentos,
                )  # fmt: skip

            with span(
                "resolucion", "PARSER", {"menciones": [m.model_dump() for m in ext.extraccion.menciones]}
            ) as s:
                base = frozenset()  # SKU de "lo de siempre": contexto para correcciones y exclusiones
                if ext.extraccion.pide_lo_de_siempre:
                    ultimo = self.catalogo.ultimo_pedido_entregado(cliente_id, antes_de=recibido.date())
                    base = frozenset(sku for sku, _ in ultimo.lineas) if ultimo else frozenset()
                operaciones, pendientes, resoluciones = self._a_operaciones(ext, base)
                s.salidas({
                    "resoluciones": [
                        {"producto": p, "tipo": r.tipo.value, "skus": list(r.skus), "metodo": r.metodo}
                        for p, r in resoluciones
                    ],
                    "operaciones": [o.model_dump(mode="json") for o in operaciones],
                    "pendientes": [p.model_dump(mode="json") for p in pendientes],
                })  # fmt: skip

            with span("motor_reglas", "CHAIN", {"operaciones": len(operaciones)}) as s:
                pedido = construir_pedido(
                    self.catalogo,
                    cliente_id,
                    recibido,
                    es_pedido=ext.extraccion.es_pedido,
                    pide_lo_de_siempre=ext.extraccion.pide_lo_de_siempre,
                    operaciones=operaciones,
                    pendientes_resolucion=pendientes,
                )
                s.salidas(pedido.model_dump(mode="json"))

            respuesta = RespuestaPedido(
                **pedido.model_dump(), mensaje_cliente=redactar_mensaje(pedido, self.catalogo, recibido)
            )
            raiz.salidas(respuesta.model_dump(mode="json"))
            etiquetar_traza(
                tags={
                    "estado": respuesta.estado.value,
                    "cliente_id": cliente_id,
                    "modelo": ext.modelo,
                    "estrategia": self.estrategia.value,
                    "version_prompt": VERSION_PROMPT,
                    "motivos": ",".join(m.value for m in respuesta.motivos_revision) or "ninguno",
                },
                metadata={
                    "costo_usd": f"{ext.costo_usd:.6f}",
                    "tokens_entrada": ext.tokens_entrada,
                    "tokens_salida": ext.tokens_salida,
                    "latencia_llm_s": f"{ext.latencia_s:.3f}",
                    "total_q": respuesta.total,
                    "lineas": len(respuesta.lineas),
                },
            )
        return ResultadoInterpretacion(respuesta=respuesta, extraccion=ext, resoluciones=resoluciones)

    def _a_operaciones(
        self, ext: ResultadoExtraccion, base: frozenset[str] = frozenset()
    ) -> tuple[list[Operacion], list[Pendiente], list[tuple[str, Resolucion]]]:
        operaciones: list[Operacion] = []
        pendientes: list[Pendiente] = []
        resoluciones: list[tuple[str, Resolucion]] = []
        resueltos: set[str] = set()
        for m in ext.extraccion.menciones:
            accion = Accion(m.accion)
            if accion is Accion.AGREGAR and _CORRECCION.search(m.texto):
                accion = Accion.CORREGIR  # "de arroz que sean 3": reemplaza, no suma (§2)
            r = resolver_mencion(
                self.resolutor,
                m.producto,
                m.skus_posibles,
                self.estrategia,
                texto_literal=texto_sin_cantidad(m.texto, m.cantidad)
                if accion is not Accion.QUITAR
                else None,
                skus_previos=frozenset(resueltos),
            )
            if accion is not Accion.AGREGAR and r.tipo is TipoResolucion.AMBIGUO:
                # "ah no, de naranjita mejor 4": una corrección o exclusión se refiere a algo YA pedido.
                # Si de las opciones solo una está en el pedido (o en "lo de siempre"), es esa.
                en_contexto = set(r.skus) & (resueltos | base)
                if len(en_contexto) == 1:
                    r = Resolucion(TipoResolucion.UNICO, tuple(en_contexto), "contexto")
            resoluciones.append((m.producto, r))
            if r.tipo is TipoResolucion.UNICO and accion is Accion.QUITAR:
                operaciones.append(Operacion(sku=r.sku, texto=m.texto, accion=accion))
            elif r.tipo is TipoResolucion.UNICO:
                resueltos.add(r.sku)
                cantidad = cantidad_y_unidad(m.texto, m.cantidad)
                if cantidad is None:  # "un fardo y medio": no se redondea -> revisión
                    pendiente = Pendiente(
                        motivo=Motivo.CANTIDAD_NO_CONVERTIBLE, texto=m.texto, opciones=[r.sku]
                    )
                    if accion is Accion.CORREGIR:  # la corrección invalida lo pedido antes de ese producto
                        operaciones.append(Operacion(sku=r.sku, texto=m.texto, accion=Accion.QUITAR))
                    if pendiente not in pendientes:
                        pendientes.append(pendiente)
                    continue
                operaciones.append(
                    Operacion(
                        sku=r.sku, texto=m.texto, accion=accion, cantidad=cantidad[0], unidad=cantidad[1]
                    )
                )
            elif accion is Accion.QUITAR:
                # "sin el aceite" con aceite ambiguo: se quita cualquiera de las opciones.
                # Si no existe, no hay nada que quitar.
                operaciones += [Operacion(sku=s, texto=m.texto, accion=accion) for s in r.skus]
            else:
                pendiente = r.a_pendiente(m.producto)
                if pendiente not in pendientes:
                    pendientes.append(pendiente)
        return operaciones, pendientes, resoluciones
