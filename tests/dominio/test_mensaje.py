"""El mensaje al cliente es coherente con el pedido calculado (politicas.md §9)."""

from datetime import date, datetime

from novapedidos.dominio import Accion, Motivo, Operacion, Pendiente, Unidad, construir_pedido
from novapedidos.dominio.mensaje import fecha_en_palabras, redactar_mensaje, saludo


def op(sku, cantidad=None, accion=Accion.AGREGAR):
    return Operacion(sku=sku, texto=sku, cantidad=cantidad, accion=accion, unidad=Unidad.VENTA)


def pedido(catalogo, ops, cliente="C001", recibido=datetime(2026, 11, 23, 15, 20), **kw):
    p = construir_pedido(catalogo, cliente, recibido, es_pedido=True, operaciones=ops, **kw)
    return p, redactar_mensaje(p, catalogo, recibido)


def test_confirmado_menciona_productos_total_y_fecha(catalogo_real):
    p, texto = pedido(catalogo_real, [op("B01", 2), op("B11", 1)])
    assert "2 fardos de Kola Norte 600 ml" in texto and "1 fardo de Energía Max 473 ml" in texto
    assert f"Q{p.total:,.2f}" in texto
    assert "jueves 26 de noviembre" in texto
    assert "asesor" not in texto


def test_requiere_revision_dice_que_un_asesor_confirmara(catalogo_real):
    amb = Pendiente(motivo=Motivo.PRODUCTO_AMBIGUO, texto="aceite", opciones=["A06", "A07"])
    _, texto = pedido(catalogo_real, [op("B01", 2)], pendientes_resolucion=[amb])
    assert "asesor" in texto and "aceite" in texto


def test_no_promete_agotados_e_informa_sustitucion(catalogo_real):
    _, texto = pedido(catalogo_real, [op("B03", 2), op("S02", 1)])  # B03 -> B02 ; S02 agotado sin sustituto
    assert "Kola Norte 3 L está agotado, así que le enviamos Kola Norte 1.5 L" in texto
    assert "Recibimos su pedido: 2 fardos de Kola Norte 1.5 L." in texto
    assert "Galletas Dulcitas Chocolate está agotado" in texto
    assert "displays de Galletas Dulcitas Chocolate" not in texto  # no se lista como recibido


def test_credito_excedido(catalogo_real):
    _, texto = pedido(catalogo_real, [op("P01", 4)], cliente="C034", recibido=datetime(2026, 11, 25, 8, 49))
    assert "crédito" in texto


def test_fuera_de_alcance():
    from novapedidos.dominio.modelos import Estado, PedidoCalculado

    texto = redactar_mensaje(
        PedidoCalculado(cliente_id="C1", estado=Estado.FUERA_DE_ALCANCE), None, datetime(2026, 1, 1, 9)
    )
    assert texto.startswith("¡Buenos días!") and "asesor" in texto


def test_saludo_y_fecha():
    assert saludo(datetime(2026, 1, 1, 11, 59)) == "¡Buenos días!"
    assert saludo(datetime(2026, 1, 1, 12, 0)) == "¡Buenas tardes!"
    assert saludo(datetime(2026, 1, 1, 19, 0)) == "¡Buenas noches!"
    assert fecha_en_palabras(date(2026, 12, 5)) == "sábado 5 de diciembre"
