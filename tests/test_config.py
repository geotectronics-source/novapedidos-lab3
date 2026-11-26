"""Pruebas de humo del Inciso 2: la configuración se lee del entorno y los datos están donde se espera."""

from pathlib import Path

import pytest

from novapedidos.config import Settings


def test_valores_por_defecto_sin_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in ("MODELO_LLM", "DATA_DIR", "MLFLOW_TRACKING_URI", "OPENROUTER_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    s = Settings(_env_file=None)
    assert s.openrouter_base_url == "https://openrouter.ai/api/v1"
    assert s.llm_temperatura == 0.0
    assert s.data_dir == Path("lab3")
    assert s.openrouter_api_key is None


def test_variables_de_entorno_sobrescriben(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MODELO_LLM", "proveedor/modelo-x")
    monkeypatch.setenv("MLFLOW_TRACKING_URI", "http://mlflow:5000")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-prueba")
    s = Settings(_env_file=None)
    assert s.modelo_llm == "proveedor/modelo-x"
    assert s.mlflow_tracking_uri == "http://mlflow:5000"
    # La clave es SecretStr: no se imprime por accidente en logs.
    assert "sk-prueba" not in repr(s)
    assert s.openrouter_api_key.get_secret_value() == "sk-prueba"


def test_datos_publicados_presentes() -> None:
    datos = Settings(_env_file=None).data_dir / "datos"
    if not datos.exists():
        pytest.skip("Datos del GES no colocados en lab3/")
    esperados = {"productos", "sinonimos", "precios_escala", "clientes", "historial_pedidos"}
    assert esperados <= {p.stem for p in datos.glob("*.parquet")}
