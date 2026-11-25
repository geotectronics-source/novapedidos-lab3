"""Los scorers deben detectar errores (no solo aprobar lo correcto)."""

import copy

import pytest

from novapedidos.evaluacion import comparacion as c
from novapedidos.evaluacion.casos import CASOS_PROPIOS, a_registros, cargar, leer_jsonl

ESPERADO = {
    "estado": "requiere_revision",
    "lineas": [
        {"sku": "B01", "cantidad": 2, "precio_unitario": 120.0, "descuento_pct": 0, "subtotal": 240.0},
        {"sku": "B11", "cantidad": 4, "precio_unitario": 150.0, "descuento_pct": 0, "subtotal": 600.0},
    ],
    "total": 840.0,
    "fecha_entrega": "2026-11-26",
    "sustituciones": [],
    "pendientes": [{"motivo": "producto_ambiguo", "texto": "una caja de aceite", "opciones": ["A06", "A07"]}],
    "motivos_revision": ["producto_ambiguo"],
}
OBTENIDO = {**copy.deepcopy(ESPERADO), "cliente_id": "C001", "mensaje_cliente": "… un asesor le confirmará …"}
OBTENIDO["pendientes"][0]["texto"] = "aceite"  # el texto libre no cuenta
OBTENIDO["lineas"].reverse()  # el orden no cuenta


def _con(**cambios):
    o = copy.deepcopy(OBTENIDO)
    o.update(cambios)
    return o


def test_respuesta_correcta_aprueba_todo():
    assert c.pedido_exacto(OBTENIDO, ESPERADO)
    assert c.lineas_f1(OBTENIDO, ESPERADO) == 1.0
    assert c.problemas_de_contrato(OBTENIDO) == []


@pytest.mark.parametrize(
    ("cambio", "criterio"),
    [
        ({"estado": "confirmado"}, c.estado_correcto),
        ({"fecha_entrega": "2026-11-30"}, c.fecha_correcta),
        ({"total": 841.0}, c.total_correcto),
        ({"motivos_revision": []}, c.motivos_correctos),
        (
            {"pendientes": [{"motivo": "producto_ambiguo", "texto": "x", "opciones": ["A06"]}]},
            c.pendientes_correctos,
        ),
        (
            {"sustituciones": [{"sku_solicitado": "A07", "sku_entregado": "A06", "cantidad": 1}]},
            c.sustituciones_correctas,
        ),
    ],
)
def test_cada_criterio_detecta_su_error(cambio, criterio):
    o = _con(**cambio)
    assert not criterio(o, ESPERADO)
    assert not c.pedido_exacto(o, ESPERADO)


def test_cantidad_y_precio_equivocados():
    o = copy.deepcopy(OBTENIDO)
    o["lineas"][0]["cantidad"] = 3
    assert not c.lineas_correctas(o, ESPERADO)
    assert 0 < c.lineas_f1(o, ESPERADO) < 1  # crédito parcial: una de dos líneas
    o = copy.deepcopy(OBTENIDO)
    o["lineas"][0]["precio_unitario"] = 1.0  # p. ej. una inyección que cambió el precio
    assert c.lineas_correctas(o, ESPERADO) and not c.montos_correctos(o, ESPERADO)


def test_error_de_prediccion_falla_todo():
    o = {"error": "ErrorExtraccion: 429"}
    assert not c.pedido_exacto(o, ESPERADO) and c.lineas_f1(o, ESPERADO) == 0.0
    assert c.problemas_de_contrato(o)


@pytest.mark.parametrize(
    ("cambio", "fragmento"),
    [
        ({"estado": "confirmado"}, "confirmado"),
        ({"motivos_revision": ["producto_ambiguo", "credito_excedido", "otro"]}, "motivos inválidos"),
        ({"total": 1.0}, "suma de subtotales"),
        ({"mensaje_cliente": None, "extra": 1}, "claves"),
    ],
)
def test_contrato_detecta_incoherencias(cambio, fragmento):
    problemas = c.problemas_de_contrato(_con(**cambio))
    assert any(fragmento in p for p in problemas), problemas


def test_mensaje_coherente():
    nombres = {"B01": "Kola Norte 600 ml", "B11": "Energía Max 473 ml"}
    o = _con(mensaje_cliente="2 fardos de Kola Norte 600 ml y 4 de Energía Max 473 ml. Un asesor confirmará.")
    assert c.mensaje_coherente(o, nombres)
    assert not c.mensaje_coherente(_con(mensaje_cliente="Kola Norte 600 ml. Un asesor confirmará."), nombres)
    assert not c.mensaje_coherente(_con(mensaje_cliente="Kola Norte 600 ml y Energía Max 473 ml."), nombres)


def test_registros_para_mlflow(catalogo_real):
    from conftest import DATA_DIR

    casos = cargar("dev", DATA_DIR)
    r = a_registros(casos[:1])[0]
    assert set(r["inputs"]) == {"cliente_id", "fecha_hora", "mensajes"}
    assert r["expectations"]["esperado"]["estado"] and r["expectations"]["caso_id"] == casos[0]["id"]


def test_casos_propios_bien_formados(catalogo_real):
    if not CASOS_PROPIOS.exists():
        pytest.skip("aún no hay casos propios")
    casos = leer_jsonl(CASOS_PROPIOS)
    assert len({x["id"] for x in casos}) == len(casos)
    for caso in casos:
        assert set(caso) >= {"id", "tipo", "entrada", "esperado"}
        assert caso["entrada"]["cliente_id"] in catalogo_real.clientes
        assert (
            c.problemas_de_contrato({**caso["esperado"], "cliente_id": "x", "mensaje_cliente": "x"}) == []
        ), caso["id"]
