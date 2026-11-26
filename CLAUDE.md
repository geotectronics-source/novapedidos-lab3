# CLAUDE.md — contexto para agentes de programación

Proyecto académico (Laboratorio 3, Product Development): API que convierte mensajes informales de
WhatsApp de tenderos en pedidos estructurados para NovaDistribuidora. Stack: Python 3.12, uv,
LangChain + OpenRouter, FastAPI, MLflow, Docker Compose.

## Principio de arquitectura (no negociable)

- **El LLM solo extrae** (qué producto mencionó el cliente, cantidad, unidad, acción, si es pedido,
  si pide "lo de siempre"), siempre con **salida estructurada**.
- **El código calcula y decide**: resolución a SKU, conversión de unidades, consolidación, agotados,
  precios, descuentos, crédito, fecha de entrega y estado. Todo en `src/novapedidos/dominio/` con pruebas.
- Ningún texto del cliente puede alterar precios, descuentos, crédito ni instrucciones del sistema.
- Ante la duda, no adivinar: registrar un pendiente (`producto_ambiguo`, `producto_no_existe`,
  `agotado_sin_sustituto`, `cantidad_no_convertible`).

## Estructura

```
src/novapedidos/
  config.py        Settings (pydantic-settings) leídos de .env
  dominio/         reglas del negocio (sin LLM)
  resolucion/      texto → SKU (sinónimos, fuzzy matching, ambigüedad)
  llm/             cadenas LangChain, prompts, esquemas de extracción
  api/             FastAPI: POST /v1/pedidos/interpretar, GET /health
  observabilidad/  MLflow (trazas), tolerante a que MLflow no esté disponible
  evaluacion/      scorers por código, evaluación y comparación en MLflow
  servicio.py      pipeline: cliente → LLM → resolución → motor → mensaje
tests/             pytest; NO llaman al modelo (marcador `llm` para las que sí)
evaluacion/        casos propios (.jsonl + fuente) y prueba de punta a punta por HTTP
evidencia/         resultados de la comparación y capturas de MLflow
eda/               exploración de datos (REPORTE_EDA.md: reglas verificadas)
lab3/              datos del GES — NO se versiona (montado como volumen en Docker)
```

## Comandos

```powershell
uv sync                         # instala dependencias (uv.lock)
uv run pytest                   # pruebas sin LLM
uv run pytest -m llm            # pruebas que llaman al modelo real
uv run ruff check . ; uv run ruff format .
```

## Reglas verificadas contra los 84 casos (ver eda/REPORTE_EDA.md)

- Montos con `Decimal` y `ROUND_HALF_UP` a 2 decimales; descuento por la cantidad final de la línea.
- Crédito excedido si `saldo_pendiente + total > limite_credito`.
- Fecha efectiva = recepción (+1 día si hora ≥ 14:00); entrega = primer día de visita **estrictamente posterior**.
- "Lo de siempre" = último pedido `entregado` (los cancelados no cuentan); se le aplican agotados/sustitutos.
- Sustituto que ya existe en el pedido se suma a esa línea. Quitar un producto ocurre antes de evaluar agotados.
- Una corrección o exclusión también descarta los pendientes de la mención anterior de ese producto
  (`servicio._sin_pendientes_rectificados`, DECISIONES D15/D20). "sobre" tras una cantidad es unidad suelta.
- Pendiente de agotado sin sustituto: `texto` = nombre del catálogo, `opciones` = [sku].
- Unidades sueltas/docenas se acumulan por SKU y se convierten una sola vez (12 + 12 botellas = 1 fardo).
- Interfaz del motor: `construir_pedido(catalogo, cliente_id, recibido, es_pedido=, pide_lo_de_siempre=,
  operaciones=[Operacion], pendientes_resolucion=[Pendiente])`. Ver DECISIONES.md D5–D6.

## Resolución de productos (src/novapedidos/resolucion/)

- `Resolutor(catalogo).resolver(texto) -> Resolucion(tipo=UNICO|AMBIGUO|NO_EXISTE, skus)`.
- Precisión antes que cobertura: palabra no reconocida → NO_EXISTE; fuzzy solo por distancia de edición
  (≤1, ≤2 en 10+ letras, mínimo 5 letras), nunca `fuzz.ratio`.
