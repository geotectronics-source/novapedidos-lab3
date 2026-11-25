"""Evalúa UNA configuración (modelo + estrategia) en MLflow con `mlflow.genai.evaluate`.

    uv run python -m novapedidos.evaluacion.ejecutar --modelo anthropic/claude-haiku-5.5 --conjunto todos

Cada ejecución crea un run en el experimento `novapedidos-evaluacion` con:
- parámetros (modelo, estrategia, versión del prompt, conjunto, n.º de casos),
- métricas por scorer (exactitud, estado, líneas, montos, fecha, motivos...) + latencia p50/p95 y costo,
- una traza por caso (con sus spans) y la tabla de resultados por caso como artefacto.
"""

from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime
from pathlib import Path

# En la evaluación, cada traza debe guardarse ANTES de calificarla (MLflow arma la respuesta desde la traza).
# Con exportación asíncrona y el MLflow local cargado, se perdieron 94 de 132 trazas de una configuración.
# Se fija antes de importar mlflow (la API, en cambio, usa exportación asíncrona para no frenar solicitudes).
os.environ["MLFLOW_ENABLE_ASYNC_TRACE_LOGGING"] = "false"

import mlflow  # noqa: E402

from novapedidos.config import get_settings
from novapedidos.dominio.catalogo import Catalogo
from novapedidos.evaluacion.casos import a_registros, cargar
from novapedidos.evaluacion.scorers import crear_scorers
from novapedidos.llm.extractor import ExtractorLLM
from novapedidos.llm.prompts import VERSION_PROMPT
from novapedidos.observabilidad import trazas
from novapedidos.servicio import InterpreteDePedidos

EXPERIMENTO = "novapedidos-evaluacion"
CRITERIOS = [
    "pedido_exacto", "estado_correcto", "lineas_correctas", "montos_correctos", "total_correcto", "fecha_correcta",
    "motivos_correctos", "pendientes_correctos", "sustituciones_correctas", "lineas_f1", "contrato_valido",
    "mensaje_coherente",
]  # fmt: skip


def _valores(df, nombre: str) -> list[float]:
    col = f"{nombre}/value"
    if col not in df.columns:
        return []
    return [float(v) for v in df[col].tolist() if v is not None and v == v]


def _percentil(valores: list[float], q: float) -> float:
    if not valores:
        return float("nan")
    ordenados = sorted(valores)
    return ordenados[min(len(ordenados) - 1, int(round(q * (len(ordenados) - 1))))]


def _clave(entrada: dict) -> tuple:
    return entrada.get("cliente_id"), entrada.get("fecha_hora"), tuple(entrada.get("mensajes") or ())


def filas_por_caso(df, casos: list[dict]) -> list[dict]:
    """Detalle por caso desde result_df (columnas `<criterio>/value`, request, response).

    El caso se identifica por `caso_id/value` y, si faltara, por su entrada (cliente, fecha, mensajes).
    """
    por_id = {c["id"]: c for c in casos}
    por_entrada = {_clave(c["entrada"]): c for c in casos}
    filas = []
    for _, f in df.iterrows():
        caso = por_id.get(f.get("caso_id/value")) or por_entrada.get(_clave(f.get("request") or {}), {})
        filas.append({
            "caso_id": caso.get("id"), "tipo": caso.get("tipo"), "origen": caso.get("origen"),
            **{k: f.get(f"{k}/value") for k in [*CRITERIOS, "latencia_s", "costo_usd"]},
            "obtenido": f.get("response"), "esperado": caso.get("esperado"), "inputs": f.get("request"),
            "trace_id": f.get("trace_id"),
        })  # fmt: skip
    return sorted(filas, key=lambda x: str(x["caso_id"]))


