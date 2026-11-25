"""Reglas del negocio como funciones puras (misma entrada -> misma salida, sin efectos).

Cada función implementa una sección de politicas.md y se prueba por separado.
Los montos se manejan con Decimal: con float, 0.1 + 0.2 != 0.3 y los centavos se desvían.
"""

from collections.abc import Iterable, Sequence
from datetime import date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal

from novapedidos.dominio.catalogo import Escalon, Producto
from novapedidos.dominio.modelos import Estado, Motivo, Pendiente, Unidad

HORA_CORTE = time(14, 0)  # politicas.md §7: a las 14:00 o después cuenta como el día siguiente
CENTAVO = Decimal("0.01")
UNIDADES_POR_DOCENA = 12


# ---------------------------------------------------------------- §2 Cantidades
def a_unidades_sueltas(cantidad: int | None, unidad: Unidad) -> int:
    """Cantidad expresada en unidades sueltas. "una docena" sin número = 1 docena = 12."""
    if unidad is Unidad.VENTA:
        raise ValueError("Solo aplica a unidades sueltas o docenas")
    n = 1 if cantidad is None else cantidad
    if n < 1:
        raise ValueError("La cantidad debe ser un entero positivo")
    return n * UNIDADES_POR_DOCENA if unidad is Unidad.DOCENA else n


def sueltas_a_unidades_venta(sueltas: int, unidades_por_empaque: int) -> int | None:
    """División EXACTA entre unidades_por_empaque; None si no es exacta (nunca se redondea)."""
    enteros, residuo = divmod(sueltas, unidades_por_empaque)
    return None if residuo or enteros == 0 else enteros


def convertir_a_unidades_venta(cantidad: int | None, unidad: Unidad, producto: Producto) -> int | None:
    """Convierte UNA mención a unidades de venta (fardo, caja, display, quintal).

    - Sin cantidad en unidad de venta -> 1 unidad de venta ("y unas manías").
    - En unidad de venta (o sin unidad) -> tal cual.
    - Sueltas o docenas -> división exacta; si no es exacta -> None (`cantidad_no_convertible`).

    El motor no convierte mención por mención: acumula las sueltas de cada SKU y llama a
    `sueltas_a_unidades_venta` una sola vez (ver motor.py).
    """
    if unidad is Unidad.VENTA:
        if cantidad is not None and cantidad < 1:
            raise ValueError("La cantidad debe ser un entero positivo")
        return 1 if cantidad is None else cantidad
    return sueltas_a_unidades_venta(a_unidades_sueltas(cantidad, unidad), producto.unidades_por_empaque)


# ---------------------------------------------------------------- §5 Precios y descuentos
def redondear(monto: Decimal) -> Decimal:
    """Redondeo a 2 decimales, mitad hacia arriba (2.345 -> 2.35)."""
    return monto.quantize(CENTAVO, rounding=ROUND_HALF_UP)


def descuento_pct(cantidad: int, escalones: Sequence[Escalon]) -> int:
    """Mayor porcentaje cuyo mínimo se alcance con la cantidad de la línea (0 si ninguno)."""
    return max((e.descuento_pct for e in escalones if cantidad >= e.cantidad_minima), default=0)


def subtotal(cantidad: int, precio: Decimal, pct: int) -> Decimal:
    """cantidad × precio × (1 − descuento/100), redondeado a centavos."""
    return redondear(Decimal(cantidad) * precio * (Decimal(100 - pct) / Decimal(100)))


# ---------------------------------------------------------------- §6 Crédito
def credito_excedido(saldo_pendiente: Decimal, total: Decimal, limite_credito: Decimal) -> bool:
    """'Supera' = estrictamente mayor. Igualar el límite no lo excede."""
    return saldo_pendiente + total > limite_credito


# ---------------------------------------------------------------- §7 Fecha de entrega
def fecha_efectiva(recibido: datetime) -> date:
    """Un pedido recibido a las 14:00 o después se considera recibido al día siguiente."""
    return recibido.date() + timedelta(days=1) if recibido.time() >= HORA_CORTE else recibido.date()


def fecha_entrega(recibido: datetime, dias_visita: Iterable[int]) -> date:
    """Primer día de visita ESTRICTAMENTE posterior a la fecha efectiva.

    Verificado con los 84 casos (eda/03_verificar_reglas.py): un pedido del lunes 09:00 de un
    cliente con visita lunes/jueves se entrega el jueves, no el mismo lunes.
    """
    dias = set(dias_visita)
    if not dias:
        raise ValueError("El cliente no tiene días de visita")
    dia = fecha_efectiva(recibido) + timedelta(days=1)
    while dia.weekday() not in dias:
        dia += timedelta(days=1)
    return dia


# ---------------------------------------------------------------- §8 Estado
def motivos_revision(pendientes: Iterable[Pendiente], excede_credito: bool) -> list[Motivo]:
    """Motivos únicos, en el orden canónico del enum Motivo."""
    presentes = {p.motivo for p in pendientes}
    if excede_credito:
        presentes.add(Motivo.CREDITO_EXCEDIDO)
    return [m for m in Motivo if m in presentes]


def determinar_estado(hay_lineas: bool, motivos: Sequence[Motivo]) -> Estado:
    if motivos:
        return Estado.REQUIERE_REVISION
    if hay_lineas:
        return Estado.CONFIRMADO
    return Estado.FUERA_DE_ALCANCE
