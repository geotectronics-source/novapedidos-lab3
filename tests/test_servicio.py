"""Pipeline completo con un extractor FALSO: prueba la integración sin llamar al modelo."""

from datetime import datetime

import pytest

from novapedidos.dominio import ClienteNoEncontrado, Estado, Motivo, Unidad
from novapedidos.llm import Extraccion, ExtractorFijo, MencionExtraida
from novapedidos.servicio import InterpreteDePedidos, texto_sin_cantidad, unidad_desde_texto


def m(texto, producto, skus=(), cantidad=None, unidad="venta", accion="agregar"):
    return MencionExtraida(
        texto=texto,
        producto=producto,
        skus_posibles=list(skus),
        cantidad=cantidad,
        unidad=unidad,
        accion=accion,
    )


def interprete(catalogo, extraccion, estrategia="hibrida"):
    return InterpreteDePedidos(catalogo, ExtractorFijo(extraccion), estrategia)


ANEXO = Extraccion(
    es_pedido=True,
    menciones=[
        m("2 fardos de kola 600", "kola 600", ["B01"], 2),
        m("una caja de aceite", "aceite", ["A06", "A07"], 1),
        m("48 latas de energía max", "energía max", ["B11"], 48, "suelta"),
    ],
)


def test_ejemplo_del_anexo_de_punta_a_punta(catalogo_real):
    r = (
        interprete(catalogo_real, ANEXO)
        .interpretar("C001", datetime(2026, 11, 23, 15, 20), ["..."])
        .respuesta
    )
    assert r.estado is Estado.REQUIERE_REVISION
    assert [(x.sku, x.cantidad, x.subtotal) for x in r.lineas] == [("B01", 2, 240.0), ("B11", 4, 600.0)]
    assert r.total == 840.0 and str(r.fecha_entrega) == "2026-11-26"
    assert [(p.motivo, p.opciones) for p in r.pendientes] == [(Motivo.PRODUCTO_AMBIGUO, ["A06", "A07"])]
    assert "asesor" in r.mensaje_cliente and "jueves 26 de noviembre" in r.mensaje_cliente


def test_cliente_inexistente_no_gasta_tokens(catalogo_real):
    extractor = ExtractorFijo(ANEXO)
    with pytest.raises(ClienteNoEncontrado):
        InterpreteDePedidos(catalogo_real, extractor).interpretar("C999", datetime(2026, 11, 23, 9), ["hola"])
    assert extractor.llamadas == []  # el modelo nunca se llamó


def test_fuera_de_alcance(catalogo_real):
    e = Extraccion(es_pedido=False)
    r = (
        interprete(catalogo_real, e)
        .interpretar("C023", datetime(2026, 11, 27, 14, 40), ["Gracias"])
        .respuesta
    )
    assert r.estado is Estado.FUERA_DE_ALCANCE and r.lineas == [] and r.fecha_entrega is None


def test_la_unidad_la_decide_el_texto_y_no_el_llm(catalogo_real):
    # El LLM dice "suelta" (vio "473 ml"), pero el cliente no dijo latas: son 5 fardos.
    e = Extraccion(
        es_pedido=True, menciones=[m("5 energía max 473 ml", "energía max 473 ml", ["B11"], 5, "suelta")]
    )
    r = interprete(catalogo_real, e).interpretar("C001", datetime(2026, 12, 4, 12, 56), ["..."]).respuesta
    assert [(x.sku, x.cantidad) for x in r.lineas] == [("B11", 5)] and r.estado is Estado.CONFIRMADO


def test_detalle_que_el_llm_quito_se_recupera_del_texto(catalogo_real):
    # El LLM normalizó "arroz quintal" a "arroz" (ambiguo), pero el cliente sí dijo "quintal".
    e = Extraccion(es_pedido=True, menciones=[m("arroz quintal: 2", "arroz", ["A02"], 2)])
    r = interprete(catalogo_real, e).interpretar("C027", datetime(2026, 11, 30, 7, 57), ["..."]).respuesta
    assert [(x.sku, x.cantidad) for x in r.lineas] == [("A02", 2)]


