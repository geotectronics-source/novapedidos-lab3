"""Pruebas de la API (contrato del Anexo) SIN llamar al modelo: el extractor es un doble de prueba."""

from collections.abc import Sequence

import pytest
from fastapi.testclient import TestClient

from novapedidos.api.app import crear_app
from novapedidos.config import Settings
from novapedidos.llm import ErrorExtraccion, Extraccion, ExtractorFijo, MencionExtraida
from novapedidos.observabilidad.salud import EstadoDependencia
from novapedidos.servicio import InterpreteDePedidos

CLAVES_RESPUESTA = {
    "cliente_id", "estado", "lineas", "total", "fecha_entrega", "sustituciones",
    "pendientes", "motivos_revision", "mensaje_cliente",
}  # fmt: skip
ANEXO = {
    "cliente_id": "C001",
    "fecha_hora": "2026-11-23T15:20",
    "mensajes": ["Buenas, mándeme 2 fardos de kola 600, una caja de aceite", "y 48 latas de energía max"],
}


def _m(texto, producto, skus, cantidad, unidad="venta"):
    return MencionExtraida(
        texto=texto, producto=producto, skus_posibles=skus, cantidad=cantidad, unidad=unidad
    )


def extraccion_por_mensaje(mensajes: Sequence[str]) -> Extraccion:
    texto = " ".join(mensajes).lower()
    if "kola" not in texto:
        return Extraccion(es_pedido=False)
    return Extraccion(
        es_pedido=True,
        menciones=[
            _m("2 fardos de kola 600", "kola 600", ["B01"], 2),
            _m("una caja de aceite", "aceite", ["A06", "A07"], 1),
            _m("48 latas de energía max", "energía max", ["B11"], 48, "suelta"),
        ],
    )


class ExtractorCaido:
    modelo = "caido"

    def extraer(self, mensajes):
        raise ErrorExtraccion("429 rate limit")


def _cliente(catalogo, extractor=None, mlflow_ok=True, settings=None):
    interprete = InterpreteDePedidos(catalogo, extractor or ExtractorFijo(extraccion_por_mensaje))
    estado = EstadoDependencia(mlflow_ok, "ok" if mlflow_ok else "MLflow no responde")
    app = crear_app(
        settings or Settings(_env_file=None), interprete=interprete, verificador_mlflow=lambda: estado
    )
    return TestClient(app)


@pytest.fixture
def api(catalogo_real):
    with _cliente(catalogo_real) as c:
        yield c


# ------------------------------------------------------------------ 200
def test_ejemplo_del_anexo(api):
    r = api.post("/v1/pedidos/interpretar", json=ANEXO)
    assert r.status_code == 200
    cuerpo = r.json()
    assert set(cuerpo) == CLAVES_RESPUESTA
    assert cuerpo["estado"] == "requiere_revision"
    assert cuerpo["lineas"] == [
        {"sku": "B01", "cantidad": 2, "precio_unitario": 120.0, "descuento_pct": 0, "subtotal": 240.0},
        {"sku": "B11", "cantidad": 4, "precio_unitario": 150.0, "descuento_pct": 0, "subtotal": 600.0},
    ]
    assert cuerpo["total"] == 840.0
    assert cuerpo["fecha_entrega"] == "2026-11-26"
    assert cuerpo["sustituciones"] == []
    assert cuerpo["pendientes"] == [
        {"motivo": "producto_ambiguo", "texto": "aceite", "opciones": ["A06", "A07"]}
    ]
    assert cuerpo["motivos_revision"] == ["producto_ambiguo"]
    assert isinstance(cuerpo["mensaje_cliente"], str) and cuerpo["mensaje_cliente"]


def test_respuestas_declaran_utf8(api):
    # Sin charset, PowerShell 5.1 muestra "Â¡Buenas tardes!" (detectado al probar el README).
    for r in (
        api.post("/v1/pedidos/interpretar", json=ANEXO),
        api.post("/v1/pedidos/interpretar", json={**ANEXO, "mensajes": []}),
        api.post("/v1/pedidos/interpretar", json={**ANEXO, "cliente_id": "C999"}),
        api.get("/health"),
    ):
        assert r.headers["content-type"] == "application/json; charset=utf-8", r.status_code


