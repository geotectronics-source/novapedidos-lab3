"""Pruebas unitarias de cada regla de politicas.md (funciones puras)."""

from dataclasses import replace
from datetime import date, datetime
from decimal import ROUND_HALF_EVEN, Decimal

import pytest

from novapedidos.dominio import reglas
from novapedidos.dominio.catalogo import Escalon
from novapedidos.dominio.modelos import Estado, Motivo, Pendiente, Unidad

LUNES, JUEVES, SABADO = 0, 3, 5


# ------------------------------------------------------------------ §2 conversión de cantidades
@pytest.mark.parametrize(
    ("cantidad", "unidad", "upe", "esperado"),
    [
        (None, Unidad.VENTA, 24, 1),  # "y unas manías" -> 1 unidad de venta
        (3, Unidad.VENTA, 24, 3),  # "3 de kola 600"
        (48, Unidad.SUELTA, 24, 2),  # "48 botellas" de un fardo de 24
        (72, Unidad.SUELTA, 24, 3),
        (36, Unidad.SUELTA, 24, None),  # 1.5 fardos: no se redondea
        (6, Unidad.SUELTA, 24, None),  # menos de un empaque
        (1, Unidad.DOCENA, 12, 1),  # "una docena de cloro" (caja de 12)
        (2, Unidad.DOCENA, 24, 1),
        (1, Unidad.DOCENA, 24, None),
        (5, Unidad.SUELTA, 1, 5),  # producto vendido por unidad (quintal)
        (None, Unidad.DOCENA, 12, 1),  # "una docena de cloro" sin número = 1 docena
        (None, Unidad.DOCENA, 24, None),  # "una docena de jugos" (caja de 24) no es exacta
    ],
)
def test_convertir_a_unidades_venta(catalogo_mini, cantidad, unidad, upe, esperado):
    producto = replace(catalogo_mini.productos["K1"], unidades_por_empaque=upe)
    assert reglas.convertir_a_unidades_venta(cantidad, unidad, producto) == esperado


def test_convertir_rechaza_cantidades_no_positivas(catalogo_mini):
    with pytest.raises(ValueError):
        reglas.convertir_a_unidades_venta(0, Unidad.VENTA, catalogo_mini.productos["K1"])


# ------------------------------------------------------------------ §5 precios y descuentos
BEBIDAS = (Escalon(10, 3), Escalon(20, 5))


@pytest.mark.parametrize(("cantidad", "pct"), [(1, 0), (9, 0), (10, 3), (19, 3), (20, 5), (500, 5)])
def test_descuento_mayor_escalon_alcanzado(cantidad, pct):
    assert reglas.descuento_pct(cantidad, BEBIDAS) == pct


def test_descuento_sin_escalones_es_cero():
    assert reglas.descuento_pct(100, ()) == 0


def test_redondeo_mitad_hacia_arriba():
    assert reglas.redondear(Decimal("2.345")) == Decimal("2.35")
    assert reglas.redondear(Decimal("2.675")) == Decimal("2.68")
    # Problema 1: el redondeo "del banquero" (mitad al par) daría 2.34.
    assert Decimal("2.345").quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN) == Decimal("2.34")
    # Problema 2: float no representa 2.675 exacto (es 2.67499999...), así que round() da 2.67.
    assert round(2.675, 2) == 2.67


@pytest.mark.parametrize(
    ("cantidad", "precio", "pct", "esperado"),
    [
        (2, "120", 0, "240.00"),
        (24, "120", 5, "2736.00"),
        (1, "10.05", 3, "9.75"),  # 9.7485 -> 9.75
        (6, "35.99", 3, "209.46"),  # 209.4618 -> 209.46
    ],
)
def test_subtotal(cantidad, precio, pct, esperado):
    assert reglas.subtotal(cantidad, Decimal(precio), pct) == Decimal(esperado)


# ------------------------------------------------------------------ §6 crédito
@pytest.mark.parametrize(
    ("saldo", "total", "limite", "excede"),
    [(7700, 672, 8000, True), (7000, 1000, 8000, False), (7000, "1000.01", 8000, True)],
)
def test_credito_excedido_es_estricto(saldo, total, limite, excede):
    assert reglas.credito_excedido(Decimal(saldo), Decimal(str(total)), Decimal(limite)) is excede


# ------------------------------------------------------------------ §7 fecha de entrega
@pytest.mark.parametrize(
    ("recibido", "dias", "esperado"),
    [
        (
            "2026-11-23T09:12",
            (LUNES, JUEVES),
            "2026-11-26",
        ),  # lunes antes del corte -> jueves (no el mismo día)
        ("2026-11-23T13:59", (LUNES, JUEVES), "2026-11-26"),
        ("2026-11-23T14:00", (LUNES, JUEVES), "2026-11-26"),  # 14:00 exacto ya es "día siguiente"
        ("2026-11-23T15:20", (LUNES, JUEVES), "2026-11-26"),  # ejemplo del Anexo
        ("2026-11-25T13:00", (LUNES, JUEVES), "2026-11-26"),  # miércoles -> jueves
        ("2026-11-25T14:00", (LUNES, JUEVES), "2026-11-30"),  # miércoles tarde = jueves -> lunes
        ("2026-11-28T14:53", (SABADO,), "2026-12-05"),  # D001: sábado tarde -> sábado siguiente
        ("2026-11-28T10:00", (SABADO,), "2026-12-05"),  # sábado temprano -> sábado siguiente
        ("2026-11-27T14:30", (SABADO,), "2026-12-05"),  # viernes tarde = sábado -> el otro sábado
        ("2026-11-27T13:30", (SABADO,), "2026-11-28"),  # viernes temprano -> mañana sábado
        ("2026-12-31T20:00", (LUNES,), "2027-01-04"),  # cambio de año
    ],
)
def test_fecha_entrega(recibido, dias, esperado):
    assert reglas.fecha_entrega(datetime.fromisoformat(recibido), dias) == date.fromisoformat(esperado)


def test_fecha_entrega_sin_dias_de_visita_falla():
    with pytest.raises(ValueError):
        reglas.fecha_entrega(datetime(2026, 11, 23, 9), ())


# ------------------------------------------------------------------ §8 estado y motivos
def _p(m: Motivo) -> Pendiente:
    return Pendiente(motivo=m, texto="x")


def test_motivos_unicos_en_orden_canonico():
    pendientes = [
        _p(Motivo.AGOTADO_SIN_SUSTITUTO),
        _p(Motivo.PRODUCTO_AMBIGUO),
        _p(Motivo.AGOTADO_SIN_SUSTITUTO),
    ]
    assert reglas.motivos_revision(pendientes, excede_credito=True) == [
        Motivo.PRODUCTO_AMBIGUO,
        Motivo.AGOTADO_SIN_SUSTITUTO,
        Motivo.CREDITO_EXCEDIDO,
    ]


@pytest.mark.parametrize(
    ("hay_lineas", "motivos", "estado"),
    [
        (True, [], Estado.CONFIRMADO),
        (True, [Motivo.CREDITO_EXCEDIDO], Estado.REQUIERE_REVISION),
        (False, [Motivo.PRODUCTO_NO_EXISTE], Estado.REQUIERE_REVISION),
        (False, [], Estado.FUERA_DE_ALCANCE),
    ],
)
def test_determinar_estado(hay_lineas, motivos, estado):
    assert reglas.determinar_estado(hay_lineas, motivos) is estado


def test_pendiente_no_admite_credito_excedido():
    with pytest.raises(ValueError):
        Pendiente(motivo=Motivo.CREDITO_EXCEDIDO, texto="x")
