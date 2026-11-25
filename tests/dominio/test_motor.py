"""Pruebas del motor completo con el catálogo sintético: combinaciones de reglas y bordes."""

from datetime import date, datetime

import pytest
from pydantic import ValidationError

from novapedidos.dominio import (
    Accion,
    ClienteNoEncontrado,
    Estado,
    Motivo,
    Operacion,
    Pendiente,
    Unidad,
    construir_pedido,
)

LUNES_MANANA = datetime(2026, 11, 23, 9, 0)


def op(sku, cantidad=None, unidad=Unidad.VENTA, accion=Accion.AGREGAR, texto=None):
    return Operacion(sku=sku, cantidad=cantidad, unidad=unidad, accion=accion, texto=texto or sku)


def pedir(catalogo, *ops, cliente="T1", recibido=LUNES_MANANA, **kw):
    return construir_pedido(catalogo, cliente, recibido, es_pedido=True, operaciones=list(ops), **kw)


def lineas(pedido):
    return {linea.sku: linea.cantidad for linea in pedido.lineas}


# ------------------------------------------------------------------ casos básicos
def test_pedido_simple_confirmado(catalogo_mini):
    p = pedir(catalogo_mini, op("K1", 2), op("C1", 1))
    assert p.estado is Estado.CONFIRMADO
    assert lineas(p) == {"K1": 2, "C1": 1}
    assert p.total == 240 + 108
    assert p.fecha_entrega == date(2026, 11, 26)
    assert p.pendientes == [] and p.motivos_revision == []


def test_no_es_pedido_fuera_de_alcance(catalogo_mini):
    p = construir_pedido(catalogo_mini, "T1", LUNES_MANANA, es_pedido=False, operaciones=[op("K1", 1)])
    assert p.estado is Estado.FUERA_DE_ALCANCE
    assert p.lineas == [] and p.total == 0 and p.fecha_entrega is None


def test_pedido_que_queda_vacio_es_fuera_de_alcance(catalogo_mini):
    p = pedir(catalogo_mini, op("K1", 2), op("K1", accion=Accion.QUITAR))
    assert p.estado is Estado.FUERA_DE_ALCANCE and p.fecha_entrega is None


def test_cliente_inexistente(catalogo_mini):
    with pytest.raises(ClienteNoEncontrado):
        pedir(catalogo_mini, op("K1", 1), cliente="NOEXISTE")


# ------------------------------------------------------------------ sumas, correcciones y exclusiones
def test_menciones_repetidas_se_suman(catalogo_mini):
    assert lineas(pedir(catalogo_mini, op("K1", 2), op("K1", 3))) == {"K1": 5}


def test_correccion_reemplaza(catalogo_mini):
    assert lineas(pedir(catalogo_mini, op("K1", 3), op("K1", 5, accion=Accion.CORREGIR))) == {"K1": 5}


def test_quitar_elimina_la_linea(catalogo_mini):
    assert lineas(pedir(catalogo_mini, op("K1", 3), op("C1", 1), op("K1", accion=Accion.QUITAR))) == {"C1": 1}


def test_sin_cantidad_es_una_unidad_de_venta(catalogo_mini):
    assert lineas(pedir(catalogo_mini, op("C1"))) == {"C1": 1}


# ------------------------------------------------------------------ cantidad_no_convertible
def test_unidades_sueltas_no_exactas_generan_pendiente(catalogo_mini):
    p = pedir(catalogo_mini, op("K1", 36, Unidad.SUELTA, texto="36 botellas de kola 600"))
    assert p.estado is Estado.REQUIERE_REVISION
    assert p.lineas == []
    assert p.pendientes == [
        Pendiente(motivo=Motivo.CANTIDAD_NO_CONVERTIBLE, texto="36 botellas de kola 600", opciones=["K1"])
    ]
    assert p.motivos_revision == [Motivo.CANTIDAD_NO_CONVERTIBLE]
    assert p.fecha_entrega == date(2026, 11, 26)  # requiere revisión, pero sigue siendo un pedido


def test_parte_convertible_se_conserva(catalogo_mini):
    p = pedir(catalogo_mini, op("K1", 2), op("K1", 30, Unidad.SUELTA))
    assert lineas(p) == {"K1": 2}
    assert p.motivos_revision == [Motivo.CANTIDAD_NO_CONVERTIBLE]


