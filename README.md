# NovaPedidos — Toma de pedidos por WhatsApp con LLMs

Laboratorio 3 · Product Development · Maestría en Data Science.

API que recibe los mensajes informales que los tenderos envían por WhatsApp y propone un pedido
estructurado y verificable: líneas, precios, descuentos, total, fecha de entrega, sustituciones,
pendientes para revisión humana y un mensaje de confirmación para el cliente.

> 🚧 En construcción. Las instrucciones de `docker compose up` y de evaluación se completan en los
> incisos 9 y 10.

## Requisitos

- Docker Desktop (con Docker Compose).
- Una clave de [OpenRouter](https://openrouter.ai).
- Para desarrollo local: [uv](https://docs.astral.sh/uv/) (instala Python 3.12 automáticamente).

## Datos

Los datos publicados en el GES **no** están en el repositorio. Descomprímalos en la carpeta `lab3/`
en la raíz del proyecto, de modo que queden así:

```
lab3/
├── datos/  productos.parquet · sinonimos.parquet · precios_escala.parquet · clientes.parquet · historial_pedidos.parquet
├── ejemplos/mensajes_dev.jsonl
├── politicas.md
└── catalogo_problemas.md
```

(Otra ubicación: ajuste `DATA_DIR` en `.env`.)

## Configuración

```powershell
Copy-Item .env.example .env   # y complete OPENROUTER_API_KEY
```

## Desarrollo local

```powershell
uv sync
uv run pytest                 # pruebas sin modelo
uv run pytest -m llm          # pruebas con el modelo real (requiere OPENROUTER_API_KEY)
uv run uvicorn novapedidos.api.app:app --port 8000
```

Documentación interactiva de la API: http://127.0.0.1:8000/docs

## API

`POST /v1/pedidos/interpretar`

```json
{
  "cliente_id": "C001",
  "fecha_hora": "2026-11-23T15:20",
  "mensajes": ["Buenas, mándeme 2 fardos de kola 600, una caja de aceite", "y 48 latas de energía max"]
}
```

| Código | Cuándo |
|---|---|
| 200 | Pedido interpretado (contrato del Anexo) |
| 404 | El cliente no existe |
| 422 | Solicitud inválida (campos faltantes, lista vacía, fecha que no es `AAAA-MM-DDTHH:MM`…); `detail` explica el motivo |
| 503 | El modelo de lenguaje no está disponible (reintentar) |

`GET /health` → `{"estado": "ok" | "degradado", "motivo": ..., "dependencias": {...}}`

## Evaluación reproducible (MLflow)

Requiere un servidor de MLflow (el de `docker compose` o uno local) y `OPENROUTER_API_KEY` en `.env`.

```powershell
# Una configuración (modelo + estrategia) sobre los 84 casos publicados + 48 propios
uv run python -m novapedidos.evaluacion.ejecutar --modelo anthropic/claude-haiku-5.5 --conjunto todos

# La comparación completa de alternativas (7 configuraciones, ~US$1.8, ~25 min)
uv run python -m novapedidos.evaluacion.comparar

# Reconstruir las respuestas esperadas de los casos propios a partir de su interpretación
uv run python evaluacion/construir_casos_propios.py
```

Resultados en MLflow (experimento `novapedidos-evaluacion`) y en `evidencia/comparacion/`
([análisis y elección del modelo](evidencia/comparacion/ANALISIS.md)).

## Documentación

- [DECISIONES.md](DECISIONES.md): decisiones de diseño, alternativas y justificación.
- [CLAUDE.md](CLAUDE.md): contexto para agentes de programación.
- [eda/REPORTE_EDA.md](eda/REPORTE_EDA.md): exploración de datos y verificación de las reglas.
