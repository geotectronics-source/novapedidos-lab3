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


def test_pedido_grande_entero_se_calcula_y_va_a_revision_por_credito(catalogo_real):
    # Auditoría Codex N15: 10 001 fardos caían en cantidad_no_convertible (tope de 10 000).
    e = Extraccion(es_pedido=True, menciones=[m("10001 fardos de kola 600", "kola 600", ["B01"], 10001)])
    r = interprete(catalogo_real, e).interpretar("C001", datetime(2026, 11, 23, 15, 20), ["..."]).respuesta
    assert [(x.sku, x.cantidad, x.descuento_pct) for x in r.lineas] == [("B01", 10001, 5)]
    assert r.total == 1140114.0 and r.motivos_revision == [Motivo.CREDITO_EXCEDIDO] and r.pendientes == []


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
        ("1 sobre de shampoo Brisa de 10 ml", Unidad.SUELTA),  # auditoría Codex N08
        ("un sobre de shampoo brisa", Unidad.SUELTA),
        ("shampoo brisa sobre de 10 ml", Unidad.VENTA),  # sin cantidad delante: es el nombre
        ("3 de shampoo brisa sobre 10 ml", Unidad.VENTA),
        # Revisión adversarial del Inciso 11: variantes y "sobre" como preposición
        ("un solo sobre de shampoo brisa", Unidad.SUELTA),
        ("otro sobre de shampoo brisa", Unidad.SUELTA),
        ("1sobre de shampoo brisa", Unidad.SUELTA),
        ("un sobresito de shampoo brisa", Unidad.SUELTA),
        ("3 fardos de kola 600 sobre lo de siempre", Unidad.VENTA),
        ("kola 600 sobre el pedido de ayer", Unidad.VENTA),
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


# --- Regresiones de la auditoría de Codex (mensajes inéditos N04–N08): una rectificación reemplaza
#     lo pedido ANTES, incluidos sus pendientes (politicas.md §2).
C001 = ("C001", datetime(2026, 11, 23, 15, 20))


def test_quitar_producto_ambiguo_elimina_su_pendiente(catalogo_real):
    # N04: "4 fardos de kola 600 y 2 cajas de aceite" + "ya no quiero el aceite" -> confirmado.
    e = Extraccion(
        es_pedido=True,
        menciones=[
            m("4 fardos de kola 600", "kola 600", ["B01"], 4),
            m("2 cajas de aceite", "aceite", ["A06", "A07"], 2),
            m("ya no quiero el aceite", "aceite", accion="quitar"),
        ],
    )
    r = interprete(catalogo_real, e).interpretar(*C001, ["..."]).respuesta
    assert r.estado is Estado.CONFIRMADO and r.pendientes == [] and r.total == 480.0


def test_cancelar_producto_inexistente_elimina_su_pendiente(catalogo_real):
    # N05: "dos cajas de cerveza" + "cancele la cerveza" -> confirmado con la kola.
    e = Extraccion(
        es_pedido=True,
        menciones=[
            m("2 fardos de kola 600", "kola 600", ["B01"], 2),
            m("dos cajas de cerveza", "cervezas", [], 2),
            m("cancele la cerveza", "cerveza", accion="quitar"),
        ],
    )
    r = interprete(catalogo_real, e).interpretar(*C001, ["..."]).respuesta
    assert r.estado is Estado.CONFIRMADO and r.pendientes == [] and r.total == 240.0


def test_quitar_otro_producto_inexistente_no_elimina_el_pendiente(catalogo_real):
    e = Extraccion(
        es_pedido=True,
        menciones=[
            m("dos cajas de cerveza", "cerveza", [], 2),
            m("sin el vino", "vino", accion="quitar"),
        ],
    )
    r = interprete(catalogo_real, e).interpretar(*C001, ["..."]).respuesta
    assert [(p.motivo, p.texto) for p in r.pendientes] == [(Motivo.PRODUCTO_NO_EXISTE, "cerveza")]