def test_correccion_valida_resuelve_la_no_convertible(catalogo_mini):
    p = pedir(catalogo_mini, op("K1", 30, Unidad.SUELTA), op("K1", 2, accion=Accion.CORREGIR))
    assert lineas(p) == {"K1": 2} and p.estado is Estado.CONFIRMADO


def test_correccion_no_convertible_elimina_la_linea(catalogo_mini):
    p = pedir(catalogo_mini, op("K1", 2), op("K1", 30, Unidad.SUELTA, accion=Accion.CORREGIR))
    assert p.lineas == [] and p.motivos_revision == [Motivo.CANTIDAD_NO_CONVERTIBLE]


def test_docena_exacta(catalogo_mini):
    assert lineas(pedir(catalogo_mini, op("C1", 1, Unidad.DOCENA))) == {"C1": 1}


# --- Regresiones encontradas en la revisión adversarial (sueltas repartidas en varias menciones)
def test_sueltas_en_varias_menciones_se_suman_antes_de_convertir(catalogo_mini):
    # "12 botellas de kola" + "otras 12" = 24 botellas = 1 fardo exacto
    p = pedir(catalogo_mini, op("K1", 12, Unidad.SUELTA), op("K1", 12, Unidad.SUELTA))
    assert lineas(p) == {"K1": 1} and p.estado is Estado.CONFIRMADO


def test_venta_mas_sueltas_que_completan_empaques(catalogo_mini):
    p = pedir(catalogo_mini, op("K1", 1), op("K1", 12, Unidad.SUELTA), op("K1", 12, Unidad.SUELTA))
    assert lineas(p) == {"K1": 2} and p.estado is Estado.CONFIRMADO


def test_sueltas_no_exactas_conservan_todos_los_textos(catalogo_mini):
    p = pedir(
        catalogo_mini,
        op("K1", 10, Unidad.SUELTA, texto="10 botellas"),
        op("K1", 4, Unidad.SUELTA, texto="otras 4"),
    )
    assert p.lineas == []
    assert p.pendientes == [
        Pendiente(motivo=Motivo.CANTIDAD_NO_CONVERTIBLE, texto="10 botellas; otras 4", opciones=["K1"])
    ]


def test_docena_sin_numero_se_convierte(catalogo_mini):
    assert lineas(pedir(catalogo_mini, op("C1", None, Unidad.DOCENA))) == {"C1": 1}
    p = pedir(catalogo_mini, op("K1", None, Unidad.DOCENA))  # 12 de un fardo de 24
    assert p.motivos_revision == [Motivo.CANTIDAD_NO_CONVERTIBLE]


def test_lo_de_siempre_mas_sueltas_del_mismo_producto(catalogo_mini):
    p = pedir(catalogo_mini, op("K1", 48, Unidad.SUELTA), pide_lo_de_siempre=True)
    assert lineas(p)["K1"] == 2 + 2  # 2 fardos del historial + 48 botellas


# ------------------------------------------------------------------ agotados y sustitutos
def test_agotado_con_sustituto(catalogo_mini):
    p = pedir(catalogo_mini, op("K3", 2))
    assert lineas(p) == {"K2": 2}
    assert [(s.sku_solicitado, s.sku_entregado, s.cantidad) for s in p.sustituciones] == [("K3", "K2", 2)]
    assert p.estado is Estado.CONFIRMADO  # la sustitución no requiere revisión


def test_sustituto_se_suma_a_linea_existente_y_el_descuento_usa_el_total(catalogo_mini):
    p = pedir(catalogo_mini, op("K2", 6), op("K3", 4))
    assert lineas(p) == {"K2": 10}
    assert p.lineas[0].descuento_pct == 3  # 10 fardos de bebidas -> 3 %
    assert p.lineas[0].subtotal == pytest.approx(10 * 144 * 0.97)


def test_agotado_sin_sustituto(catalogo_mini):
    p = pedir(catalogo_mini, op("K1", 1), op("X1", 2, texto="2 galletas"))
    assert lineas(p) == {"K1": 1}
    assert p.pendientes == [
        Pendiente(motivo=Motivo.AGOTADO_SIN_SUSTITUTO, texto="Galleta agotada", opciones=["X1"])
    ]
    assert p.estado is Estado.REQUIERE_REVISION


