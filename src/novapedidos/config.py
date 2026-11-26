"""Configuración central, leída de variables de entorno o del archivo .env.

Todo lo que cambia entre entornos (clave, modelo, rutas, URL de MLflow) vive aquí y
en ningún otro lugar del código. Ver .env.example para la lista completa.
"""

from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- Modelo de lenguaje (OpenRouter) ---
    openrouter_api_key: SecretStr | None = Field(default=None, description="Clave de OpenRouter")
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    modelo_llm: str = Field(
        default="anthropic/claude-haiku-5.5", description="Modelo principal (id de OpenRouter)"
    )
    modelo_llm_respaldo: str | None = Field(
        default=None, description="Modelo alterno si el principal falla (429, caída). Vacío = sin respaldo"
    )
    llm_temperatura: float = 0.0
    llm_timeout_s: float = 30.0
    llm_max_reintentos: int = 2
    llm_metodo_salida: str = Field(default="function_calling", description="function_calling | json_schema")
    estrategia_resolucion: str = Field(default="hibrida", description="hibrida | determinista | llm")

    # --- Datos publicados por el equipo docente ---
    data_dir: Path = Field(default=Path("lab3"), description="Carpeta con datos/, politicas.md, ejemplos/")

    # --- Observabilidad ---
    mlflow_tracking_uri: str = "http://localhost:5000"
    mlflow_experimento: str = "novapedidos"
    mlflow_timeout_s: float = 2.0
    trazas_activas: bool = Field(default=True, description="Enviar trazas de cada solicitud a MLflow")


@lru_cache
def get_settings() -> Settings:
    """Devuelve una única instancia (se lee el entorno una sola vez)."""
    return Settings()