- Vocabulario curado en `normalizacion.py` (STOPWORDS, SINONIMOS_PALABRA, SINONIMOS_FRASE). Al agregar un
  sinónimo, agregar su caso a `tests/resolucion/test_resolutor.py`.

## Capa LLM y pipeline

- `llm/esquemas.py` (Extraccion) es lo único que se consume del modelo; nunca agregar campos de precio/total.
- `llm/prompts.py`: subir `VERSION_PROMPT` al cambiar el prompt (se registra en MLflow).
- `servicio.InterpreteDePedidos.interpretar(cliente_id, recibido, mensajes)`: cliente → LLM → resolución
  (`resolucion/combinar.py`, estrategia `hibrida`) → motor → plantilla de mensaje.
- La unidad se deriva del texto literal (`unidad_desde_texto`), no del LLM.
- En pruebas usar `ExtractorFijo`; las que llaman al modelo real llevan `@pytest.mark.llm`.

## API (src/novapedidos/api/)

- `crear_app(settings, interprete, verificador_mlflow)` permite inyectar dobles; las pruebas de
  `tests/api/` nunca llaman al modelo.
- Validación en `api/esquemas.py` (422 en español, antes de llamar al modelo); 404 cliente; 503 LLM caído.
- Si los puertos 8000/5000 están ocupados, usar `uvicorn ... --port 8001` y `MLFLOW_PUERTO_HOST` en `.env`.
  En pruebas locales preferir `127.0.0.1` a `localhost` (en Windows, `localhost` agrega ~2 s por IPv6).

## Observabilidad (src/novapedidos/observabilidad/)

- `/health` incluye `dependencias.trazas` (`ok` | `inicializando` | `desactivadas`); los 422 dejan traza `solicitud_rechazada`.
- `trazas.py`: usar `with span(nombre, tipo, entradas) as s: ...; s.salidas(...)` y `etiquetar_traza()`; nunca
  llamar a mlflow directamente desde el dominio o el servicio (si MLflow falla, la solicitud debe seguir).
- Las variables `MLFLOW_*` (async, reintentos 0, timeout 2 s) se fijan en `trazas.py` antes de importar mlflow.
- MLflow para desarrollo: `docker compose up -d mlflow` (puerto 5000), o sin Docker:
  `uv run mlflow server --host 127.0.0.1 --port 5000 --backend-store-uri sqlite:///mlflow_data/mlflow.db
  --default-artifact-root ./mlflow_data/artifacts`. `MLFLOW_TRACKING_URI` en `.env` debe apuntar al mismo puerto.

## Evaluación (src/novapedidos/evaluacion/, evaluacion/)

- Casos propios: editar `evaluacion/casos_propios_fuente.json` (mensaje + interpretación) y regenerar con
  `uv run python evaluacion/construir_casos_propios.py`; nunca editar a mano el `.jsonl` generado.
- Scorers por código en `comparacion.py` (funciones puras, probadas en `tests/test_evaluacion.py`) envueltos
  con `@scorer` en `scorers.py`. La métrica principal es `pedido_exacto`.
- Tras cualquier cambio de código o prompt, la comparación publicada debe re-ejecutarse
  (`uv run python -m novapedidos.evaluacion.comparar`): los resultados deben corresponder al código final.
- Modelos con 20 solicitudes/min (gpt-6-luna, claude-sonnet-5.5) se evalúan con `rps=0.3`.

## Docker

```powershell
docker compose up --build            # API :8000 + MLflow :5000
docker compose stop mlflow           # prueba de tolerancia: /health -> degradado, la API sigue respondiendo
uv run python evaluacion/probar_http.py --interrumpir-mlflow   # prueba de punta a punta por HTTP
```

- Dentro de compose la API usa `MLFLOW_TRACKING_URI=http://mlflow:5000` (lo fija el compose, manda sobre `.env`).
- Nada de datos ni credenciales en la imagen: revisar `.dockerignore` al agregar archivos.
- Probar comandos de documentación en PowerShell 5.1 (comillas, charset) antes de publicarlos.

## Convenciones

- Código e identificadores en español (como el contrato de la API). Tipos en todas las firmas.
- Nunca versionar `.env` ni `lab3/`. Configuración nueva → `config.py` y `.env.example`.
- Antes de terminar un cambio: `uv run ruff check .` y `uv run pytest` en verde.
