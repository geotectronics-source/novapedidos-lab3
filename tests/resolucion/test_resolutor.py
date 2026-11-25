"""Pruebas del resolutor texto -> SKU con el catálogo real.

Tres grupos:
  - DEV: menciones tal como aparecen en mensajes_dev.jsonl (con sus errores de ortografía).
  - NO_VISTAS: nombres informales y productos que no vendemos, que NO están en los casos publicados.
  - Propiedades: nunca devuelve un SKU fuera del catálogo; las opciones de un ambiguo están ordenadas.
"""

import pytest

from novapedidos.dominio.modelos import Motivo
from novapedidos.resolucion import Resolutor, TipoResolucion
from novapedidos.resolucion.normalizacion import Medida, normalizar

U, A, N = TipoResolucion.UNICO, TipoResolucion.AMBIGUO, TipoResolucion.NO_EXISTE

DEV = [
    ("agua pura cristal 600 ml", U, ["B07"]),
    ("jugo huerto naranja", U, ["B09"]),
    ("shampoo birsa sobre 10 ml", U, ["P02"]),
    ("arroz ceiba de libra", U, ["A01"]),
    ("naranjitas", A, ["B04", "B05"]),
    ("papel higienico", A, ["L04", "L05"]),
    ("pasta", A, ["A09", "A10", "P03"]),
    ("espagueti bella", U, ["A10"]),
    ("pasta dental sonrisa 75 ml", U, ["P03"]),
    ("cocas", A, ["B01", "B02", "B03"]),
    ("aceite", A, ["A06", "A07"]),
    ("juguitos", A, ["B09", "B10"]),
    ("chicharritos picntes 30 g", U, ["S04"]),
    ("arroz la ceiba quintal", U, ["A02"]),
    ("azúúcar dulzura 5 lb", U, ["A05"]),
    ("deetrgente espumoso 500 g", U, ["L01"]),
    ("maní sallado la finca 50 g", U, ["S06"]),
    ("te qutzal", U, ["B12"]),
    ("té qutezal", U, ["B12"]),
    ("agua pura 1.5", U, ["B08"]),
    ("dulcitas chocolate", U, ["S02"]),  # agotado: el motor decide qué hacer
    ("cafe altura instantaneo 50 g", U, ["A13"]),
    ("aceite girasol dordo 750 ml", U, ["A06"]),
    ("papel suave 12", U, ["L05"]),
    ("papel higiénico suave 12 rollos", U, ["L05"]),
    ("cerveza", N, []),
    ("velas", N, []),
    ("recargas de Q50", N, []),
    ("gas propano", N, []),
    ("cilindros de gas propano", N, []),
    ("farditos de agua cristal 600", U, ["B07"]),
    ("cajitas de nutrimezcla", U, ["A14"]),
    ("kola de litro y medio", U, ["B02"]),
    ("friijol negro", U, ["A03"]),
    ("nranjita 600 ml", U, ["B04"]),
    ("narannjita 1.5", U, ["B05"]),
    ("laavaplatos brillo", U, ["L06"]),
    ("espagueti bellla", U, ["A10"]),
    ("arroz ceeiba de libra", U, ["A01"]),
    ("paapel suave 4", U, ["L04"]),
    ("galletas saladdas crac", U, ["S03"]),
    ("galletas ducitas vainilla", U, ["S01"]),
    ("jaabon de tocador rosa 100 g", U, ["P01"]),
    ("kola de 3", U, ["B03"]),
    ("frijol negro monte verde 1 lb", U, ["A03"]),
    ("cloro blancura 1 l", U, ["L03"]),
    ("jugo huerto manzana", U, ["B10"]),
    ("coditos bella", U, ["A09"]),
    ("papitas doradas 40 g", U, ["S05"]),
    ("energía max 473 ml", U, ["B11"]),
    ("limonada volcán 600 ml", U, ["B06"]),
    ("leche en polvo vaquita 360 g", U, ["A16"]),
    ("jabón de barra lavandero 350 g", U, ["L02"]),
    ("kola norte 1.5 l", U, ["B02"]),
    ("chicharritos", U, ["S04"]),
    ("sopa rapida", U, ["A15"]),
]

