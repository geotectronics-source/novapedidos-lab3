"""Motor de pedidos: aplica politicas.md en orden sobre operaciones ya resueltas a SKU.

    1. "lo de siempre"  -> base = último pedido entregado
    2. operaciones      -> agregar (suma) / corregir (reemplaza) / quitar (elimina), convirtiendo unidades
    3. agotados         -> sustituto (se suma a la línea si ya existe) o pendiente
    4. precios          -> precio de catálogo, descuento por escala, subtotal, total
    5. crédito, fecha de entrega, motivos y estado

No hay LLM aquí: la misma entrada produce siempre la misma salida.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from novapedidos.dominio import reglas
from novapedidos.dominio.catalogo import Catalogo
from novapedidos.dominio.modelos import (
    Accion,
    Estado,
    LineaPedido,
    Motivo,
    Operacion,
    PedidoCalculado,
    Pendiente,
    Sustitucion,
    Unidad,
)

TEXTO_LO_DE_SIEMPRE = "lo de siempre"


@dataclass
class _Acumulado:
    """Lo pedido de un SKU: unidades de venta y unidades sueltas por separado."""

    venta: int = 0
    sueltas: int = 0
    textos_sueltas: list[str] = field(default_factory=list)

    def reiniciar(self) -> None:  # una corrección reemplaza todo lo anterior del SKU
        self.venta, self.sueltas, self.textos_sueltas = 0, 0, []


def pedido_fuera_de_alcance(cliente_id: str) -> PedidoCalculado:
    return PedidoCalculado(cliente_id=cliente_id, estado=Estado.FUERA_DE_ALCANCE)


def construir_pedido(
    catalogo: Catalogo,
    cliente_id: str,
    recibido: datetime,
    *,
    es_pedido: bool,
    pide_lo_de_siempre: bool = False,
    operaciones: Sequence[Operacion] = (),
    pendientes_resolucion: Sequence[Pendiente] = (),
) -> PedidoCalculado:
    """Construye el pedido completo. Lanza ClienteNoEncontrado si el cliente no existe."""
    cliente = catalogo.cliente(cliente_id)
    if not es_pedido:
        return pedido_fuera_de_alcance(cliente_id)

    pendientes: list[Pendiente] = list(pendientes_resolucion)
    # sku -> acumulado. El dict conserva el orden de la primera mención (orden de las líneas).
    acumulados: dict[str, _Acumulado] = {}

    # 1. "Lo de siempre"
    if pide_lo_de_siempre:
        base = catalogo.ultimo_pedido_entregado(cliente_id, antes_de=recibido.date())
        if base is None:
            pendientes.append(Pendiente(motivo=Motivo.PRODUCTO_NO_EXISTE, texto=TEXTO_LO_DE_SIEMPRE))
        else:
            for sku, cantidad in base.lineas:
                acumulados.setdefault(sku, _Acumulado()).venta += cantidad

    # 2. Operaciones del mensaje, en el orden en que el cliente las dijo.
    #    Las unidades sueltas se ACUMULAN por SKU y se convierten al final: "12 botellas" + "otras 12"
    #    son 24 botellas = 1 fardo exacto (politicas.md §2: las menciones repetidas se suman).
    for op in operaciones:
        if op.sku not in catalogo.productos:  # defensa: nunca inventar un SKU aunque llegue uno desconocido
            pendientes.append(Pendiente(motivo=Motivo.PRODUCTO_NO_EXISTE, texto=op.texto))
            continue
        if op.accion is Accion.QUITAR:
            acumulados.pop(op.sku, None)
            continue
        if op.accion is Accion.CORREGIR and op.sku in acumulados:
            acumulados[op.sku].reiniciar()
        acumulado = acumulados.setdefault(op.sku, _Acumulado())
        if op.unidad is Unidad.VENTA:
            acumulado.venta += op.cantidad if op.cantidad is not None else 1
        else:
            acumulado.sueltas += reglas.a_unidades_sueltas(op.cantidad, op.unidad)
            acumulado.textos_sueltas.append(op.texto)

    cantidades: dict[str, int] = {}
    for sku, acumulado in acumulados.items():
        cantidad = acumulado.venta
        if acumulado.sueltas:
            convertidas = reglas.sueltas_a_unidades_venta(
                acumulado.sueltas, catalogo.productos[sku].unidades_por_empaque
            )
            if convertidas is None:  # no exacto: no se redondea, va a revisión
                pendientes.append(
                    Pendiente(
                        motivo=Motivo.CANTIDAD_NO_CONVERTIBLE,
                        texto="; ".join(acumulado.textos_sueltas),
                        opciones=[sku],
                    )
                )
            else:
                cantidad += convertidas
        if cantidad > 0:
            cantidades[sku] = cantidad

    # 3. Agotados: sustituto disponible o pendiente
    finales: dict[str, int] = {}
    sustituciones: list[Sustitucion] = []
    for sku, cantidad in cantidades.items():
        producto = catalogo.productos[sku]
        if producto.disponible:
            finales[sku] = finales.get(sku, 0) + cantidad
            continue
        sustituto = catalogo.productos.get(producto.sustituto_sku) if producto.sustituto_sku else None
        if sustituto is not None and sustituto.disponible:
            finales[sustituto.sku] = finales.get(sustituto.sku, 0) + cantidad
            sustituciones.append(
                Sustitucion(sku_solicitado=sku, sku_entregado=sustituto.sku, cantidad=cantidad)
            )
        else:
            pendientes.append(
                Pendiente(motivo=Motivo.AGOTADO_SIN_SUSTITUTO, texto=producto.nombre, opciones=[sku])
            )

    # 4. Precios, descuentos y total
    lineas: list[LineaPedido] = []
    total = Decimal(0)
    for sku, cantidad in finales.items():
        producto = catalogo.productos[sku]
        pct = reglas.descuento_pct(cantidad, catalogo.escalas.get(producto.categoria, ()))
        sub = reglas.subtotal(cantidad, producto.precio, pct)
        total += sub
        lineas.append(
            LineaPedido(
                sku=sku,
                cantidad=cantidad,
                precio_unitario=float(producto.precio),
                descuento_pct=pct,
                subtotal=float(sub),
            )
        )

    # 5. Crédito, motivos, estado y fecha
    excede = bool(lineas) and reglas.credito_excedido(cliente.saldo_pendiente, total, cliente.limite_credito)
    motivos = reglas.motivos_revision(pendientes, excede)
    estado = reglas.determinar_estado(bool(lineas), motivos)
    if estado is Estado.FUERA_DE_ALCANCE:  # "pedido" sin nada que entregar ni revisar
        return pedido_fuera_de_alcance(cliente_id)

    return PedidoCalculado(
        cliente_id=cliente_id,
        estado=estado,
        lineas=lineas,
        total=float(reglas.redondear(total)),
        fecha_entrega=reglas.fecha_entrega(recibido, cliente.dias_visita),
        sustituciones=sustituciones,
        pendientes=pendientes,
        motivos_revision=motivos,
    )