def evaluar(
    modelo: str,
    estrategia: str = "hibrida",
    conjunto: str = "todos",
    limite: int | None = None,
    workers: int = 4,
    rps: str = "auto",
    nombre: str | None = None,
    tracking_uri: str | None = None,
    salida: Path | None = None,
) -> dict:
    settings = get_settings()
    trazas.activar_sincrono(tracking_uri or settings.mlflow_tracking_uri, EXPERIMENTO)
    catalogo = Catalogo.desde_directorio(settings.data_dir)
    interprete = InterpreteDePedidos(catalogo, ExtractorLLM(settings, catalogo, modelo=modelo), estrategia)
    casos = cargar(conjunto, settings.data_dir)[:limite]

    def predecir(cliente_id: str, fecha_hora: str, mensajes: list[str]) -> dict:
        try:
            r = interprete.interpretar(cliente_id, datetime.fromisoformat(fecha_hora), mensajes)
            return r.respuesta.model_dump(mode="json")
        except Exception as e:  # se registra como falla del caso, no tumba la evaluación
            return {"error": f"{type(e).__name__}: {e}"[:500]}

    os.environ["MLFLOW_GENAI_EVAL_MAX_WORKERS"] = str(workers)
    os.environ["MLFLOW_GENAI_EVAL_PREDICT_RATE_LIMIT"] = str(rps)
    nombre = nombre or f"{modelo.split('/')[-1]}|{estrategia}|prompt-{VERSION_PROMPT}|{conjunto}"
    inicio = time.perf_counter()
    with mlflow.start_run(run_name=nombre) as run:
        mlflow.log_params({
            "modelo": modelo, "estrategia": estrategia, "version_prompt": VERSION_PROMPT, "conjunto": conjunto,
            "n_casos": len(casos), "workers": workers, "rps": rps,
        })  # fmt: skip
        resultado = mlflow.genai.evaluate(
            data=a_registros(casos), predict_fn=predecir, scorers=crear_scorers(catalogo)
        )
        df = resultado.result_df
        latencias, costos = _valores(df, "latencia_s"), _valores(df, "costo_usd")
        errores = sum(
            1 for o in df.get("response", df.get("outputs", [])) if isinstance(o, dict) and "error" in o
        )
        resumen = {
            "modelo": modelo,
            "estrategia": estrategia,
            "version_prompt": VERSION_PROMPT,
            "conjunto": conjunto,
            "n_casos": len(casos),
            "errores": errores,
            **{k: round(sum(v) / len(v), 4) for k in CRITERIOS if (v := _valores(df, k))},
            "latencia_p50_s": round(_percentil(latencias, 0.5), 3),
            "latencia_p95_s": round(_percentil(latencias, 0.95), 3),
            "costo_total_usd": round(sum(costos), 5),
            "costo_por_1000_pedidos_usd": round(1000 * sum(costos) / max(len(costos), 1), 3),
            "duracion_total_s": round(time.perf_counter() - inicio, 1),
            "run_id": run.info.run_id,
        }
        mlflow.log_metrics({
            k: v for k, v in resumen.items() if isinstance(v, int | float) and k not in ("n_casos",)
        })  # fmt: skip
        # Tabla por caso (para analizar fallas) como artefacto del run
        filas = filas_por_caso(df, casos)
        # Sin respuesta (p. ej. un 429 deja la traza sin salida) o con error explícito: fallas de infraestructura
        resumen["errores"] = sum(
            1 for f in filas if not isinstance(f["obtenido"], dict) or "error" in f["obtenido"]
        )
        mlflow.log_metric("errores", resumen["errores"])
        mlflow.log_dict({"casos": filas}, "resultados_por_caso.json")
        if salida:
            salida.mkdir(parents=True, exist_ok=True)
            archivo = salida / f"{nombre.replace('|', '__').replace('/', '_')}.json"
            archivo.write_text(json.dumps({"resumen": resumen, "casos": filas}, ensure_ascii=False, indent=1, default=str),
                               encoding="utf-8")  # fmt: skip
    return resumen


def main() -> None:
    p = argparse.ArgumentParser(description="Evalúa una configuración del intérprete en MLflow")
    p.add_argument("--modelo", default=None)
    p.add_argument("--estrategia", default="hibrida", choices=["hibrida", "determinista", "llm"])
    p.add_argument("--conjunto", default="todos", choices=["dev", "propios", "todos"])
    p.add_argument("--limite", type=int, default=None)
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--rps", default="auto", help="solicitudes por segundo al modelo (p. ej. 0.3) o 'auto'")
    p.add_argument("--nombre", default=None)
    p.add_argument("--salida", type=Path, default=None, help="carpeta donde guardar el detalle en JSON")
    a = p.parse_args()
    resumen = evaluar(a.modelo or get_settings().modelo_llm, a.estrategia, a.conjunto, a.limite, a.workers, a.rps,
                      a.nombre, salida=a.salida)  # fmt: skip
    print(json.dumps(resumen, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
