"""Capa de modelo de lenguaje con LangChain y OpenRouter (Inciso 5).

Extracción con salida estructurada. El mensaje al cliente se redacta con plantilla (dominio/mensaje.py).
"""

from novapedidos.llm.esquemas import Extraccion, MencionExtraida
from novapedidos.llm.extractor import (
    ErrorExtraccion,
    Extractor,
    ExtractorFijo,
    ExtractorLLM,
    ResultadoExtraccion,
)

__all__ = [
    "ErrorExtraccion",
    "Extraccion",
    "Extractor",
    "ExtractorFijo",
    "ExtractorLLM",
    "MencionExtraida",
    "ResultadoExtraccion",
]