NO_VISTAS = [
    ("gaseosa", A, ["B01", "B02", "B03", "B04", "B05", "B06"]),
    ("fideos", A, ["A09", "A10"]),
    ("aceite de oliva", N, []),  # reconoce el tipo pero no la variante: no se vende
    ("jugo de uva", N, []),
    ("galletas de fresa", N, []),
    ("leche deslactosada", N, []),
    ("te de manzanilla", N, []),  # "manzanilla" se parece a "manzana" pero contradice a "te"
    ("kola 2 litros", N, []),  # presentación que no existe
    ("papalinas", U, ["S05"]),
    ("unas manías", U, ["S06"]),
    ("pasta de dientes", U, ["P03"]),
    ("crema dental", U, ["P03"]),
    ("papel de baño", A, ["L04", "L05"]),
    ("champú", U, ["P02"]),
    ("lejía", U, ["L03"]),
    ("coca cola 600", U, ["B01"]),
    ("coca de litro y medio", U, ["B02"]),
    ("arroz", A, ["A01", "A02"]),
    ("frijoles", A, ["A03", "A04"]),
    ("frijol colorado", U, ["A04"]),
    ("quintales de arroz", U, ["A02"]),
    ("jabón", A, ["L02", "P01"]),
    ("jabon para ropa", U, ["L02"]),
    ("café", A, ["A12", "A13"]),
    ("kola helada", A, ["B01", "B02", "B03"]),
    ("2 fardos de kola 600", U, ["B01"]),  # si la cantidad se cuela en el texto, se ignora
    ("tres litros de kola", U, ["B03"]),
    ("KOLA 1,5", U, ["B02"]),
    ("600ml de agua cristal", U, ["B07"]),
    ("huevos", N, []),
    ("pan", N, []),
    ("papalina picante", N, []),  # papitas que no son picantes: no existe
]


# Fallas reales encontradas por la revisión adversarial (537 menciones generadas por agentes).
ATAQUE = [
    # fuzzy demasiado permisivo: inventaba un SKU
    ("azuquita", U, ["A05"]),  # antes: A16 (leche "vaquita")
    ("cereal", N, []),  # antes: A07 (aceite palma "real")
    ("monster", N, []),  # antes: frijol "monte" verde
    ("ensalada", N, []),
    # variantes que no se venden aunque mencionen la marca
    ("kola norte light", N, []),
    ("jugo huerto de piña", N, []),
    ("galletas dulcitas de fresa", N, []),
    ("té quetzal durazno", N, []),
    ("té frío de durazno", N, []),
    ("sopa rápida de camarón", N, []),
    ("arroz la ceiba integral", N, []),
    ("leche vaquita deslactosada", N, []),
    ("café molido descafeinado", N, []),
    ("frijol negro volteado", N, []),
    ("agua pura con gas", N, []),
    ("agua pura de galón", N, []),
    ("agua pura garrafón", N, []),
    ("polvo para hornear", N, []),
    ("chicharritos sin picante", N, []),  # todos los chicharritos son picantes
    # diminutivos
    ("aceitito", A, ["A06", "A07"]),
    ("salita", U, ["A11"]),
    ("manicito", U, ["S06"]),
    ("champucito", U, ["P02"]),
    ("jaboncito de baño", U, ["P01"]),
    # números escritos, fracciones y unidades equivalentes
    ("kola seiscientos", U, ["B01"]),
    ("la agua de seiscientos", U, ["B07"]),
    ("papel higienico de doce", U, ["L05"]),
    ("te quetzal medio litro", U, ["B12"]),  # 0.5 l = 500 ml
    ("te 1/2 litro", U, ["B12"]),
    ("naranjita 1 1/2 litro", U, ["B05"]),
    ("cloro 1000 ml", U, ["L03"]),  # 1000 ml = 1 l
    ("KOLA 3 LTRS", U, ["B03"]),
    ("kola 600cc", U, ["B01"]),
    # fonética, palabras pegadas/separadas
    ("koka 600", U, ["B01"]),
    ("koka kola 🥤", A, ["B01", "B02", "B03"]),
    ("shampu", U, ["P02"]),
    ("galleta de vaniya", U, ["S01"]),
    ("leche en polbo", U, ["A16"]),
    ("kolanorte", A, ["B01", "B02", "B03"]),
    ("kola norte600", U, ["B01"]),
    ("naranjita600", U, ["B04"]),
    ("lava platos", U, ["L06"]),
    ("lavatrastos", U, ["L06"]),
    ("nutri-mezcla", U, ["A14"]),
    # frases y sinónimos
    ("jabón de lavar trastes", U, ["L06"]),  # antes: L02 (jabón para ropa)
    ("jabón para trastos", U, ["L06"]),
    ("jabón para la ropa", U, ["L02"]),
    ("pasta para los dientes", U, ["P03"]),
    ("crema de dientes", U, ["P03"]),
    ("pasta dentrifica", U, ["P03"]),
    ("aceite de cocina", A, ["A06", "A07"]),
    ("harina para tortillas", U, ["A08"]),
    ("bebida energizante", U, ["B11"]),
    ("pastillas de jabón", A, ["L02", "P01"]),
    ("sopas instantáneas", U, ["A15"]),
    ("galletas de soda", U, ["S03"]),
    ("detergente en polvo", U, ["L01"]),
    ("desodorante de bolita", U, ["P04"]),
    ("manías saladas", U, ["S06"]),  # género: "saladas" también es "salado"
    ("gaseosa de naranja", A, ["B04", "B05"]),
    ("refresco de limón", U, ["B06"]),
    ("limón", A, ["B06", "B12"]),
    ("naranja", A, ["B04", "B05", "B09"]),
]