@pytest.mark.parametrize("producto_primero", ["kola 600", "kola"])  # el LLM puede perder el "600"
def test_quitar_producto_con_fraccion_elimina_su_pendiente(catalogo_real, producto_primero):
    # N06: "un fardo y medio de kola 600 y 1 fardo de agua pura 600" + "quite por completo la kola".
    e = Extraccion(
        es_pedido=True,
        menciones=[
            m("un fardo y medio de kola", producto_primero, [], 1.5),
            m("1 fardo de agua pura 600", "agua pura 600", ["B07"], 1),
            m("quite por completo la kola", "kola", accion="quitar"),
        ],
    )
    r = interprete(catalogo_real, e).interpretar(*C001, ["..."]).respuesta
    assert r.estado is Estado.CONFIRMADO and r.pendientes == []
    assert [(x.sku, x.cantidad) for x in r.lineas] == [("B07", 1)]


def test_corregir_fraccion_a_cantidad_entera_elimina_el_pendiente(catalogo_real):
    # N07: "un fardo y medio de kola 600" + "corrija a 2 fardos de kola 600" -> B01 x2 confirmado.
    e = Extraccion(
        es_pedido=True,
        menciones=[
            m("un fardo y medio de kola 600", "kola 600", ["B01"], 1.5),
            m("corrija a 2 fardos de kola 600", "kola 600", ["B01"], 2, accion="corregir"),
        ],
    )
    r = interprete(catalogo_real, e).interpretar(*C001, ["..."]).respuesta
    assert r.estado is Estado.CONFIRMADO and r.pendientes == []
    assert [(x.sku, x.cantidad) for x in r.lineas] == [("B01", 2)]


def test_corregir_entera_a_fraccion_deja_un_solo_pendiente(catalogo_real):
    e = Extraccion(
        es_pedido=True,
        menciones=[
            m("2 fardos de kola 600", "kola 600", ["B01"], 2),
            m("mejor un fardo y medio de kola 600", "kola 600", ["B01"], 1.5, accion="corregir"),
        ],
    )
    r = interprete(catalogo_real, e).interpretar(*C001, ["..."]).respuesta
    assert r.lineas == [] and [p.motivo for p in r.pendientes] == [Motivo.CANTIDAD_NO_CONVERTIBLE]


def test_corregir_ambiguo_con_producto_preciso_resuelve_la_ambiguedad(catalogo_real):
    # "una caja de aceite" + "mejor que sean 2 de girasol dorado": el cliente aclaró cuál.
    e = Extraccion(
        es_pedido=True,
        menciones=[
            m("una caja de aceite", "aceite", ["A06", "A07"], 1),
            m("mejor que sean 2 de girasol dorado", "aceite girasol dorado", ["A06"], 2, accion="corregir"),
        ],
    )
    r = interprete(catalogo_real, e).interpretar(*C001, ["..."]).respuesta
    assert r.pendientes == [] and [(x.sku, x.cantidad) for x in r.lineas] == [("A06", 2)]


def test_quitar_producto_ya_pedido_no_borra_otro_pendiente_ambiguo(catalogo_real):
    # "2 fardos de kola 600 y una kola" + "quite la kola 600": la exclusión es de la línea B01;
    # la otra "kola" sigue sin saberse cuál es -> revisión.
    e = Extraccion(
        es_pedido=True,
        menciones=[
            m("2 fardos de kola 600", "kola 600", ["B01"], 2),
            m("y una kola", "kola", [], 1),
            m("quite la kola 600", "kola 600", ["B01"], accion="quitar"),
        ],
    )
    r = interprete(catalogo_real, e).interpretar(*C001, ["..."]).respuesta
    assert r.lineas == [] and [p.motivo for p in r.pendientes] == [Motivo.PRODUCTO_AMBIGUO]


def test_agregar_no_rectifica_pendientes_anteriores(catalogo_real):
    e = Extraccion(
        es_pedido=True,
        menciones=[
            m("una caja de aceite", "aceite", ["A06", "A07"], 1),
            m("y 2 de girasol dorado", "aceite girasol dorado", ["A06"], 2),
        ],
    )
    r = interprete(catalogo_real, e).interpretar(*C001, ["..."]).respuesta
    assert [p.motivo for p in r.pendientes] == [Motivo.PRODUCTO_AMBIGUO]


