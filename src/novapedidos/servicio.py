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
from novapedidos.dominio.modelos import Accion, Operacion, Pendiente, RespuestaPedido, Unidad
from novapedidos.dominio.motor import construir_pedido
from novapedidos.llm.extractor import Extractor, ResultadoExtraccion
from novapedidos.resolucion.combinar import Estrategia, resolver_mencion
from novapedidos.resolucion.resolutor import Resolucion, Resolutor, TipoResolucion

_SUELTAS = re.compile(r"\b(botell|latit|lata|bolsit|bolsa|unidad|sobres\b|sobrecit)", re.IGNORECASE)
_DOCENAS = re.compile(r"\bdocenas?\b", re.IGNORECASE)


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


def texto_sin_cantidad(texto: str, cantidad: int | None) -> str:
    """'arroz quintal: 2' -> 'arroz quintal'. Así el número del pedido no se confunde con una presentación."""
    if cantidad is None:
        return texto
    return re.sub(rf"(?<![\d.,]){cantidad}(?![\d.,]|\s*(ml|l|lt|litros?|lb|libras?|g|gr|gramos?|rollos?)\b)",
                  " ", texto, count=1, flags=re.IGNORECASE)  # fmt: skip


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
        self.catalogo.cliente(cliente_id)  # lanza ClienteNoEncontrado antes de gastar tokens
        ext = self.extractor.extraer(mensajes)
        operaciones, pendientes, resoluciones = self._a_operaciones(ext)
        pedido = construir_pedido(
            self.catalogo,
            cliente_id,
            recibido,
            es_pedido=ext.extraccion.es_pedido,
            pide_lo_de_siempre=ext.extraccion.pide_lo_de_siempre,
            operaciones=operaciones,
            pendientes_resolucion=pendientes,
        )
        respuesta = RespuestaPedido(
            **pedido.model_dump(), mensaje_cliente=redactar_mensaje(pedido, self.catalogo, recibido)
        )
        return ResultadoInterpretacion(respuesta=respuesta, extraccion=ext, resoluciones=resoluciones)

    def _a_operaciones(
        self, ext: ResultadoExtraccion
    ) -> tuple[list[Operacion], list[Pendiente], list[tuple[str, Resolucion]]]:
        operaciones: list[Operacion] = []
        pendientes: list[Pendiente] = []
        resoluciones: list[tuple[str, Resolucion]] = []
        resueltos: set[str] = set()
        for m in ext.extraccion.menciones:
            accion = Accion(m.accion)
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
            resoluciones.append((m.producto, r))
            if r.tipo is TipoResolucion.UNICO:
                resueltos.add(r.sku)
                operaciones.append(
                    Operacion(
                        sku=r.sku,
                        texto=m.texto,
                        accion=accion,
                        cantidad=m.cantidad,
                        unidad=unidad_desde_texto(m.texto),
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