def test_detalle_que_el_llm_invento_no_se_acepta(catalogo_real):
    # El cliente dijo solo "aceite"; el LLM agregó "dorado". Debe quedar ambiguo.
    e = Extraccion(es_pedido=True, menciones=[m("2 cajas de aceite", "aceite dorado", ["A06"], 2)])
    r = interprete(catalogo_real, e).interpretar("C038", datetime(2026, 11, 26, 11, 30), ["..."]).respuesta
    assert r.lineas == [] and r.pendientes[0].opciones == ["A06", "A07"]


def test_correccion_sin_producto_en_el_texto_usa_el_contexto(catalogo_real):
    e = Extraccion(
        es_pedido=True,
        menciones=[
            m("3 fardos de kola 600", "kola 600", ["B01"], 3),
            m("no, mejor que sean 5 de kola", "kola 600", ["B01"], 5, accion="corregir"),
        ],
    )
    r = interprete(catalogo_real, e).interpretar("C001", datetime(2026, 11, 23, 9), ["..."]).respuesta
    assert [(x.sku, x.cantidad) for x in r.lineas] == [("B01", 5)]


def test_quitar_ambiguo_quita_cualquiera_de_las_opciones(catalogo_real):
    # C009: lo de siempre = A07x1 (-> A06), A16x2, B04x1. "sin el aceite" debe quitar el aceite.
    e = Extraccion(
        es_pedido=True, pide_lo_de_siempre=True, menciones=[m("sin el aceite", "aceite", accion="quitar")]
    )
    r = interprete(catalogo_real, e).interpretar("C009", datetime(2026, 12, 1, 7, 51), ["..."]).respuesta
    assert {x.sku for x in r.lineas} == {"A16", "B04"}
    assert r.pendientes == []


def test_pendientes_repetidos_se_unifican(catalogo_real):
    e = Extraccion(
        es_pedido=True,
        menciones=[
            m("2 de aceite", "aceite", cantidad=2),
            m("no, 3 de aceite", "aceite", cantidad=3, accion="corregir"),
        ],
    )
    r = interprete(catalogo_real, e).interpretar("C001", datetime(2026, 11, 23, 9), ["..."]).respuesta
    assert len(r.pendientes) == 1


def test_skus_inventados_por_el_llm_se_descartan(catalogo_real):
    e = Extraccion(es_pedido=True, menciones=[m("5 cervezas", "cerveza", ["Z99"], 5)])
    for estrategia in ("hibrida", "llm", "determinista"):
        r = (
            interprete(catalogo_real, e, estrategia)
            .interpretar("C001", datetime(2026, 11, 23, 9), ["."])
            .respuesta
        )
        assert r.lineas == [] and r.pendientes[0].motivo is Motivo.PRODUCTO_NO_EXISTE


# --- Regresiones del ataque a la API (situaciones fuera de los casos publicados)
def test_paquetes_son_unidades_sueltas(catalogo_real):
    # S01 es un display de 12 paquetes: 24 paquetes = 2 displays (antes se cobraban 24 displays).
    e = Extraccion(
        es_pedido=True,
        menciones=[m("24 paquetes de galletas dulcitas vainilla", "dulcitas vainilla", ["S01"], 24)],
    )
    r = interprete(catalogo_real, e).interpretar("C028", datetime(2026, 11, 25, 10, 30), ["..."]).respuesta
    assert [(x.sku, x.cantidad) for x in r.lineas] == [("S01", 2)]


def test_correccion_sobre_lo_de_siempre_reemplaza(catalogo_real):
    # C015: el último pedido entregado trae A02 x2. "de arroz quintal que sean 3" -> 3, no 5.
    e = Extraccion(
        es_pedido=True,
        pide_lo_de_siempre=True,
        menciones=[m("de arroz quintal que sean 3", "arroz quintal", ["A02"], 3)],  # el LLM dijo "agregar"
    )
    r = interprete(catalogo_real, e).interpretar("C015", datetime(2026, 11, 25, 9, 40), ["..."]).respuesta
    assert dict((x.sku, x.cantidad) for x in r.lineas)["A02"] == 3