def test_fuera_de_alcance_cumple_el_contrato(api):
    r = api.post("/v1/pedidos/interpretar", json={**ANEXO, "mensajes": ["¿A qué hora pasa el camión?"]})
    cuerpo = r.json()
    assert r.status_code == 200
    assert (cuerpo["estado"], cuerpo["lineas"], cuerpo["total"], cuerpo["fecha_entrega"]) == (
        "fuera_de_alcance", [], 0.0, None,
    )  # fmt: skip


def test_cliente_en_minusculas_y_con_espacios(api):
    assert api.post("/v1/pedidos/interpretar", json={**ANEXO, "cliente_id": " c001 "}).status_code == 200


def test_campos_extra_se_ignoran(api):
    assert api.post("/v1/pedidos/interpretar", json={**ANEXO, "canal": "whatsapp"}).status_code == 200


# ------------------------------------------------------------------ 404
def test_cliente_inexistente_404(api):
    r = api.post("/v1/pedidos/interpretar", json={**ANEXO, "cliente_id": "C999"})
    assert r.status_code == 404 and "C999" in r.json()["detail"]


# ------------------------------------------------------------------ 422
@pytest.mark.parametrize(
    ("cambio", "campo"),
    [
        ({"cliente_id": None}, "cliente_id"),
        ({"cliente_id": ""}, "cliente_id"),
        ({"cliente_id": 123}, "cliente_id"),
        ({"mensajes": []}, "mensajes"),
        ({"mensajes": None}, "mensajes"),
        ({"mensajes": "hola"}, "mensajes"),
        ({"mensajes": [""]}, "mensajes"),
        ({"mensajes": ["   "]}, "mensajes"),
        ({"mensajes": [123]}, "mensajes.0"),
        ({"mensajes": ["x" * 2001]}, "mensajes"),
        ({"mensajes": ["hola"] * 21}, "mensajes"),
        ({"fecha_hora": "23/11/2026 15:20"}, "fecha_hora"),
        ({"fecha_hora": "2026-11-23 15:20"}, "fecha_hora"),
        ({"fecha_hora": "2026-11-23"}, "fecha_hora"),
        ({"fecha_hora": "2026-13-01T10:00"}, "fecha_hora"),
        ({"fecha_hora": "2026-02-30T10:00"}, "fecha_hora"),
        ({"fecha_hora": "2026-11-23T25:00"}, "fecha_hora"),
        ({"fecha_hora": "2026-11-23T15:20:00"}, "fecha_hora"),
        ({"fecha_hora": "2026-11-23T15:20Z"}, "fecha_hora"),
        ({"fecha_hora": ""}, "fecha_hora"),
        ({"fecha_hora": 20261123}, "fecha_hora"),
        ({"fecha_hora": None}, "fecha_hora"),
        ({"fecha_hora": "9999-12-31T23:59"}, "fecha_hora"),  # antes: 500 por desborde del calendario
        ({"fecha_hora": "0001-01-01T10:00"}, "fecha_hora"),
    ],
)
def test_solicitudes_invalidas_422(api, cambio, campo):
    cuerpo = {**ANEXO, **cambio}
    cuerpo = {k: v for k, v in cuerpo.items() if v is not None}  # None = campo faltante
    r = api.post("/v1/pedidos/interpretar", json=cuerpo)
    assert r.status_code == 422, r.text
    error = r.json()
    assert error["detail"].startswith("Solicitud inválida.")
    assert campo in {e["campo"] for e in error["errores"]}, error
    assert all(e["mensaje"] for e in error["errores"])


@pytest.mark.parametrize("cuerpo", ["no es json", "[1, 2]", "", "null"])
def test_cuerpo_que_no_es_un_objeto_json_422(api, cuerpo):
    r = api.post("/v1/pedidos/interpretar", content=cuerpo, headers={"content-type": "application/json"})
    assert r.status_code == 422 and r.json()["detail"]


