"""Modelos del dominio: la entrada que recibe el motor y la salida que exige el contrato.

Entrada del motor (la producen las capas de LLM y de resolución):
    Operacion   -> "el cliente pidió agregar / corregir / quitar el SKU X, cantidad N, en tal unidad"
    Pendiente   -> lo que la resolución ya no pudo convertir en SKU (ambiguo, no existe)

Salida (Anexo del enunciado):
    PedidoCalculado -> estado, líneas, total, fecha, sustituciones, pendientes, motivos
    RespuestaPedido -> lo anterior + mensaje_cliente
"""

from datetime import date
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Estado(StrEnum):
    CONFIRMADO = "confirmado"
    REQUIERE_REVISION = "requiere_revision"
    FUERA_DE_ALCANCE = "fuera_de_alcance"


class Motivo(StrEnum):
    """El orden de declaración es el orden canónico en `motivos_revision`."""

    PRODUCTO_AMBIGUO = "producto_ambiguo"
    PRODUCTO_NO_EXISTE = "producto_no_existe"
    AGOTADO_SIN_SUSTITUTO = "agotado_sin_sustituto"
    CANTIDAD_NO_CONVERTIBLE = "cantidad_no_convertible"
    CREDITO_EXCEDIDO = "credito_excedido"  # solo en motivos_revision, nunca en pendientes


class Unidad(StrEnum):
    VENTA = "venta"  # fardo, caja, display, quintal... o sin unidad ("3 de kola 600")
    SUELTA = "suelta"  # botellas, latas, bolsas, sobres, unidades
    DOCENA = "docena"


class Accion(StrEnum):
    AGREGAR = "agregar"  # se suma a lo que ya había del mismo SKU
    CORREGIR = "corregir"  # reemplaza la cantidad ("no, mejor que sean 5")
    QUITAR = "quitar"  # elimina la línea ("pero sin las papalinas")


# ----------------------------------------------------------------------------- entrada del motor
class Operacion(BaseModel):
    """Una instrucción ya resuelta a un SKU del catálogo.

    `extra="forbid"`: no existe forma de colar un precio, descuento o crédito por esta vía.
    """

    model_config = ConfigDict(extra="forbid")

    sku: str
    texto: str = Field(description="Fragmento del mensaje del cliente que originó la operación")
    accion: Accion = Accion.AGREGAR
    cantidad: int | None = Field(default=None, ge=1, description="None = el cliente no dijo cantidad")
    unidad: Unidad = Unidad.VENTA


# ----------------------------------------------------------------------------- salida (contrato)
class LineaPedido(BaseModel):
    sku: str
    cantidad: int = Field(ge=1)
    precio_unitario: float
    descuento_pct: int = Field(ge=0, le=100)
    subtotal: float


class Sustitucion(BaseModel):
    sku_solicitado: str
    sku_entregado: str
    cantidad: int = Field(ge=1)


class Pendiente(BaseModel):
    motivo: Motivo
    texto: str
    opciones: list[str] = Field(default_factory=list)

    @field_validator("motivo")
    @classmethod
    def _sin_credito(cls, motivo: Motivo) -> Motivo:
        if motivo is Motivo.CREDITO_EXCEDIDO:
            raise ValueError("credito_excedido solo puede aparecer en motivos_revision")
        return motivo


class PedidoCalculado(BaseModel):
    cliente_id: str
    estado: Estado
    lineas: list[LineaPedido] = Field(default_factory=list)
    total: float = 0.0
    fecha_entrega: date | None = None
    sustituciones: list[Sustitucion] = Field(default_factory=list)
    pendientes: list[Pendiente] = Field(default_factory=list)
    motivos_revision: list[Motivo] = Field(default_factory=list)


class RespuestaPedido(PedidoCalculado):
    mensaje_cliente: str
