"""Cómo se combinan el LLM y el resolutor determinista para decidir el SKU de cada mención.

Tres estrategias (configurables con ESTRATEGIA_RESOLUCION; se comparan en el Inciso 8):

- determinista: el LLM solo normaliza el texto (`producto`); decide el resolutor.
- llm:          decide el LLM con sus `skus_posibles` (filtrados al catálogo: nunca un SKU inventado).
- hibrida:      (por defecto) el resolutor decide y el LLM lo complementa:
    * resolutor ÚNICO y el LLM coincide (o no opina)       -> ÚNICO
    * resolutor ÚNICO y el LLM propone OTROS SKU            -> AMBIGUO con ambos (discrepancia: revisión)
    * resolutor ÚNICO, pero el texto literal del cliente es ambiguo y contiene ese SKU
                                                            -> AMBIGUO (el LLM agregó un detalle que el
                                                               cliente no dijo: "aceite"->"aceite dorado")
    * resolutor AMBIGUO, pero el texto literal del cliente lo resuelve a uno de esos SKU
                                                            -> ÚNICO (el LLM quitó un detalle que el cliente
                                                               sí dijo, p. ej. "arroz quintal" -> "arroz")
    * resolutor AMBIGUO                                     -> AMBIGUO (el LLM no puede elegir por el cliente)
    * resolutor NO_EXISTE porque no reconoció NADA (jerga que no está en el vocabulario) y el LLM sí
      propone SKU del catálogo                              -> se usa la propuesta del LLM
    * resolutor NO_EXISTE por un detalle que contradice (otro sabor, otra presentación) -> NO_EXISTE
"""

from __future__ import annotations

from collections.abc import Iterable
from enum import StrEnum

from novapedidos.resolucion.resolutor import Resolucion, Resolutor, TipoResolucion


class Estrategia(StrEnum):
    HIBRIDA = "hibrida"
    DETERMINISTA = "determinista"
    LLM = "llm"


def _desde_skus(skus: tuple[str, ...], metodo: str) -> Resolucion:
    if not skus:
        return Resolucion(TipoResolucion.NO_EXISTE, (), metodo)
    tipo = TipoResolucion.UNICO if len(skus) == 1 else TipoResolucion.AMBIGUO
    return Resolucion(tipo, skus, metodo)


def resolver_mencion(
    resolutor: Resolutor,
    producto: str,
    skus_llm: Iterable[str],
    estrategia: Estrategia = Estrategia.HIBRIDA,
    *,
    texto_literal: str | None = None,
    skus_previos: frozenset[str] = frozenset(),
) -> Resolucion:
    """Decide el SKU de una mención.

    `texto_literal`: el fragmento tal como lo escribió el cliente (detecta detalles agregados o quitados).
    `skus_previos`: SKU ya resueltos en menciones anteriores del mismo pedido (contexto de correcciones).
    """
    validos = tuple(sorted({s for s in skus_llm if s in resolutor.catalogo.productos}))  # nunca inventar

    if estrategia is Estrategia.LLM:
        return _desde_skus(validos, "llm")

    r = resolutor.resolver(producto)
    if estrategia is Estrategia.DETERMINISTA:
        return r

    literal = resolutor.resolver(texto_literal) if texto_literal else None

    if r.tipo is TipoResolucion.UNICO:
        if validos and r.sku not in validos:
            return Resolucion(TipoResolucion.AMBIGUO, tuple(sorted({*r.skus, *validos})), "discrepancia")
        if (
            literal
            and literal.tipo is TipoResolucion.AMBIGUO
            and r.sku in literal.skus
            and r.sku not in skus_previos
        ):
            return Resolucion(TipoResolucion.AMBIGUO, literal.skus, "ambiguedad_en_texto")
        return r
    if r.tipo is TipoResolucion.AMBIGUO:
        # El LLM quitó el detalle que distingue ("arroz quintal" -> "arroz"), pero el cliente sí lo dijo.
        if literal and literal.tipo is TipoResolucion.UNICO and literal.sku in r.skus:
            return Resolucion(TipoResolucion.UNICO, literal.skus, "detalle_en_texto")
        return r
    if r.tipo is TipoResolucion.NO_EXISTE and r.metodo == "sin_coincidencias" and validos:
        return _desde_skus(validos, "llm_respaldo")
    return r
