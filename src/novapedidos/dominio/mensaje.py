"""Mensaje de confirmación para el cliente (politicas.md §9), redactado con una plantilla.

Por qué plantilla y no LLM: el mensaje se construye A PARTIR del pedido calculado, así que es coherente
por construcción: no puede prometer un agotado, mencionar un precio distinto ni olvidar decir que un
asesor confirmará. Además no agrega latencia ni costo. (Ver DECISIONES.md.)
"""

from datetime import date, datetime

from novapedidos.dominio.catalogo import Catalogo
from novapedidos.dominio.modelos import Estado, Motivo, PedidoCalculado

DIAS = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")
MESES = (
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
)  # fmt: skip
PLURALES = {"fardo": "fardos", "caja": "cajas", "display": "displays", "quintal": "quintales"}


def saludo(recibido: datetime) -> str:
    if recibido.hour < 12:
        return "¡Buenos días!"
    if recibido.hour < 19:
        return "¡Buenas tardes!"
    return "¡Buenas noches!"


def fecha_en_palabras(d: date) -> str:
    return f"{DIAS[d.weekday()]} {d.day} de {MESES[d.month - 1]}"


def _enumerar(partes: list[str]) -> str:
    return partes[0] if len(partes) == 1 else ", ".join(partes[:-1]) + " y " + partes[-1]


def _cantidad(cantidad: int, unidad: str) -> str:
    return f"{cantidad} {unidad if cantidad == 1 else PLURALES.get(unidad, unidad + 's')}"


def redactar_mensaje(pedido: PedidoCalculado, catalogo: Catalogo, recibido: datetime) -> str:
    inicio = saludo(recibido)
    if pedido.estado is Estado.FUERA_DE_ALCANCE:
        return f"{inicio} Gracias por escribirnos. Un asesor atenderá su mensaje a la brevedad."

    frases: list[str] = []
    if pedido.lineas:
        items = [
            f"{_cantidad(linea.cantidad, catalogo.productos[linea.sku].unidad_venta)} de "
            f"{catalogo.productos[linea.sku].nombre}"
            for linea in pedido.lineas
        ]
        frases.append(f"Recibimos su pedido: {_enumerar(items)}.")
    else:
        frases.append("Recibimos su mensaje.")

    for s in pedido.sustituciones:
        frases.append(
            f"{catalogo.productos[s.sku_solicitado].nombre} está agotado, así que le enviamos "
            f"{catalogo.productos[s.sku_entregado].nombre}."
        )

    for p in pedido.pendientes:
        if p.motivo is Motivo.PRODUCTO_AMBIGUO:
            frases.append(f"Sobre «{p.texto}», un asesor le confirmará cuál producto desea.")
        elif p.motivo is Motivo.PRODUCTO_NO_EXISTE:
            frases.append(f"Sobre «{p.texto}», un asesor le confirmará si lo podemos conseguir.")
        elif p.motivo is Motivo.AGOTADO_SIN_SUSTITUTO:
            frases.append(f"{p.texto} está agotado; un asesor se comunicará con usted.")
        elif p.motivo is Motivo.CANTIDAD_NO_CONVERTIBLE:
            frases.append(f"Sobre «{p.texto}», un asesor le confirmará la cantidad.")

    if Motivo.CREDITO_EXCEDIDO in pedido.motivos_revision:
        frases.append("Un asesor revisará su crédito y le confirmará el pedido antes de enviarlo.")

    if pedido.lineas:
        frases.append(f"Total: Q{pedido.total:,.2f}.")
    if pedido.fecha_entrega:
        prefijo = "Entrega" if pedido.estado is Estado.CONFIRMADO else "Entrega estimada"
        frases.append(f"{prefijo} el {fecha_en_palabras(pedido.fecha_entrega)}.")
    frases.append("¡Gracias!")
    return " ".join([inicio, *frases])
