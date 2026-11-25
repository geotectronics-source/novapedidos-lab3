# Imagen de la API (NovaPedidos).
#
# - Dependencias EXACTAS del uv.lock (las mismas versiones probadas en desarrollo).
# - Sin datos ni credenciales: lab3/ se monta como volumen y la clave llega por variables de entorno.
# - Dos etapas: la de construcción tiene uv; la final solo el entorno virtual y el código.
# - Usuario sin privilegios.

# ---------------------------------------------------------------- construcción
FROM python:3.12.13-slim-bookworm AS construccion
COPY --from=ghcr.io/astral-sh/uv:0.11.29 /uv /bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# 1) Solo las dependencias: esta capa se reutiliza mientras no cambie uv.lock (builds rápidos).
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# 2) El código del proyecto.
COPY src ./src
RUN uv sync --frozen --no-dev

# ---------------------------------------------------------------- ejecución
FROM python:3.12.13-slim-bookworm

RUN groupadd --system app && useradd --system --gid app --home /app app

WORKDIR /app
COPY --from=construccion --chown=app:app /app/.venv /app/.venv
COPY --from=construccion --chown=app:app /app/src /app/src

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    DATA_DIR=/app/lab3 \
    MLFLOW_DISABLE_AGENT_HINT=1

USER app
EXPOSE 8000

# /health responde 200 aunque MLflow esté caído (estado "degradado"): el contenedor sigue sano.
HEALTHCHECK --interval=15s --timeout=5s --start-period=40s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4).status == 200 else 1)"

CMD ["uvicorn", "novapedidos.api.app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
