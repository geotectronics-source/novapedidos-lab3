"""Compara varias configuraciones (modelos y estrategias) en calidad, latencia y costo.

    uv run python -m novapedidos.evaluacion.comparar                 # todas
    uv run python -m novapedidos.evaluacion.comparar --solo haiku    # filtra por nombre

Cada configuración es un run de MLflow (experimento novapedidos-evaluacion). Al final escribe en
evidencia/comparacion/: resultados.csv, resultados.md (tabla + desglose por tipo de caso) y comparacion.png.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

from novapedidos.evaluacion.casos import RAIZ
from novapedidos.evaluacion.ejecutar import evaluar

SALIDA = RAIZ / "evidencia" / "comparacion"

# (nombre, modelo, estrategia, workers, rps). rps bajo para modelos con límite de 20 solicitudes/minuto.
CONFIGURACIONES = [
    ("haiku-hibrida", "anthropic/claude-haiku-5.5", "hibrida", 4, "auto"),
    ("haiku-hibrida-rep2", "anthropic/claude-haiku-5.5", "hibrida", 4, "auto"),  # variabilidad entre corridas
    ("haiku-determinista", "anthropic/claude-haiku-5.5", "determinista", 4, "auto"),
    ("haiku-solo-llm", "anthropic/claude-haiku-5.5", "llm", 4, "auto"),
    ("deepseek-flash-hibrida", "deepseek/deepseek-v4.1-flash", "hibrida", 4, "auto"),
    ("gpt6-luna-hibrida", "openai/gpt-6-luna", "hibrida", 2, "0.3"),
    ("sonnet-hibrida", "anthropic/claude-sonnet-5.5", "hibrida", 2, "0.3"),  # también 20 solicitudes/min
]

COLUMNAS = [
    "nombre", "modelo", "estrategia", "n_casos", "errores", "pedido_exacto", "estado_correcto", "lineas_correctas",
    "montos_correctos", "fecha_correcta", "motivos_correctos", "pendientes_correctos", "lineas_f1", "contrato_valido",
    "mensaje_coherente", "latencia_p50_s", "latencia_p95_s", "costo_por_1000_pedidos_usd", "costo_total_usd",
]  # fmt: skip


def _tabla_md(filas: list[dict], columnas: list[str]) -> str:
    def fmt(v):
        if isinstance(v, float):
            return f"{v:.3f}" if v < 10 else f"{v:.1f}"
        return str(v)

    lineas = ["| " + " | ".join(columnas) + " |", "|" + "---|" * len(columnas)]
    lineas += ["| " + " | ".join(fmt(f.get(c, "")) for c in columnas) + " |" for f in filas]
    return "\n".join(lineas)


def _por_tipo(detalle: Path) -> dict[str, tuple[int, int]]:
    datos = json.loads(detalle.read_text(encoding="utf-8"))
    conteo: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for caso in datos["casos"]:
        clave = f"{caso['origen']}:{caso['tipo']}"
        conteo[clave][0] += bool(caso.get("pedido_exacto"))
        conteo[clave][1] += 1
    return {k: (v[0], v[1]) for k, v in sorted(conteo.items())}


def _grafico(filas: list[dict], destino: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ejes = plt.subplots(1, 2, figsize=(13, 5))
    for f in filas:
        x, y = f["costo_por_1000_pedidos_usd"], 100 * f["pedido_exacto"]
        ejes[0].scatter(x, y, s=80)
        ejes[0].annotate(f["nombre"], (x, y), textcoords="offset points", xytext=(5, 5), fontsize=8)
        ejes[1].scatter(f["latencia_p50_s"], y, s=80)
        ejes[1].annotate(
            f["nombre"], (f["latencia_p50_s"], y), textcoords="offset points", xytext=(5, 5), fontsize=8
        )
    ejes[0].set(xscale="log", xlabel="Costo por 1 000 pedidos (USD, escala log)", ylabel="Pedidos exactos (%)",
                title="Calidad vs. costo")  # fmt: skip
    ejes[1].set(xlabel="Latencia p50 (s)", ylabel="Pedidos exactos (%)", title="Calidad vs. latencia")
    for eje in ejes:
        eje.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(destino, dpi=130)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument(
        "--solo", default=None, help="corre solo las configuraciones cuyo nombre contenga este texto"
    )
    p.add_argument("--conjunto", default="todos", choices=["dev", "propios", "todos"])
    a = p.parse_args()
    detalle_dir = SALIDA / "detalle"
    filas = []
    for nombre, modelo, estrategia, workers, rps in CONFIGURACIONES:
        if a.solo and a.solo not in nombre:
            continue
        print(f"\n=== {nombre} ({modelo}, {estrategia}) ===", flush=True)
        resumen = evaluar(
            modelo, estrategia, a.conjunto, workers=workers, rps=rps, nombre=nombre, salida=detalle_dir
        )
        filas.append({"nombre": nombre, **resumen})
        print(
            json.dumps({k: resumen.get(k) for k in COLUMNAS if k in resumen}, ensure_ascii=False), flush=True
        )

    # Acumula con corridas anteriores (permite correr configuraciones por separado)
    SALIDA.mkdir(parents=True, exist_ok=True)
    acumulado = SALIDA / "resultados.json"
    previas: dict[str, dict] = {}
    for archivo in sorted(
        detalle_dir.glob("*.json")
    ):  # corridas anteriores (aunque la comparación se haya cortado)
        resumen = json.loads(archivo.read_text(encoding="utf-8"))["resumen"]
        previas[archivo.stem] = {"nombre": archivo.stem, **resumen}
    if acumulado.exists():
        previas.update({f["nombre"]: f for f in json.loads(acumulado.read_text(encoding="utf-8"))})
    previas.update({f["nombre"]: f for f in filas})
    todas = [previas[n] for n, *_ in CONFIGURACIONES if n in previas]
    acumulado.write_text(json.dumps(todas, ensure_ascii=False, indent=1), encoding="utf-8")

    import csv

    with (SALIDA / "resultados.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNAS, extrasaction="ignore")
        w.writeheader()
        w.writerows(todas)
    _grafico(todas, SALIDA / "comparacion.png")

    md = ["# Comparación de alternativas", "", f"Conjunto: `{a.conjunto}`. Métricas = proporción de casos (0–1).", "",
          _tabla_md(todas, COLUMNAS), "", "![Comparación](comparacion.png)", "", "## Pedidos exactos por tipo de caso", ""]  # fmt: skip
    tipos = {f["nombre"]: _por_tipo(detalle_dir / f"{f['nombre']}.json") for f in todas
             if (detalle_dir / f"{f['nombre']}.json").exists()}  # fmt: skip
    claves = sorted({k for t in tipos.values() for k in t})
    filas_tipo = [
        {"tipo": k, **{n: f"{t[k][0]}/{t[k][1]}" if k in t else "" for n, t in tipos.items()}} for k in claves
    ]
    md.append(_tabla_md(filas_tipo, ["tipo", *tipos]))
    (SALIDA / "resultados.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print(f"\nResultados en {SALIDA}")


if __name__ == "__main__":
    main()