def test_un_sobre_suelto_no_se_cobra_como_display(catalogo_real):
    # N08: P02 es un display de 24 sobres; 1 sobre no es exacto -> revisión, no 1 display por Q36.
    e = Extraccion(
        es_pedido=True,
        menciones=[m("1 sobre de shampoo Brisa de 10 ml", "shampoo brisa 10 ml", ["P02"], 1, "suelta")],
    )
    r = interprete(catalogo_real, e).interpretar(*C001, ["..."]).respuesta
    assert r.lineas == [] and r.motivos_revision == [Motivo.CANTIDAD_NO_CONVERTIBLE]
    assert r.pendientes[0].opciones == ["P02"]


# --- Regresiones de la revisión adversarial del Inciso 11: ante la duda, el pendiente se conserva.
def test_excluir_una_opcion_de_un_ambiguo_conserva_el_pendiente(catalogo_real):
    # "1 kola" + "pero no la de 600": sigue sin saberse si es B02 o B03 (antes se confirmaba sin kola).
    e = Extraccion(
        es_pedido=True,
        menciones=[
            m("1 kola", "kola", [], 1),
            m("2 de agua pura 600", "agua pura 600", ["B07"], 2),
            m("pero no la de 600", "kola 600", ["B01"], accion="quitar"),
        ],
    )
    r = interprete(catalogo_real, e).interpretar(*C001, ["..."]).respuesta
    assert r.estado is Estado.REQUIERE_REVISION
    esperado = [(Motivo.PRODUCTO_AMBIGUO, ["B01", "B02", "B03"])]
    assert [(p.motivo, p.opciones) for p in r.pendientes] == esperado


def test_excluir_una_marca_de_aceite_ambiguo_conserva_el_pendiente(catalogo_real):
    e = Extraccion(
        es_pedido=True,
        menciones=[
            m("una caja de aceite", "aceite", ["A06", "A07"], 1),
            m("sin el girasol dorado", "aceite girasol dorado", ["A06"], accion="quitar"),
        ],
    )
    r = interprete(catalogo_real, e).interpretar(*C001, ["..."]).respuesta
    assert r.estado is Estado.REQUIERE_REVISION and r.pendientes[0].opciones == ["A06", "A07"]


def test_quitar_otra_variante_inexistente_no_borra_el_pendiente(catalogo_real):
    # "kola norte light" no existe; "quite la kola de 2 litros" (nunca pedida) no es la misma.
    e = Extraccion(
        es_pedido=True,
        menciones=[
            m("2 fardos de kola 600", "kola 600", ["B01"], 2),
            m("1 fardo de kola norte light", "kola norte light", [], 1),
            m("quite la kola de 2 litros", "kola 2 litros", [], accion="quitar"),
        ],
    )
    r = interprete(catalogo_real, e).interpretar(*C001, ["..."]).respuesta
    assert [(p.motivo, p.texto) for p in r.pendientes] == [(Motivo.PRODUCTO_NO_EXISTE, "kola norte light")]


def test_red_de_correccion_no_borra_el_pendiente_de_otra_mencion(catalogo_real):
    # El modelo marca ambas como "agregar"; "que sea" activa la red _CORRECCION, pero eso no aclara el
    # aceite ambiguo de la primera mención: son dos productos pedidos.
    e = Extraccion(
        es_pedido=True,
        menciones=[
            m("una caja de aceite", "aceite", ["A06", "A07"], 1),
            m("y 2 cajas de girasol dorado, que sea del de 750", "aceite girasol dorado", ["A06"], 2),
        ],
    )
    r = interprete(catalogo_real, e).interpretar(*C001, ["..."]).respuesta
    assert [p.motivo for p in r.pendientes] == [Motivo.PRODUCTO_AMBIGUO]
    assert [(x.sku, x.cantidad) for x in r.lineas] == [("A06", 2)]


def test_preposicion_sobre_no_convierte_fardos_en_sueltas(catalogo_real):
    e = Extraccion(
        es_pedido=True,
        menciones=[m("3 fardos de kola 600 sobre lo de siempre", "kola 600", ["B01"], 3)],
    )
    r = interprete(catalogo_real, e).interpretar(*C001, ["..."]).respuesta
    assert [(x.sku, x.cantidad) for x in r.lineas] == [("B01", 3)] and r.pendientes == []
