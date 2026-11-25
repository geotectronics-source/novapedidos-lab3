"""Esquema de salida estructurada: lo ÚNICO que el código consume del modelo.

Fíjate en lo que NO está aquí: precios, descuentos, subtotales, totales, fechas, crédito, estado.
El modelo no tiene dónde escribirlos, así que ningún mensaje puede alterarlos por esta vía.
Las descripciones de los campos viajan al modelo como parte del esquema: son instrucciones.
"""

from typing import Literal

from pydantic import BaseModel, Field


class MencionExtraida(BaseModel):
    texto: str = Field(
        description="Fragmento literal del mensaje donde el cliente pide el producto, con su cantidad "
        "(ej. 'una caja de aceite', '48 latas de energía max')."
    )
    producto: str = Field(
        description="SOLO el producto, sin cantidad ni empaque, con la ortografía corregida y los nombres "
        "informales llevados a palabras del catálogo, SIN agregar marca, sabor ni presentación que el cliente "
        "no dijo. Ej: 'nranjita 600' -> 'naranjita 600'; 'azuquita' -> 'azúcar'; 'una caja de aceite' -> "
        "'aceite'; 'kola de litro y medio' -> 'kola 1.5 l'; 'cinco cajas de cerveza' -> 'cerveza'."
    )
    skus_posibles: list[str] = Field(
        default_factory=list,
        description="SKUs del catálogo que podrían ser lo que pidió el cliente: uno si es inequívoco, TODOS "
        "los que encajen si es ambiguo (ej. 'aceite' -> ['A06','A07']), lista vacía si no se vende.",
    )
    cantidad: int | None = Field(
        default=None, ge=1, description="Número pedido, en dígitos. null si el cliente no dijo cantidad."
    )
    unidad: Literal["venta", "suelta", "docena"] = Field(
        default="venta",
        description="'venta' si dijo fardo/caja/display/quintal o no dijo unidad; 'suelta' si pidió "
        "botellas, latas, bolsas, sobres o unidades sueltas; 'docena' si pidió docenas.",
    )
    accion: Literal["agregar", "corregir", "quitar"] = Field(
        default="agregar",
        description="'agregar' para un pedido normal; 'corregir' cuando el cliente cambia la cantidad de "
        "algo que ya pidió ('no, mejor que sean 5', 'corrijo: de X son 8'), con la cantidad FINAL; "
        "'quitar' cuando pide no incluir algo ('pero sin las papitas', 'quíteme la sal').",
    )


class Extraccion(BaseModel):
    es_pedido: bool = Field(
        description="true si el cliente está haciendo o modificando un pedido; false si solo pregunta, "
        "agradece, reclama o saluda."
    )
    pide_lo_de_siempre: bool = Field(
        default=False,
        description="true si pide 'lo de siempre', 'lo mismo de la otra vez', 'lo de cada semana', "
        "'mi pedido de siempre', 'lo mismo del último pedido' o equivalente. 'Le hago mi pedido' NO lo es.",
    )
    menciones: list[MencionExtraida] = Field(
        default_factory=list,
        description="Cada producto mencionado, en el orden del mensaje. Sin precios ni totales.",
    )
