"""Prueba de punta a punta POR HTTP contra el servicio levantado (simula el programa del docente).

    docker compose up -d
    uv run python evaluacion/probar_http.py --interrumpir-mlflow

1. Envía los casos (publicados + propios) a POST /v1/pedidos/interpretar y compara con lo esperado.
2. Envía solicitudes inválidas y verifica 422/404.
3. Opcional: a mitad de la corrida detiene MLflow (docker compose stop mlflow), comprueba que la API sigue
   respondiendo y que /health dice "degradado", y lo vuelve a levantar.
Guarda el resumen en evidencia/docker/prueba_http.json.
"""

from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import httpx

from novapedidos.config import get_settings
from novapedidos.evaluacion import comparacion as c
from novapedidos.evaluacion.casos import RAIZ, cargar

INVALIDAS = [
    ({"fecha_hora": "2026-11-23T10:00", "mensajes": ["hola"]}, 422, "falta cliente_id"),
    ({"cliente_id": "C001", "mensajes": ["hola"]}, 422, "falta fecha_hora"),
    ({"cliente_id": "C001", "fecha_hora": "2026-11-23T10:00"}, 422, "faltan mensajes"),
    ({"cliente_id": "C001", "fecha_hora": "2026-11-23T10:00", "mensajes": []}, 422, "lista vacía"),
    (
        {"cliente_id": "C001", "fecha_hora": "23/11/2026 10:00", "mensajes": ["hola"]},
        422,
        "fecha mal formada",
    ),
    ({"cliente_id": "C001", "fecha_hora": "2026-13-45T10:00", "mensajes": ["hola"]}, 422, "fecha imposible"),
    (
        {"cliente_id": "C001", "fecha_hora": "2026-11-23T10:00", "mensajes": "hola"},
        422,
        "mensajes no es lista",
    ),
    (
        {"cliente_id": "C999", "fecha_hora": "2026-11-23T10:00", "mensajes": ["hola"]},
        404,
        "cliente inexistente",
    ),
]


PROYECTO: list[str] = []  # ["-p", "nombre"] si el stack se levantó con otro nombre de proyecto


def _compose(*args: str) -> None:
    subprocess.run(["docker", "compose", *PROYECTO, *args], cwd=RAIZ, check=False, capture_output=True)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--url", default="http://127.0.0.1:8000")
    p.add_argument("--conjunto", default="todos", choices=["dev", "propios", "todos"])
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--interrumpir-mlflow", action="store_true")
    p.add_argument("--proyecto", default=None, help="nombre del proyecto de docker compose (-p)")
    a = p.parse_args()
    if a.proyecto:
        PROYECTO.extend(["-p", a.proyecto])
    cliente = httpx.Client(base_url=a.url, timeout=60)
    casos = cargar(a.conjunto, get_settings().data_dir)
    eventos: list[str] = []

    def interrumpir() -> None:  # a los ~10 s detiene MLflow 30 s, y lo vuelve a levantar
        time.sleep(10)
        _compose("stop", "mlflow")
        time.sleep(3)
        salud = cliente.get("/health").json()
        eventos.append(f"MLflow detenido -> /health: {salud['estado']} ({salud.get('motivo')})")
        time.sleep(27)
        _compose("start", "mlflow")
        eventos.append("MLflow levantado de nuevo")

    hilo_interrupcion = threading.Thread(target=interrumpir, daemon=True)
    if a.interrumpir_mlflow:
        hilo_interrupcion.start()

    def enviar(caso: dict) -> dict:
        inicio = time.perf_counter()
        try:
            r = cliente.post("/v1/pedidos/interpretar", json=caso["entrada"])
            cuerpo = r.json()
        except Exception as e:  # el servicio no respondió
            return {"id": caso["id"], "http": None, "exacto": False, "contrato": [str(e)], "s": 0}
        return {
            "id": caso["id"],
            "http": r.status_code,
            "exacto": r.status_code == 200 and c.pedido_exacto(cuerpo, caso["esperado"]),
            "contrato": c.problemas_de_contrato(cuerpo)
            if r.status_code == 200
            else [f"HTTP {r.status_code}"],
            "s": time.perf_counter() - inicio,
        }

    inicio = time.perf_counter()
    with ThreadPoolExecutor(a.workers) as pool:
        resultados = list(pool.map(enviar, casos))
    duracion = time.perf_counter() - inicio

    invalidas = []
    for cuerpo, esperado, nombre in INVALIDAS:
        r = cliente.post("/v1/pedidos/interpretar", json=cuerpo)
        detalle = str(r.json().get("detail"))[:120]
        invalidas.append(
            {
                "caso": nombre,
                "esperado": esperado,
                "obtenido": r.status_code,
                "ok": r.status_code == esperado,
                "detail": detalle,
            }
        )

    if a.interrumpir_mlflow:  # espera a que MLflow vuelva y a que /health lo refleje
        hilo_interrupcion.join()
        for _ in range(30):
            if cliente.get("/health").json()["estado"] == "ok":
                eventos.append("/health de vuelta en ok")
                break
            time.sleep(2)

    lat = sorted(x["s"] for x in resultados if x["http"] == 200)
    resumen = {
        "casos": len(resultados),
        "http_200": sum(x["http"] == 200 for x in resultados),
        "pedidos_exactos": sum(x["exacto"] for x in resultados),
        "fallas": [x["id"] for x in resultados if not x["exacto"]],
        "violaciones_de_contrato": {x["id"]: x["contrato"] for x in resultados if x["contrato"]},
        "latencia_p50_s": round(statistics.median(lat), 2) if lat else None,
        "latencia_p95_s": round(lat[int(0.95 * (len(lat) - 1))], 2) if lat else None,
        "latencia_max_s": round(max(lat), 2) if lat else None,
        "duracion_total_s": round(duracion, 1),
        "invalidas_ok": f"{sum(i['ok'] for i in invalidas)}/{len(invalidas)}",
        "invalidas": invalidas,
        "eventos_mlflow": eventos,
        "health_final": cliente.get("/health").json(),
    }
    destino = RAIZ / "evidencia" / "docker"
    destino.mkdir(parents=True, exist_ok=True)
    (destino / "prueba_http.json").write_text(
        json.dumps(resumen, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print(json.dumps({k: v for k, v in resumen.items() if k != "invalidas"}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
