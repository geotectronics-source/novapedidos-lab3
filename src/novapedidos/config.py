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
    modelo_llm: str = Field(default="openai/gpt-4.1-mini", description="Modelo principal (id de OpenRouter)")
    llm_temperatura: float = 0.0
    llm_timeout_s: float = 30.0
    llm_max_reintentos: int = 2

    # --- Datos publicados por el equipo docente ---
    data_dir: Path = Field(default=Path("lab3"), description="Carpeta con datos/, politicas.md, ejemplos/")

    # --- Observabilidad ---
    mlflow_tracking_uri: str = "http://localhost:5000"
    mlflow_experimento: str = "novapedidos"
    mlflow_timeout_s: float = 2.0

    @property
    def datos_dir(self) -> Path:
        return self.data_dir / "datos"


@lru_cache
def get_settings() -> Settings:
    """Devuelve una única instancia (se lee el entorno una sola vez)."""
    return Settings()
