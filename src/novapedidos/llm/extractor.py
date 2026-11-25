"""Extractor: mensajes del cliente -> Extraccion (salida estructurada de LangChain sobre OpenRouter).

Se define como un Protocol para que la API y las pruebas puedan usar un extractor falso
(`ExtractorFijo`) sin llamar al modelo: el enunciado exige pruebas que no dependan del LLM.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Protocol

from langchain_openai import ChatOpenAI

from novapedidos.config import Settings
from novapedidos.dominio.catalogo import Catalogo
from novapedidos.llm.esquemas import Extraccion
from novapedidos.llm.prompts import VERSION_PROMPT, mensaje_sistema, mensaje_usuario


class ErrorExtraccion(RuntimeError):
    """El modelo no respondió o no produjo una salida válida tras los reintentos."""


@dataclass(frozen=True)
class ResultadoExtraccion:
    extraccion: Extraccion
    modelo: str
    latencia_s: float = 0.0
    tokens_entrada: int = 0
    tokens_salida: int = 0
    costo_usd: float = 0.0
    intentos: int = 1


class Extractor(Protocol):
    modelo: str

    def extraer(self, mensajes: Sequence[str]) -> ResultadoExtraccion: ...


class ExtractorLLM:
    """LangChain `with_structured_output` + OpenRouter (API compatible con OpenAI)."""

    def __init__(
        self,
        settings: Settings,
        catalogo: Catalogo,
        *,
        modelo: str | None = None,
        metodo: str | None = None,
    ) -> None:
        if settings.openrouter_api_key is None:
            raise ErrorExtraccion("Falta OPENROUTER_API_KEY en el entorno / .env")
        self.modelo = modelo or settings.modelo_llm
        self.metodo = metodo or settings.llm_metodo_salida
        self.version_prompt = VERSION_PROMPT
        self._sistema = mensaje_sistema(catalogo)
        respaldo = settings.modelo_llm_respaldo if modelo is None else None  # en comparaciones, sin respaldo
        self._cadenas = [(m, self._crear_cadena(settings, m)) for m in (self.modelo, respaldo) if m]
        self._intentos_parseo = 2  # si el modelo devuelve JSON inválido, se pide de nuevo una vez

    def _crear_cadena(self, settings: Settings, modelo: str):
        llm = ChatOpenAI(
            model=modelo,
            base_url=settings.openrouter_base_url,
            api_key=settings.openrouter_api_key,
            temperature=settings.llm_temperatura,
            timeout=settings.llm_timeout_s,
            max_retries=settings.llm_max_reintentos,  # reintentos de red / 429 / 5xx con espera exponencial
            extra_body={"usage": {"include": True}},  # OpenRouter devuelve el costo exacto
        )
        return llm.with_structured_output(Extraccion, method=self.metodo, include_raw=True)

    def extraer(self, mensajes: Sequence[str]) -> ResultadoExtraccion:
        errores = []
        for modelo, cadena in self._cadenas:
            try:
                return self._extraer_con(modelo, cadena, mensajes)
            except ErrorExtraccion as e:
                errores.append(str(e))
        raise ErrorExtraccion(" | ".join(errores))

    def _extraer_con(self, modelo: str, cadena, mensajes: Sequence[str]) -> ResultadoExtraccion:
        entrada = [("system", self._sistema), ("human", mensaje_usuario(mensajes))]
        inicio = time.perf_counter()
        tokens_in = tokens_out = 0
        costo = 0.0
        ultimo_error: Exception | None = None
        for intento in range(1, self._intentos_parseo + 1):
            try:
                respuesta = cadena.invoke(entrada)
            except Exception as e:  # red, timeout, 4xx/5xx tras los reintentos de ChatOpenAI
                raise ErrorExtraccion(f"Falló la llamada al modelo {modelo}: {e}") from e
            raw = respuesta.get("raw")
            if raw is not None:
                uso = raw.usage_metadata or {}
                tokens_in += uso.get("input_tokens", 0)
                tokens_out += uso.get("output_tokens", 0)
                costo += float((raw.response_metadata.get("token_usage") or {}).get("cost") or 0.0)
            if respuesta.get("parsed") is not None:
                return ResultadoExtraccion(
                    extraccion=respuesta["parsed"],
                    modelo=modelo,
                    latencia_s=time.perf_counter() - inicio,
                    tokens_entrada=tokens_in,
                    tokens_salida=tokens_out,
                    costo_usd=costo,
                    intentos=intento,
                )
            ultimo_error = respuesta.get("parsing_error")
        raise ErrorExtraccion(f"Salida no válida del modelo {modelo}: {ultimo_error}")


class ExtractorFijo:
    """Doble de prueba: devuelve una extracción predefinida (o la calcula con una función)."""

    def __init__(self, extraccion: Extraccion | Callable[[Sequence[str]], Extraccion], modelo: str = "fijo"):
        self._extraccion = extraccion
        self.modelo = modelo
        self.llamadas: list[list[str]] = []

    def extraer(self, mensajes: Sequence[str]) -> ResultadoExtraccion:
        self.llamadas.append(list(mensajes))
        e = self._extraccion(mensajes) if callable(self._extraccion) else self._extraccion
        return ResultadoExtraccion(extraccion=e, modelo=self.modelo)
