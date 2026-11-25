# /// script
# requires-python = ">=3.12"
# dependencies = ["pandas", "pyarrow"]
# ///
"""Inciso 1 - Exploración de los archivos parquet del GES.

Uso:  uv run --script eda/01_explorar_datos.py
"""
from pathlib import Path

import pandas as pd

pd.set_option("display.width", 250)
pd.set_option("display.max_columns", 30)
pd.set_option("display.max_rows", 200)
pd.set_option("display.max_colwidth", 60)

DATOS = Path(__file__).resolve().parent.parent / "lab3" / "datos"

for archivo in sorted(DATOS.glob("*.parquet")):
    df = pd.read_parquet(archivo)
    print("=" * 100)
    print(f"{archivo.name}: {df.shape[0]} filas x {df.shape[1]} columnas")
    print("-- tipos:")
    print(df.dtypes.to_string())
    print("-- nulos por columna:")
    print(df.isna().sum().to_string())
    print("-- contenido:")
    print(df.to_string() if len(df) <= 80 else df.head(40).to_string())