def test_correccion_ambigua_se_resuelve_con_lo_ya_pedido(catalogo_real):
    # Caso propio PB05: "ah no, de naranjita mejor 4" tras pedir "naranjita 600" -> corrige B04 (no ambiguo).
    e = Extraccion(
        es_pedido=True,
        menciones=[
            m("3 fardos de naranjita 600", "naranjita 600", ["B04"], 3),
            m("de naranjita mejor 4", "naranjita", ["B04", "B05"], 4, accion="corregir"),
        ],
    )
    r = interprete(catalogo_real, e).interpretar("C001", datetime(2026, 11, 23, 9), ["..."]).respuesta
    assert [(x.sku, x.cantidad) for x in r.lineas] == [("B04", 4)] and r.pendientes == []


def test_correccion_ambigua_sobre_lo_de_siempre(catalogo_real):
    # C009: lo de siempre trae B04 (naranjita 600). "de la naranjita que sean 3" -> B04 x3.
    e = Extraccion(
        es_pedido=True,
        pide_lo_de_siempre=True,
        menciones=[m("de la naranjita que sean 3", "naranjita", ["B04", "B05"], 3, accion="corregir")],
    )
    r = interprete(catalogo_real, e).interpretar("C009", datetime(2026, 12, 1, 7, 51), ["..."]).respuesta
    assert dict((x.sku, x.cantidad) for x in r.lineas)["B04"] == 3 and r.pendientes == []


def test_agregar_ambiguo_sigue_siendo_ambiguo(catalogo_real):
    # El contexto solo aplica a correcciones/exclusiones: pedir "naranjitas" de nuevo NO se adivina.
    e = Extraccion(
        es_pedido=True,
        menciones=[
            m("2 de naranjita 600", "naranjita 600", ["B04"], 2),
            m("y 3 naranjitas", "naranjitas", [], 3),
        ],
    )
    r = interprete(catalogo_real, e).interpretar("C001", datetime(2026, 11, 23, 9), ["..."]).respuesta
    assert r.pendientes[0].opciones == ["B04", "B05"]


def test_un_quintal_de_arroz_no_es_ambiguo(catalogo_real):
    e = Extraccion(es_pedido=True, menciones=[m("un quintal de arroz", "arroz quintal", ["A02"], 1)])
    r = interprete(catalogo_real, e).interpretar("C039", datetime(2026, 12, 10, 10, 40), ["..."]).respuesta
    assert [(x.sku, x.cantidad) for x in r.lineas] == [("A02", 1)] and r.pendientes == []


@pytest.mark.parametrize("cantidad_llm", [1.5, 1])  # aunque el modelo redondee, el texto lo delata
def test_fardo_y_medio_no_se_redondea(catalogo_real, cantidad_llm):
    e = Extraccion(
        es_pedido=True,
        menciones=[m("un fardo y medio de agua pura 600", "agua pura 600", ["B07"], cantidad_llm)],
    )
    r = interprete(catalogo_real, e).interpretar("C030", datetime(2026, 11, 25, 11), ["..."]).respuesta
    assert r.lineas == []
    assert [(p.motivo, p.opciones) for p in r.pendientes] == [(Motivo.CANTIDAD_NO_CONVERTIBLE, ["B07"])]


# --- Regresiones de la auditoría final
@pytest.mark.parametrize(
    ("texto", "cantidad_llm"),
    [("0 fardos de kola 600", None), ("cero fardos de kola 600", None), ("kola 600", 0.0), ("kola 600", -3)],
)
def test_cantidad_cero_o_negativa_no_se_convierte_en_uno(catalogo_real, texto, cantidad_llm):
    # Antes "0 fardos" se confirmaba como 1 fardo (el LLM devolvía null y el código ponía 1).
    menc = MencionExtraida.model_construct(
        texto=texto,
        producto="kola 600",
        skus_posibles=["B01"],
        cantidad=cantidad_llm,
        unidad="venta",
        accion="agregar",
    )
    e = Extraccion(es_pedido=True, menciones=[menc])
    r = interprete(catalogo_real, e).interpretar("C001", datetime(2026, 11, 23, 9), ["..."]).respuesta
    assert r.lineas == [] and r.motivos_revision == [Motivo.CANTIDAD_NO_CONVERTIBLE]


