"""Casos reales de mensajes_dev.jsonl con la salida que deberían producir el LLM y la resolución.

Aquí codificamos a mano "lo que el mensaje significa" (operaciones + pendientes de resolución) y
comprobamos que el motor produce EXACTAMENTE la respuesta esperada publicada. Así, si en el
Inciso 8 un caso falla, sabremos que el problema está en la extracción o en la resolución, no en las reglas.
"""

from datetime import datetime

import pytest

from novapedidos.dominio import Accion, Motivo, Operacion, Pendiente, Unidad, construir_pedido

S, D, C, Q = Unidad.SUELTA, Unidad.DOCENA, Accion.CORREGIR, Accion.QUITAR


def op(sku, cantidad=None, unidad=Unidad.VENTA, accion=Accion.AGREGAR):
    return Operacion(sku=sku, cantidad=cantidad, unidad=unidad, accion=accion, texto=sku)


def amb(texto, *opciones):
    return Pendiente(motivo=Motivo.PRODUCTO_AMBIGUO, texto=texto, opciones=list(opciones))


def noex(texto):
    return Pendiente(motivo=Motivo.PRODUCTO_NO_EXISTE, texto=texto)


# id -> (es_pedido, lo_de_siempre, operaciones, pendientes de resolución)
INTERPRETACIONES = {
    "D001": (True, False, [op("B07", 72, S), op("B09", 3), op("P02", 5)], []),  # sueltas + hora de corte
    "D002": (False, False, [], []),  # agradecimiento
    "D003": (True, False, [op("A01", 3)], [amb("naranjitas", "B04", "B05")]),
    "D005": (True, False, [op("A14", 10)], [amb("papel higiénico", "L04", "L05")]),  # descuento 4 %
    "D010": (True, False, [op("P01", 4)], []),  # crédito
    "D012": (True, True, [op("L04", 2)], []),  # habitual con sustitución
    "D015": (True, False, [op("B12", 6), op("S04")], []),  # sin cantidad
    "D017": (True, True, [], []),  # habitual: sustitución + agotado sin sustituto
    "D020": (True, False, [op("A04", 4), op("A05", 2), op("A05", 5, accion=C)], []),
    "D024": (True, False, [op("A12", 36, S)], []),  # 36 bolsas / caja de 12
    "D025": (True, True, [op("A11", accion=Q)], []),  # habitual quitando un producto
    "D027": (True, False, [op("A06", 2), op("S02", 24)], []),  # agotado sin sustituto
    "D031": (True, True, [op("S03", 5)], []),  # habitual con dos agotados
    "D032": (True, False, [op("B01", 24), op("P03", 10), op("L05", 6)], []),  # 5 % + sustituto + crédito
    "D036": (True, False, [op("S06", 1), op("A14", 1)], [noex("cerveza")]),
    "D038": (False, False, [], []),
    "D040": (True, True, [op("L06", 2), op("P04", accion=Q)], []),  # quitar un agotado: sin pendiente
    "D043": (True, True, [op("B11", 1)], []),  # varios mensajes
    "D044": (True, True, [op("B01", 1)], []),
    "D047": (True, True, [op("A08", 1), op("L06", 2)], []),  # sustituto que se suma a línea existente
    "D054": (True, False, [op("B08", 20), op("S05", 1), op("S05", 4, accion=C)], []),
    "D062": (True, False, [op("L02", 15), op("A14", 3), op("A06", 2), op("L02", 16, accion=C)], []),
    "D064": (True, False, [op("B08", 4)], [amb("cocas", "B01", "B02", "B03")]),
    "D073": (True, False, [op("B07", 2), op("P01", 6), op("B04", 3), op("P01", 9, accion=C)], []),
    "D074": (True, False, [op("A11", 5), op("L01", 48, S), op("L02", 4)], []),
    "D077": (
        True,
        False,
        [op("B12", 4), op("A11", 4), op("S01", 5), op("B02", 1), op("A11", 6, accion=C)],
        [],
    ),
    "D080": (True, True, [op("A06", 1)], []),
    "D081": (True, False, [op("A01", 5), op("A01", 6, accion=C), op("A03", 2)], []),
    "D084": (True, False, [op("L03", 1, D), op("A09", 2)], []),
}


def _normalizar(d: dict) -> dict:
    """Compara sin depender del orden de líneas, sustituciones y pendientes."""
    d = dict(d)
    d["lineas"] = sorted(d["lineas"], key=lambda x: x["sku"])
    d["sustituciones"] = sorted(d["sustituciones"], key=lambda x: x["sku_solicitado"])
    d["pendientes"] = sorted(d["pendientes"], key=lambda x: (x["motivo"], x["texto"]))
    d["motivos_revision"] = sorted(d["motivos_revision"])
    return d


@pytest.mark.parametrize("caso_id", sorted(INTERPRETACIONES))
def test_motor_reproduce_respuesta_esperada(caso_id, catalogo_real, casos_dev):
    caso = casos_dev[caso_id]
    es_pedido, siempre, ops, pend = INTERPRETACIONES[caso_id]
    entrada = caso["entrada"]
    pedido = construir_pedido(
        catalogo_real,
        entrada["cliente_id"],
        datetime.fromisoformat(entrada["fecha_hora"]),
        es_pedido=es_pedido,
        pide_lo_de_siempre=siempre,
        operaciones=ops,
        pendientes_resolucion=pend,
    )
    obtenido = pedido.model_dump(mode="json", exclude={"cliente_id"})
    assert _normalizar(obtenido) == _normalizar(caso["esperado"])


def test_ejemplo_del_anexo(catalogo_real):
    """El ejemplo del enunciado: C001, lunes 23-nov 15:20."""
    pedido = construir_pedido(
        catalogo_real,
        "C001",
        datetime(2026, 11, 23, 15, 20),
        es_pedido=True,
        operaciones=[op("B01", 2), op("B11", 48, S)],
        pendientes_resolucion=[amb("una caja de aceite", "A06", "A07")],
    )
    assert [(linea.sku, linea.cantidad, linea.subtotal) for linea in pedido.lineas] == [
        ("B01", 2, 240.0),
        ("B11", 4, 600.0),
    ]
    assert pedido.total == 840.0
    assert str(pedido.fecha_entrega) == "2026-11-26"
    assert pedido.motivos_revision == [Motivo.PRODUCTO_AMBIGUO]
    assert pedido.estado == "requiere_revision"


def test_catalogo_real_carga_y_valida(catalogo_real):
    assert len(catalogo_real.productos) == 44
    assert len(catalogo_real.clientes) == 40
    assert catalogo_real.cliente("C029").dias_visita == (5,)  # "sábado" con tilde
    assert catalogo_real.ultimo_pedido_entregado("C009").pedido_id == "PED-00051"  # ignora el cancelado
