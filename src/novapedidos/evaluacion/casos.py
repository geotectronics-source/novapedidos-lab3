"""Conjuntos de evaluación: casos publicados (mensajes_dev.jsonl) + casos propios (evaluacion/casos_propios.jsonl).

Ambos con el mismo formato: {id, tipo, entrada: {cliente_id, fecha_hora, mensajes}, esperado: {...}}.
"""

from __future__ import annotations

import json
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[3]
CASOS_PROPIOS = RAIZ / "evaluacion" / "casos_propios.jsonl"


def leer_jsonl(ruta: Path) -> list[dict]:
    return [
        json.loads(linea) for linea in Path(ruta).read_text(encoding="utf-8").splitlines() if linea.strip()
    ]


def cargar(conjunto: str, data_dir: Path) -> list[dict]:
    """conjunto: dev | propios | todos."""
    casos: list[dict] = []
    if conjunto in ("dev", "todos"):
        casos += [
            {**c, "origen": "dev"} for c in leer_jsonl(Path(data_dir) / "ejemplos" / "mensajes_dev.jsonl")
        ]
    if conjunto in ("propios", "todos"):
        casos += [{**c, "origen": "propio"} for c in leer_jsonl(CASOS_PROPIOS)]
    if not casos:
        raise ValueError(f"Conjunto desconocido o vacío: {conjunto}")
    return casos


def a_registros(casos: list[dict]) -> list[dict]:
    """Formato de mlflow.genai.evaluate: predict_fn(**inputs); la verdad va en expectations."""
    return [
        {
            "inputs": c["entrada"],
            "expectations": {
                "esperado": c["esperado"],
                "caso_id": c["id"],
                "tipo": c["tipo"],
                "origen": c["origen"],
            },
        }
        for c in casos
    ]