def test_cantidad_absurda_va_a_revision_y_no_da_500(catalogo_real):
    # Antes 1e30 fardos desbordaba Decimal (InvalidOperation) y la API respondía 500.
    e = Extraccion(es_pedido=True, menciones=[m("1e30 fardos de kola 600", "kola 600", ["B01"], 1e30)])
    r = interprete(catalogo_real, e).interpretar("C001", datetime(2026, 11, 23, 9), ["..."]).respuesta
    assert r.lineas == [] and r.motivos_revision == [Motivo.CANTIDAD_NO_CONVERTIBLE]


def test_cantidad_grande_pero_creible_se_procesa(catalogo_real):
    e = Extraccion(es_pedido=True, menciones=[m("600 fardos de kola 600", "kola 600", ["B01"], 600)])
    r = interprete(catalogo_real, e).interpretar("C010", datetime(2026, 11, 23, 9), ["..."]).respuesta
    assert [(x.sku, x.cantidad, x.descuento_pct) for x in r.lineas] == [("B01", 600, 5)]


def test_litro_y_medio_es_presentacion_no_fraccion(catalogo_real):
    e = Extraccion(es_pedido=True, menciones=[m("3 kola de litro y medio", "kola 1.5 l", ["B02"], 3)])
    r = interprete(catalogo_real, e).interpretar("C027", datetime(2026, 11, 30, 7, 57), ["..."]).respuesta
    assert [(x.sku, x.cantidad) for x in r.lineas] == [("B02", 3)]


def test_media_docena(catalogo_real):
    # L03 caja de 12: media docena = 6 botellas -> no exacto; P01 caja de 24 tampoco.
    e = Extraccion(es_pedido=True, menciones=[m("media docena de cloro", "cloro", ["L03"], 0.5, "docena")])
    r = interprete(catalogo_real, e).interpretar("C001", datetime(2026, 11, 23, 9), ["..."]).respuesta
    assert r.motivos_revision == [Motivo.CANTIDAD_NO_CONVERTIBLE]


@pytest.mark.parametrize(
    ("texto", "unidad"),
    [
        ("48 latas de energía max", Unidad.SUELTA),
        ("72 botellas de agua pura", Unidad.SUELTA),
        ("36 bolsas de cafe altura molido", Unidad.SUELTA),
        ("una docena de cloro", Unidad.DOCENA),
        ("5 shampoo birsa sobre 10 ml", Unidad.VENTA),  # "sobre" es parte del nombre
        ("12 sobres de shampoo", Unidad.SUELTA),
        ("5 energía max 473 ml", Unidad.VENTA),
        ("72 jaboncitos rosa sueltos", Unidad.SUELTA),  # caso propio PA11: antes eran 72 cajas
        ("30 sueltas de agua pura", Unidad.SUELTA),
        ("3 fardos de kola 600", Unidad.VENTA),
    ],
)
def test_unidad_desde_texto(texto, unidad):
    assert unidad_desde_texto(texto) is unidad


@pytest.mark.parametrize(
    ("texto", "cantidad", "esperado"),
    [
        ("arroz quintal: 2", 2, "arroz quintal: "),
        ("papel suave 4: 2", 2, "papel suave 4: "),
        ("3 de agua cristal 600", 3, "  de agua cristal 600"),
        ("6 de kola 600 ml", 600, "6 de kola 600 ml"),  # 600 ml es presentación, no la cantidad
        ("kola de 3", None, "kola de 3"),
    ],
)
def test_texto_sin_cantidad(texto, cantidad, esperado):
    assert (
        texto_sin_cantidad(texto, cantidad).replace("  ", " ").strip() == esperado.replace("  ", " ").strip()
    )