def test_sustituto_tambien_agotado_es_pendiente(catalogo_mini):
    p = pedir(catalogo_mini, op("X2", 1))
    assert p.lineas == [] and p.motivos_revision == [Motivo.AGOTADO_SIN_SUSTITUTO]


def test_quitar_un_agotado_no_genera_pendiente(catalogo_mini):
    p = pedir(catalogo_mini, op("K1", 1), op("X1", 1), op("X1", accion=Accion.QUITAR))
    assert p.estado is Estado.CONFIRMADO


# ------------------------------------------------------------------ "lo de siempre"
def test_lo_de_siempre_usa_ultimo_entregado_y_aplica_agotados(catalogo_mini):
    # T1: P2 (9-nov) es el último entregado antes del mensaje; P3 (cancelado) y P4 ("futuro") no cuentan.
    p = pedir(catalogo_mini, pide_lo_de_siempre=True)
    assert lineas(p) == {"K1": 2, "K2": 1}
    assert [s.sku_solicitado for s in p.sustituciones] == ["K3"]
    assert [x.opciones for x in p.pendientes] == [["X1"]]


def test_lo_de_siempre_con_agregado_y_exclusion(catalogo_mini):
    p = pedir(catalogo_mini, op("C1", 2), op("X1", accion=Accion.QUITAR), pide_lo_de_siempre=True)
    assert lineas(p) == {"K1": 2, "K2": 1, "C1": 2}
    assert p.estado is Estado.CONFIRMADO


def test_lo_de_siempre_sin_historial_entregado(catalogo_mini):
    p = pedir(catalogo_mini, cliente="T2", pide_lo_de_siempre=True)  # T2 solo tiene un cancelado
    assert p.estado is Estado.REQUIERE_REVISION and p.lineas == []
    assert p.motivos_revision == [Motivo.PRODUCTO_NO_EXISTE]


# ------------------------------------------------------------------ crédito
def test_credito_igual_al_limite_no_excede(catalogo_mini):
    # T2: límite 1000, saldo 760 -> 2 fardos K1 = 240 -> exactamente 1000
    p = pedir(catalogo_mini, op("K1", 2), cliente="T2")
    assert p.estado is Estado.CONFIRMADO


def test_credito_excedido_conserva_las_lineas(catalogo_mini):
    p = pedir(catalogo_mini, op("K1", 2), op("C1", 1), cliente="T2")
    assert p.estado is Estado.REQUIERE_REVISION
    assert p.motivos_revision == [Motivo.CREDITO_EXCEDIDO]
    assert p.pendientes == []  # credito_excedido nunca va en pendientes
    assert lineas(p) == {"K1": 2, "C1": 1}


# ------------------------------------------------------------------ robustez y seguridad
def test_pendientes_de_resolucion_se_conservan(catalogo_mini):
    amb = Pendiente(motivo=Motivo.PRODUCTO_AMBIGUO, texto="kola", opciones=["K1", "K2", "K3"])
    p = pedir(catalogo_mini, op("C1", 1), pendientes_resolucion=[amb])
    assert p.pendientes == [amb] and p.estado is Estado.REQUIERE_REVISION


def test_sku_desconocido_nunca_se_inventa(catalogo_mini):
    p = pedir(catalogo_mini, op("ZZ9", 1, texto="cerveza"))
    assert p.lineas == []
    assert p.pendientes[0].motivo is Motivo.PRODUCTO_NO_EXISTE


def test_operacion_no_acepta_campos_de_precio():
    with pytest.raises(ValidationError):
        Operacion(sku="K1", texto="x", cantidad=1, precio_unitario=1.0)
    with pytest.raises(ValidationError):
        Operacion(sku="K1", texto="x", cantidad=0)


def test_redondeo_en_subtotal_y_total(catalogo_mini):
    p = pedir(catalogo_mini, op("R1", 1))
    assert p.lineas[0].subtotal == 10.05 and p.total == 10.05


def test_es_determinista(catalogo_mini):
    ops = [op("K1", 2), op("K3", 1), op("X1", 1)]
    assert pedir(catalogo_mini, *ops) == pedir(catalogo_mini, *ops)
