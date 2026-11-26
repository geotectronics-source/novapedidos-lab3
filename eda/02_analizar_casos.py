# /// script
# requires-python = ">=3.12"
# dependencies = ["pandas", "pyarrow"]
# ///
"""Inciso 1 - Análisis de los casos de desarrollo (mensajes_dev.jsonl).

Muestra la distribución de tipos, estados y motivos, y cuántos mensajes,
líneas y pendientes tiene cada caso.

Uso:  uv run --script eda/02_analizar_casos.py [--mensajes]
"""

import json
import sys
from collections import Counter
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent / "lab3"
casos = [
    json.loads(l)
    for l in (RAIZ / "ejemplos" / "mensajes_dev.jsonl").read_text(encoding="utf-8").splitlines()
    if l.strip()
]

print(f"Casos: {len(casos)}")
print(
    "Llaves de un caso:",
    list(casos[0].keys()),
    "| entrada:",
    list(casos[0]["entrada"].keys()),
    "| esperado:",
    list(casos[0]["esperado"].keys()),
)


def tabla(titulo, contador):
    print(f"\n== {titulo} ==")
    for k, v in contador.most_common():
        print(f"  {str(k):28s} {v:3d}")


tabla("tipo", Counter(c["tipo"] for c in casos))
tabla("estado esperado", Counter(c["esperado"]["estado"] for c in casos))
tabla("motivos_revision", Counter(m for c in casos for m in c["esperado"]["motivos_revision"]))
tabla("motivo de pendientes", Counter(p["motivo"] for c in casos for p in c["esperado"]["pendientes"]))
tabla("n.º de mensajes por caso", Counter(len(c["entrada"]["mensajes"]) for c in casos))
tabla("n.º de líneas por caso", Counter(len(c["esperado"]["lineas"]) for c in casos))
tabla("descuentos aplicados (%)", Counter(l["descuento_pct"] for c in casos for l in c["esperado"]["lineas"]))
tabla("clientes", Counter(c["entrada"]["cliente_id"] for c in casos))
tabla("hora >= 14:00", Counter(c["entrada"]["fecha_hora"][11:] >= "14:00" for c in casos))
print("\nCasos con sustituciones:", sum(bool(c["esperado"]["sustituciones"]) for c in casos))
print(
    "Pendientes con opciones vacías:",
    sum(1 for c in casos for p in c["esperado"]["pendientes"] if not p["opciones"]),
)
print(
    "Rango de fechas:",
    min(c["entrada"]["fecha_hora"] for c in casos),
    "->",
    max(c["entrada"]["fecha_hora"] for c in casos),
)

if "--mensajes" in sys.argv:
    for tipo in sorted({c["tipo"] for c in casos}):
        print(f"\n######## {tipo}")
        for c in casos:
            if c["tipo"] != tipo:
                continue
            e = c["esperado"]
            lineas = ", ".join(f"{l['sku']}x{l['cantidad']}" for l in e["lineas"])
            pend = "; ".join(f'{p["motivo"]}:"{p["texto"]}"{p["opciones"]}' for p in e["pendientes"])
            sust = ", ".join(
                f"{s['sku_solicitado']}->{s['sku_entregado']}x{s['cantidad']}" for s in e["sustituciones"]
            )
            print(
                f"{c['id']} {c['entrada']['cliente_id']} {c['entrada']['fecha_hora']} | {' || '.join(c['entrada']['mensajes'])}"
            )
            print(
                f"      => {e['estado']} [{lineas}] total={e['total']} entrega={e['fecha_entrega']}"
                f"{' sust=' + sust if sust else ''}{' pend=' + pend if pend else ''} motivos={e['motivos_revision']}"
            )
