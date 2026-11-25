"""Scorers de MLflow (`@scorer`): envuelven las funciones puras de `comparacion.py`.

Todos son por código (deterministas, gratis, reproducibles). Devuelven bool o número para que MLflow
los agregue (promedios). Latencia y costo se leen de la traza de cada predicción.
"""

from __future__ import annotations

from mlflow.entities import Feedback
from mlflow.genai.scorers import scorer

from novapedidos.dominio.catalogo import Catalogo
from novapedidos.evaluacion import comparacion as c


def _esp(expectations: dict) -> dict:
    return expectations["esperado"]


@scorer
def pedido_exacto(outputs, expectations) -> bool:
    return c.pedido_exacto(outputs, _esp(expectations))


@scorer
def estado_correcto(outputs, expectations) -> bool:
    return c.estado_correcto(outputs, _esp(expectations))


@scorer
def lineas_correctas(outputs, expectations) -> bool:
    return c.lineas_correctas(outputs, _esp(expectations))


@scorer
def montos_correctos(outputs, expectations) -> bool:
    return c.montos_correctos(outputs, _esp(expectations))


@scorer
def total_correcto(outputs, expectations) -> bool:
    return c.total_correcto(outputs, _esp(expectations))


@scorer
def fecha_correcta(outputs, expectations) -> bool:
    return c.fecha_correcta(outputs, _esp(expectations))


@scorer
def motivos_correctos(outputs, expectations) -> bool:
    return c.motivos_correctos(outputs, _esp(expectations))


@scorer
def pendientes_correctos(outputs, expectations) -> bool:
    return c.pendientes_correctos(outputs, _esp(expectations))


@scorer
def sustituciones_correctas(outputs, expectations) -> bool:
    return c.sustituciones_correctas(outputs, _esp(expectations))


@scorer
def lineas_f1(outputs, expectations) -> float:
    return c.lineas_f1(outputs, _esp(expectations))


@scorer
def contrato_valido(outputs) -> Feedback:
    problemas = c.problemas_de_contrato(outputs)
    return Feedback(value=not problemas, rationale="; ".join(problemas) or "cumple el contrato")


@scorer(aggregations=["mean", "median", "p90", "max"])
def latencia_s(trace) -> float:
    return (trace.info.execution_duration or 0) / 1000


@scorer(aggregations=["mean", "max"])
def costo_usd(trace) -> float:
    return float(trace.info.trace_metadata.get("costo_usd", 0) or 0)


def crear_scorers(catalogo: Catalogo) -> list:
    nombres = {p.sku: p.nombre for p in catalogo.productos.values()}

    @scorer
    def mensaje_coherente(outputs) -> bool:
        return c.mensaje_coherente(outputs, nombres)

    return [
        pedido_exacto, estado_correcto, lineas_correctas, montos_correctos, total_correcto, fecha_correcta,
        motivos_correctos, pendientes_correctos, sustituciones_correctas, lineas_f1, contrato_valido,
        mensaje_coherente, latencia_s, costo_usd,
    ]  # fmt: skip
