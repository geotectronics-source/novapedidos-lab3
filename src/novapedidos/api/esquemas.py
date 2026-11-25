"""Esquemas de la API (Anexo del enunciado): validación de solicitudes y formato de errores.

La validación ocurre ANTES de llamar al modelo: una solicitud inválida responde 422 sin gastar tokens.
"""

from __future__ import annotations

import re
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

FORMATO_FECHA = "%Y-%m-%dT%H:%M"
PATRON_FECHA = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$")
ANIO_MINIMO, ANIO_MAXIMO = 2000, 2100
MAX_MENSAJES = 20  # límites para acotar costo y latencia del modelo
MAX_CARACTERES_MENSAJE = 2000
MAX_CARACTERES_TOTAL = 6000


class SolicitudInterpretar(BaseModel):
    """Cuerpo de POST /v1/pedidos/interpretar."""

    model_config = ConfigDict(
        str_strip_whitespace=True,
        json_schema_extra={
            "examples": [
                {
                    "cliente_id": "C001",
                    "fecha_hora": "2026-11-23T15:20",
                    "mensajes": [
                        "Buenas, mándeme 2 fardos de kola 600, una caja de aceite",
                        "y 48 latas de energía max",
                    ],
                }
            ]
        },
    )

    cliente_id: str = Field(min_length=1, max_length=20, description="Identificador del cliente, p. ej. C001")
    fecha_hora: datetime = Field(
        description="Recepción del último mensaje, AAAA-MM-DDTHH:MM en hora de Guatemala",
        json_schema_extra={"type": "string", "example": "2026-11-23T15:20"},
    )
    mensajes: list[str] = Field(
        min_length=1, max_length=MAX_MENSAJES, description="Mensajes del cliente, en orden"
    )

    @field_validator("cliente_id")
    @classmethod
    def _cliente(cls, v: str) -> str:
        return v.upper()

    @field_validator("fecha_hora", mode="before")
    @classmethod
    def _fecha(cls, v: object) -> datetime:
        mensaje = "debe tener el formato AAAA-MM-DDTHH:MM (hora de Guatemala), por ejemplo 2026-11-23T15:20"
        if not isinstance(v, str) or not PATRON_FECHA.match(v.strip()):
            raise ValueError(mensaje)
        try:
            fecha = datetime.strptime(v.strip(), FORMATO_FECHA)
        except ValueError:
            raise ValueError(f"no es una fecha y hora válida; {mensaje}") from None
        if not ANIO_MINIMO <= fecha.year <= ANIO_MAXIMO:  # el año 9999 desbordaba el cálculo de entrega (500)
            raise ValueError(f"el año debe estar entre {ANIO_MINIMO} y {ANIO_MAXIMO}")
        return fecha

    @field_validator("mensajes")
    @classmethod
    def _mensajes(cls, mensajes: list[str]) -> list[str]:
        if any(not m for m in mensajes):
            raise ValueError("ningún mensaje puede estar vacío")
        if any(len(m) > MAX_CARACTERES_MENSAJE for m in mensajes):
            raise ValueError(f"cada mensaje admite como máximo {MAX_CARACTERES_MENSAJE} caracteres")
        if sum(len(m) for m in mensajes) > MAX_CARACTERES_TOTAL:
            raise ValueError(f"el total de los mensajes admite como máximo {MAX_CARACTERES_TOTAL} caracteres")
        return mensajes


class ErrorCampo(BaseModel):
    campo: str
    mensaje: str


class RespuestaError(BaseModel):
    detail: str = Field(description="Explicación del error")
    errores: list[ErrorCampo] = Field(default_factory=list)


class EstadoServicio(BaseModel):
    estado: str = Field(description="ok | degradado")
    motivo: str | None = Field(default=None, description="Por qué está degradado")
    dependencias: dict[str, str] = Field(default_factory=dict)
    version: str
    modelo: str | None = None


# ------------------------------------------------------------------ errores de validación en español
_TRADUCCIONES = {
    "missing": "es obligatorio",
    "string_type": "debe ser un texto",
    "list_type": "debe ser una lista de textos",
    "too_short": "no puede estar vacío",
    "string_too_short": "no puede estar vacío",
    "too_long": "tiene demasiados elementos",
    "string_too_long": "es demasiado largo",
    "json_invalid": "el cuerpo no es un JSON válido",
    "model_attributes_type": "el cuerpo debe ser un objeto JSON",
    "dict_type": "el cuerpo debe ser un objeto JSON",
}


def traducir_error(error: dict) -> ErrorCampo:
    """Un error de Pydantic/FastAPI -> (campo, mensaje en español)."""
    loc = [str(p) for p in error.get("loc", ()) if p != "body"]
    campo = ".".join(loc) or "cuerpo"
    tipo = error.get("type", "")
    if tipo == "value_error":
        mensaje = str(error.get("ctx", {}).get("error", error.get("msg", ""))).removeprefix("Value error, ")
    elif tipo == "too_short" and campo == "mensajes":
        mensaje = "la lista de mensajes no puede estar vacía"
    elif tipo == "too_long" and campo == "mensajes":
        mensaje = f"admite como máximo {MAX_MENSAJES} mensajes"
    else:
        mensaje = _TRADUCCIONES.get(tipo, error.get("msg", "valor inválido"))
    return ErrorCampo(campo=campo, mensaje=mensaje)