@pytest.fixture(scope="module")
def resolutor(catalogo_real):
    return Resolutor(catalogo_real)


TODOS = DEV + NO_VISTAS + ATAQUE


@pytest.mark.parametrize(("texto", "tipo", "skus"), TODOS, ids=[t for t, *_ in TODOS])
def test_resolucion(resolutor, texto, tipo, skus):
    r = resolutor.resolver(texto)
    assert (r.tipo, list(r.skus)) == (tipo, skus), r.detalle


def test_nunca_inventa_skus(resolutor, catalogo_real):
    for texto, *_ in TODOS:
        assert set(resolutor.resolver(texto).skus) <= set(catalogo_real.productos)


def test_todos_los_nombres_y_alias_del_catalogo_se_resuelven_a_si_mismos(resolutor, catalogo_real):
    for p in catalogo_real.productos.values():
        assert resolutor.resolver(p.nombre).skus == (p.sku,), p.nombre
    for sku, aliases in catalogo_real.sinonimos.items():
        for alias in aliases:
            assert resolutor.resolver(alias).skus == (sku,), alias


def test_a_pendiente(resolutor):
    amb = resolutor.resolver("naranjitas").a_pendiente("naranjitas")
    assert (amb.motivo, amb.opciones) == (Motivo.PRODUCTO_AMBIGUO, ["B04", "B05"])
    nox = resolutor.resolver("cerveza").a_pendiente("cinco cajas de cerveza")
    assert (nox.motivo, nox.opciones, nox.texto) == (Motivo.PRODUCTO_NO_EXISTE, [], "cinco cajas de cerveza")
    with pytest.raises(ValueError):
        resolutor.resolver("kola 600").a_pendiente("kola 600")


# ------------------------------------------------------------------ normalización
@pytest.mark.parametrize(
    ("texto", "palabras", "medidas"),
    [
        ("Kola Norte 1,5 L", ("kola", "norte"), [("1.5", "l")]),
        ("kola de litro y medio", ("kola",), [("1.5", "l")]),
        ("600ml", (), [("600", "ml")]),
        ("2 fardos de kola 600", ("kola",), [("600", None)]),
        ("Galletas 🙏 Dulcitas!!", ("galletas", "dulcitas"), []),
        ("tres litros de kola", ("kola",), [("3", "l")]),
    ],
)
def test_normalizar(texto, palabras, medidas):
    n = normalizar(texto)
    assert n.palabras == palabras
    assert [(str(m.numero), m.unidad) for m in n.medidas] == medidas


def test_medida_sin_unidad_es_compatible():
    from decimal import Decimal

    assert Medida(Decimal(600), None).compatible_con(Medida(Decimal(600), "ml"))
    assert not Medida(Decimal(600), "g").compatible_con(Medida(Decimal(600), "ml"))
    assert Medida(Decimal("0.5"), "l").compatible_con(Medida(Decimal(500), "ml"))  # conversión
    assert Medida(Decimal(1), "kg").compatible_con(Medida(Decimal(1000), "g"))
