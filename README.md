# NovaPedidos — Toma de pedidos por WhatsApp con LLMs

Laboratorio 3 · Product Development · Maestría en Data Science.

API que recibe los mensajes informales que los tenderos envían por WhatsApp y propone un pedido
estructurado y verificable: líneas, precios, descuentos, total, fecha de entrega, sustituciones,
pendientes para revisión humana y un mensaje de confirmación para el cliente.

**Arquitectura:** el LLM (LangChain + OpenRouter, salida estructurada) solo *extrae* qué pidió el cliente;
el código determinista y probado resuelve los productos y calcula precios, descuentos, crédito, fechas y
estado. Ningún mensaje puede alterar precios ni condiciones. Detalle en [DECISIONES.md](DECISIONES.md).

## Levantar el producto (un comando)

Requisitos: Docker Desktop (con Docker Compose) y una clave de [OpenRouter](https://openrouter.ai).

**1. Datos.** Los datos publicados en el GES **no** están en el repositorio. Descomprímalos en la carpeta
`lab3/`, en la raíz del proyecto:

```
lab3/
├── datos/        productos.parquet · sinonimos.parquet · precios_escala.parquet · clientes.parquet · historial_pedidos.parquet
├── ejemplos/     mensajes_dev.jsonl
├── politicas.md
└── catalogo_problemas.md
```

(Si están en otra carpeta: `DATA_HOST_DIR=C:/ruta/a/la/carpeta` en `.env` para Docker; para las pruebas y los
scripts de evaluación que corren fuera de Docker, ponga también `DATA_DIR` con la misma ruta.)

**2. Configuración.** Copie el ejemplo y escriba su clave en `OPENROUTER_API_KEY`:

```powershell
Copy-Item .env.example .env
```

(En Linux/macOS: `cp .env.example .env`.) El modelo ya viene configurado en `.env.example`
(`MODELO_LLM=anthropic/claude-haiku-5.5`, respaldo `openai/gpt-6-luna`).

**3. Levantar:**

```powershell
docker compose up --build
```

| Servicio | URL |
|---|---|
| API | http://localhost:8000 · documentación interactiva: http://localhost:8000/docs |
| MLflow (trazas y evaluaciones) | http://localhost:5000 |

La primera vez tarda ~1 minuto en construir la imagen; la API queda lista unos 10 s después de arrancar.

**4. Verificar** (PowerShell):

```powershell
Invoke-RestMethod http://localhost:8000/health
```

```powershell
Invoke-RestMethod -Method Post -Uri http://localhost:8000/v1/pedidos/interpretar -ContentType "application/json" -Body '{"cliente_id": "C001", "fecha_hora": "2026-11-23T15:20", "mensajes": ["Buenas, mandeme 2 fardos de kola 600, una caja de aceite", "y 48 latas de energia max"]}'
```

En Linux/macOS (bash):

```bash
curl -s -X POST http://localhost:8000/v1/pedidos/interpretar -H 'Content-Type: application/json' \
  -d '{"cliente_id": "C001", "fecha_hora": "2026-11-23T15:20", "mensajes": ["Buenas, mandeme 2 fardos de kola 600, una caja de aceite", "y 48 latas de energia max"]}'
```

Notas para Windows: en PowerShell 5.1 no use `curl.exe -d '...'` (parte el JSON en los espacios), y en Git Bash
`curl` envía los acentos en cp1252, no en UTF-8 (la API responde 422 explicando que el cuerpo debe ser UTF-8).

**Tolerancia a fallas de MLflow:** con `docker compose stop mlflow`, la API sigue respondiendo y
`GET /health` devuelve `"estado": "degradado"` con el motivo; con `docker compose start mlflow` todo se
recupera solo, sin reiniciar la API.

**Puertos ocupados:** la API usa el 8000 (lo exige el contrato). Si el 5000 está ocupado por otro
servicio, cambie el puerto de MLflow en `.env`: `MLFLOW_PUERTO_HOST=5001` (y, para los scripts de evaluación,
`MLFLOW_TRACKING_URI=http://127.0.0.1:5001`).

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
| 503 | El modelo de lenguaje no está disponible tras reintentos y modelo de respaldo (reintentar) |

`GET /health` → `{"estado": "ok" | "degradado", "motivo": ..., "dependencias": {"datos", "mlflow", "llm"}}`

## Evaluación reproducible

Con el producto levantado (`docker compose up`) y `uv` instalado:

```powershell
uv sync

# Prueba de punta a punta POR HTTP contra el contenedor: 132 casos, solicitudes inválidas y caída de MLflow
uv run python evaluacion/probar_http.py --interrumpir-mlflow

# Evaluación en MLflow de una configuración (84 casos publicados + 48 propios)
uv run python -m novapedidos.evaluacion.ejecutar --modelo anthropic/claude-haiku-5.5 --conjunto todos

# Comparación completa de alternativas (7 configuraciones, ~US$2, ~35–40 min por los límites de solicitudes)
uv run python -m novapedidos.evaluacion.comparar
```

Los scripts escriben en el MLflow del compose con `MLFLOW_TRACKING_URI=http://127.0.0.1:5000` (el valor de
`.env.example`). Ese MLflow arranca vacío: el experimento `novapedidos-evaluacion` aparece al correr `ejecutar`
o `comparar`. Los resultados de la entrega (ejecutados en desarrollo) están versionados:
[evidencia/comparacion/ANALISIS.md](evidencia/comparacion/ANALISIS.md) (análisis y elección del modelo),
capturas de MLflow en [evidencia/mlflow/](evidencia/mlflow/) y la prueba en Docker en
[evidencia/docker/prueba_http.json](evidencia/docker/prueba_http.json).
Casos propios: [evaluacion/casos_propios.jsonl](evaluacion/casos_propios.jsonl) (mismo formato que `mensajes_dev.jsonl`).

## Desarrollo local (sin Docker)

```powershell
uv sync
uv run pytest                 # pruebas sin modelo (~390, ~15 s)
uv run pytest -m llm          # pruebas con el modelo real (requiere OPENROUTER_API_KEY)
docker compose up -d mlflow   # opcional: MLflow para las trazas (o TRAZAS_ACTIVAS=false en .env)
uv run uvicorn novapedidos.api.app:app --port 8000
```

## Estructura

```
src/novapedidos/
  dominio/          reglas del negocio (precios, descuentos, crédito, fechas, estado) — sin LLM
  resolucion/       texto del cliente → SKU (sinónimos, fonética, ambigüedad, "no existe")
  llm/              extracción con LangChain + OpenRouter (salida estructurada) y prompt
  servicio.py       pipeline: cliente → LLM → resolución → motor → mensaje
  api/              FastAPI (contrato del Anexo, validación 422, /health)
  observabilidad/   trazas en MLflow tolerantes a fallas; verificación de salud
  evaluacion/       scorers por código, evaluación y comparación en MLflow
tests/              pruebas automatizadas que no dependen del modelo
evaluacion/         casos propios y prueba por HTTP
evidencia/          comparación de alternativas, capturas de MLflow, prueba en Docker
eda/                exploración de datos y verificación de las reglas
```

## Documentación

- [DECISIONES.md](DECISIONES.md): decisiones de diseño, alternativas y justificación (incluida la elección del modelo).
- [CLAUDE.md](CLAUDE.md): contexto para agentes de programación.
- [eda/REPORTE_EDA.md](eda/REPORTE_EDA.md): exploración de datos y verificación de las reglas.
