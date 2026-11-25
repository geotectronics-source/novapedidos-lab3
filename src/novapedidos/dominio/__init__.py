"""Reglas del negocio en código determinista y probado (Inciso 3).

Modelos Pydantic del pedido, conversión de unidades, consolidación, agotados y sustitutos,
precios y descuentos por escala, crédito, fecha de entrega y estado. Nada aquí llama al LLM.
"""

from novapedidos.dominio.catalogo import Catalogo, ClienteNoEncontrado, DatosInvalidos
from novapedidos.dominio.modelos import (
    Accion,
    Estado,
    LineaPedido,
    Motivo,
    Operacion,
    PedidoCalculado,
    Pendiente,
    RespuestaPedido,
    Sustitucion,
    Unidad,
)
from novapedidos.dominio.motor import construir_pedido

__all__ = [
    "Accion",
    "Catalogo",
    "ClienteNoEncontrado",
    "DatosInvalidos",
    "Estado",
    "LineaPedido",
    "Motivo",
    "Operacion",
    "PedidoCalculado",
    "Pendiente",
    "RespuestaPedido",
    "Sustitucion",
    "Unidad",
    "construir_pedido",
]
