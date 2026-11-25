"""Verificación de disponibilidad de MLflow para GET /health.

Se consulta el endpoint /health del servidor de MLflow con un timeout corto y el resultado se guarda
unos segundos en caché: /health debe responder rápido aunque MLflow esté caído o lento.
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
    def __init__(self, tracking_uri: str, timeout_s: float = 2.0, cache_s: float = 5.0) -> None:
        self.tracking_uri = tracking_uri.rstrip("/")
        self.timeout_s = timeout_s
        self.cache_s = cache_s
        self._ultimo: tuple[float, EstadoDependencia] | None = None
        self._lock = threading.Lock()

    def __call__(self) -> EstadoDependencia:
        with self._lock:
            if self._ultimo and time.monotonic() - self._ultimo[0] < self.cache_s:
                return self._ultimo[1]
        estado = self._consultar()
        with self._lock:
            self._ultimo = (time.monotonic(), estado)
        return estado

    def invalidar(self) -> None:
        with self._lock:
            self._ultimo = None

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
