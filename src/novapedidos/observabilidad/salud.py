"""Verificación de disponibilidad de MLflow para GET /health.

Se consulta el endpoint /health del servidor de MLflow y el resultado se guarda unos segundos en caché:
/health debe responder rápido aunque MLflow esté caído o lento.

Plazo TOTAL garantizado: el timeout de httpx no cubre la resolución DNS. En docker compose, al detener el
contenedor de MLflow desaparece el nombre "mlflow" y resolverlo tardó ~7 s (medido). Por eso la consulta
corre en un hilo y, si no termina dentro del plazo, se reporta "no disponible" sin esperarla.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass

import httpx


@dataclass(frozen=True)
class EstadoDependencia:
    disponible: bool
    detalle: str


class VerificadorMlflow:
    # cache_s: antes 5 s; durante ese lapso /health podía repetir un "ok" ya obsoleto (auditoría Codex).
    def __init__(self, tracking_uri: str, timeout_s: float = 2.0, cache_s: float = 2.0) -> None:
        self.tracking_uri = tracking_uri.rstrip("/")
        self.timeout_s = timeout_s
        self.cache_s = cache_s
        self._ultimo: tuple[float, EstadoDependencia] | None = None
        self._lock = threading.Lock()
        self._en_curso: threading.Thread | None = None  # a lo sumo una consulta a la vez
        self._resultado: EstadoDependencia | None = None

    def __call__(self) -> EstadoDependencia:
        with self._lock:
            if self._ultimo and time.monotonic() - self._ultimo[0] < self.cache_s:
                return self._ultimo[1]
            if self._en_curso is None or not self._en_curso.is_alive():
                self._resultado = None
                self._en_curso = threading.Thread(target=self._consultar_en_hilo, daemon=True)
                self._en_curso.start()
            hilo = self._en_curso
        hilo.join(self.timeout_s + 0.5)  # plazo total, DNS incluido
        estado = self._resultado or EstadoDependencia(
            False,
            f"MLflow no responde en {self.tracking_uri} (sin respuesta en {self.timeout_s + 0.5:.1f} s)",
        )
        with self._lock:
            self._ultimo = (time.monotonic(), estado)
        return estado

    def _consultar_en_hilo(self) -> None:
        self._resultado = self._consultar()

    def _consultar(self) -> EstadoDependencia:
        if not self.tracking_uri.lower().startswith(("http:", "https:")):
            return EstadoDependencia(True, f"almacenamiento local ({self.tracking_uri})")
        try:
            r = httpx.get(f"{self.tracking_uri}/health", timeout=self.timeout_s)
        except Exception as e:  # red, timeout o URI mal formada: /health nunca debe fallar por esto
            return EstadoDependencia(False, f"MLflow no responde en {self.tracking_uri} ({type(e).__name__})")
        if r.status_code != 200:
            return EstadoDependencia(False, f"MLflow respondió {r.status_code} en {self.tracking_uri}")
        return EstadoDependencia(True, "ok")