def test_cuerpo_que_no_es_utf8_422(api):
    # curl en Windows puede enviar cp1252: FastAPI daría 400; el contrato pide 422 con explicación.
    import json

    cuerpo = json.dumps({**ANEXO, "mensajes": ["mándeme energía"]}, ensure_ascii=False).encode("cp1252")
    r = api.post("/v1/pedidos/interpretar", content=cuerpo, headers={"content-type": "application/json"})
    assert r.status_code == 422 and "UTF-8" in r.json()["detail"]


def test_ruta_inexistente_404_json(api):
    r = api.get("/no-existe")
    assert r.status_code == 404 and r.json()["detail"]


def test_solicitud_invalida_no_llama_al_modelo(catalogo_real):
    extractor = ExtractorFijo(extraccion_por_mensaje)
    with _cliente(catalogo_real, extractor) as c:
        c.post("/v1/pedidos/interpretar", json={**ANEXO, "mensajes": []})
        c.post("/v1/pedidos/interpretar", json={**ANEXO, "cliente_id": "C999"})
    assert extractor.llamadas == []


# ------------------------------------------------------------------ 503 y /health
def test_modelo_caido_503_y_health_degradado(catalogo_real):
    with _cliente(catalogo_real, ExtractorCaido()) as c:
        r = c.post("/v1/pedidos/interpretar", json=ANEXO)
        assert r.status_code == 503 and r.headers["retry-after"] == "5"
        salud = c.get("/health").json()
        assert salud["estado"] == "degradado" and salud["dependencias"]["llm"] == "error_reciente"


def test_health_ok(api):
    r = api.get("/health")
    assert r.status_code == 200
    assert r.json()["estado"] == "ok" and r.json()["motivo"] is None
    assert r.json()["dependencias"] == {"datos": "ok", "mlflow": "ok", "llm": "ok"}


def test_mlflow_caido_health_degradado_y_la_api_sigue_respondiendo(catalogo_real):
    with _cliente(catalogo_real, mlflow_ok=False) as c:
        salud = c.get("/health")
        assert salud.status_code == 200
        assert salud.json()["estado"] == "degradado" and "MLflow" in salud.json()["motivo"]
        assert c.post("/v1/pedidos/interpretar", json=ANEXO).status_code == 200


def test_sin_datos_el_servicio_vive_y_lo_reporta(tmp_path):
    settings = Settings(_env_file=None, data_dir=tmp_path, openrouter_api_key="x")
    app = crear_app(settings, verificador_mlflow=lambda: EstadoDependencia(True, "ok"))
    with TestClient(app) as c:
        salud = c.get("/health").json()
        assert salud["estado"] == "degradado" and salud["dependencias"]["datos"] == "error"
        assert c.post("/v1/pedidos/interpretar", json=ANEXO).status_code == 503


@pytest.mark.parametrize("uri", ["http://127.0.0.1:59999", "http://host:abc", "http://"])
def test_health_nunca_falla_por_la_uri_de_mlflow(catalogo_real, uri):
    from novapedidos.observabilidad.salud import VerificadorMlflow

    interprete = InterpreteDePedidos(catalogo_real, ExtractorFijo(extraccion_por_mensaje))
    app = crear_app(
        Settings(_env_file=None), interprete=interprete, verificador_mlflow=VerificadorMlflow(uri, 1)
    )
    with TestClient(app) as c:
        r = c.get("/health")
        assert r.status_code == 200 and r.json()["estado"] == "degradado"


def test_health_tiene_plazo_total_aunque_la_consulta_se_cuelgue(monkeypatch):
    # En docker, resolver el nombre de un MLflow detenido tardó ~7 s: el timeout de httpx no lo cubre.
    import time

    from novapedidos.observabilidad import salud

    def colgado(*args, **kwargs):
        time.sleep(10)

    monkeypatch.setattr(salud.httpx, "get", colgado)
    verificar = salud.VerificadorMlflow("http://mlflow:5000", timeout_s=1, cache_s=5)
    inicio = time.perf_counter()
    estado = verificar()
    assert not estado.disponible and time.perf_counter() - inicio < 2.0
    inicio = time.perf_counter()
    verificar()  # en caché: inmediato
    assert time.perf_counter() - inicio < 0.1


def test_documentacion_openapi_disponible(api):
    esquema = api.get("/openapi.json").json()
    assert "/v1/pedidos/interpretar" in esquema["paths"] and "/health" in esquema["paths"]
