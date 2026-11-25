"""Observabilidad: trazas en MLflow que nunca bloquean ni rompen la API.

Usa un MLflow local en SQLite (carpeta temporal), sin servidor ni modelo.
"""

import time
from datetime import datetime

import mlflow
import pytest

from novapedidos.llm import Extraccion, ExtractorFijo, MencionExtraida
from novapedidos.observabilidad import trazas
from novapedidos.observabilidad.trazas import Observabilidad, span
from novapedidos.servicio import InterpreteDePedidos

EXTRACCION = Extraccion(
    es_pedido=True,
    menciones=[
        MencionExtraida(texto="2 fardos de kola 600", producto="kola 600", skus_posibles=["B01"], cantidad=2)
    ],
)


def _esperar(condicion, segundos=20.0):
    limite = time.monotonic() + segundos
    while time.monotonic() < limite:
        if condicion():
            return True
        time.sleep(0.1)
    return False


@pytest.fixture(autouse=True)
def _limpiar():
    trazas.desactivar()
    yield
    trazas.desactivar()


def test_sin_observabilidad_span_no_hace_nada():
    assert not trazas.activo()
    with span("x", entradas={"a": 1}) as s:
        s.salidas({"b": 2})  # no falla ni escribe nada
        s.atributos(c=3)


def test_mlflow_caido_no_bloquea(catalogo_real):
    obs = Observabilidad("http://127.0.0.1:59999", "prueba")
    t = time.perf_counter()
    obs.iniciar()
    assert time.perf_counter() - t < 1.0  # iniciar no espera a MLflow (hilo de fondo)
    interprete = InterpreteDePedidos(catalogo_real, ExtractorFijo(EXTRACCION))
    t = time.perf_counter()
    r = interprete.interpretar("C001", datetime(2026, 11, 23, 9), ["..."]).respuesta
    assert r.estado == "confirmado" and time.perf_counter() - t < 1.0
    assert not trazas.activo()
    _esperar(lambda: obs.ultimo_error is not None, 10)
    assert obs.ultimo_error  # se registró por qué no hay trazas
    t = time.perf_counter()
    obs.detener()
    assert time.perf_counter() - t < 6.0


def test_traza_completa_en_mlflow_local(catalogo_real, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # MLflow crea ./mlruns para artefactos: que quede en la carpeta temporal
    uri = f"sqlite:///{(tmp_path / 'mlflow.db').as_posix()}"
    obs = Observabilidad(uri, "prueba-trazas")
    obs.iniciar()
    assert _esperar(trazas.activo, 60), obs.ultimo_error
    interprete = InterpreteDePedidos(catalogo_real, ExtractorFijo(EXTRACCION, modelo="modelo-falso"))
    interprete.interpretar("C001", datetime(2026, 11, 23, 9), ["2 fardos de kola 600"])
    traza_id = mlflow.get_last_active_trace_id()
    obs.detener(timeout_flush_s=30)

    traza = mlflow.get_trace(traza_id)
    assert traza is not None
    nombres = {s.name for s in traza.data.spans}
    assert {"interpretar_pedido", "extraccion", "resolucion", "motor_reglas"} <= nombres
    tags = traza.info.tags
    assert tags["estado"] == "confirmado" and tags["cliente_id"] == "C001"
    assert tags["modelo"] == "modelo-falso" and tags["version_prompt"].startswith("v")
    assert traza.info.trace_metadata["total_q"] == "240.0"


def test_un_error_de_mlflow_no_rompe_la_solicitud(catalogo_real, monkeypatch):
    monkeypatch.setattr(trazas, "_activo", True)

    def explota(*args, **kwargs):
        raise RuntimeError("MLflow se cayó a mitad de la solicitud")

    monkeypatch.setattr(mlflow, "start_span", explota)
    monkeypatch.setattr(mlflow, "update_current_trace", explota)
    interprete = InterpreteDePedidos(catalogo_real, ExtractorFijo(EXTRACCION))
    r = interprete.interpretar("C001", datetime(2026, 11, 23, 9), ["..."]).respuesta
    assert r.total == 240.0
