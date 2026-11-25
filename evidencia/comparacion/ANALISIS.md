# Análisis de la evaluación y elección del modelo

Reproducir: `uv run python -m novapedidos.evaluacion.comparar` (requiere MLflow y `OPENROUTER_API_KEY`).
Tabla completa: [resultados.md](resultados.md) · datos: [resultados.csv](resultados.csv) · detalle por caso: `detalle/`.
En MLflow: experimento `novapedidos-evaluacion`, filtro `tags.comparacion_final = 'true'`.

## 1. Conjunto de evaluación (132 casos)

| Origen | Casos | Qué cubre |
|---|---|---|
| Publicados (`mensajes_dev.jsonl`) | 84 | Los 12 tipos del catálogo de problemas |
| **Propios** (`evaluacion/casos_propios.jsonl`) | 48 | Lo que los publicados **no** cubren |

Casos propios, por familia (12 c/u): **cantidades** (sueltas no exactas → `cantidad_no_convertible`, que no
aparece en ningún caso publicado; docenas; fracciones; paquetes/sobres; umbrales exactos de descuento),
**habitual y correcciones** ("lo de siempre" con correcciones, exclusiones y sustitutos; correcciones cruzadas en
varios mensajes), **seguridad** (7 inyecciones de instrucciones, 2 con crédito excedido; 5 fuera de alcance nuevos)
y **catálogo/negocio** (variantes que no se venden, ambigüedades nuevas, crédito en el límite exacto, 13:59 vs 14:00,
cambio de año).

**Cómo se construyó la respuesta esperada de los casos propios:** 4 agentes escribieron mensaje + interpretación
según `politicas.md` (`casos_propios_fuente.json`); el motor determinista (verificado contra los 84 publicados)
calculó la respuesta esperada (`construir_casos_propios.py`); 4 verificadores independientes, **sin ver la
interpretación**, recalcularon a mano cada caso desde los parquet: 48/48 correctos, 0 discutibles.

## 2. Calificaciones (scorers por código)

Todas deterministas, gratis y reproducibles (`src/novapedidos/evaluacion/`): `pedido_exacto` (métrica principal:
todo correcto a la vez), `estado_correcto`, `lineas_correctas`, `montos_correctos` (precio, descuento, subtotal),
`fecha_correcta`, `motivos_correctos`, `pendientes_correctos` (motivo + opciones; el texto libre no cuenta),
`sustituciones_correctas`, `lineas_f1` (crédito parcial), `contrato_valido` (invariantes del Anexo, sin necesitar
la respuesta correcta), `mensaje_coherente` (§9), y `latencia_s` / `costo_usd` leídos de la traza.

**¿Por qué no un juez LLM?** Lo que el enunciado evalúa (estado, líneas, total, fecha, motivos) tiene una única
respuesta correcta: compararla con código es exacto y gratis. El único texto libre es `mensaje_cliente`, que se
genera con una plantilla a partir del pedido; sus requisitos (§9) se verifican con código.

## 3. Resultados (código final, una corrida por configuración + una repetición)

| Configuración | Exactos | Latencia p50 / p95 | Costo por 1 000 pedidos | Fallas |
|---|---|---|---|---|
| **claude-haiku-5.5 · híbrida** | **132/132 (100 %)** | 2.5 s / 3.7 s | US$0.61 | — |
| claude-haiku-5.5 · híbrida (repetición) | 132/132 (100 %) | 2.4 s / 3.4 s | US$0.61 | — |
| claude-haiku-5.5 · determinista | 132/132 (100 %) | 2.0 s / 3.4 s | US$0.61 | — |
| claude-haiku-5.5 · **solo LLM** | 129/132 (97.7 %) | 2.3 s / 3.4 s | US$0.61 | D008, D014, PA10 |
| deepseek-v4.1-flash · híbrida | 131/132 (99.2 %) | 2.7 s / **5.4 s** | US$0.31 | D025 |
| gpt-6-luna · híbrida | 132/132 (100 %) | **1.8 s** / 3.7 s | **US$0.11** | — |
| claude-sonnet-5.5 · híbrida | 132/132 (100 %) | 2.2 s / 4.0 s | US$12.00 | — |

![Comparación](comparacion.png)

### Lectura de las fallas

- **Solo LLM (97.7 %)**: el modelo responde "lo que probablemente quiso decir" en vez de "todo lo que podría
  significar": "pasta" sin la pasta dental (D008, D014); y al revés, marcó "frijol negro" como ambiguo con
  el frijol rojo aunque el cliente dijo el color (PA10). Es la razón de
  la estrategia híbrida: **la ambigüedad la decide el código**.
- **deepseek (D025)**: extrajo "lo mismo que la vez pasada" como si fuera un producto → pendiente
  `producto_no_existe` extra (las líneas sí eran correctas).
- **Variabilidad entre corridas**: en una corrida intermedia, haiku segmentó mal "pasta: 2, seis fardos de
  espagueti" (1 vez en 264 interpretaciones de ese caso). Con temperatura 0 los modelos no son 100 % deterministas.

### Límite estadístico

Con 132 casos y 0 fallas, la tasa de error real podría llegar a ~2.3 % (regla del 3: 3/n, IC 95 %). Por eso
**la calidad no distingue entre haiku, luna y sonnet**: la elección se decide por costo, latencia y operación.

## 4. Hallazgos operativos (también son evidencia)

| Hallazgo | Consecuencia en el producto |
|---|---|
| `claude-sonnet-5.5` rechaza `function_calling` (no admite `tool_choice` forzado) | El extractor prueba el otro método de salida estructurada automáticamente |
| `gpt-6-luna` y `claude-sonnet-5.5`: **20 solicitudes/minuto** en cuentas nuevas (429) | Riesgo para un modelo principal bajo la carga de la evaluación |
| Un caso propio (PA11, "72 jaboncitos rosa **sueltos**") reveló que "sueltos" no se reconocía como unidad suelta | Corregido; sin casos propios habría pasado inadvertido |
| Un caso propio (PB05, "de **naranjita** mejor 4") reveló que una corrección ambigua no usaba el contexto | Corregido: correcciones/exclusiones se resuelven con lo ya pedido |

## 5. Decisión

- **Modelo principal: `anthropic/claude-haiku-5.5`** — 100 % en dos corridas, sin límite de solicitudes observado
  con 4 en paralelo, p95 < 4 s, US$0.61 por 1 000 pedidos.
- **Modelo de respaldo: `openai/gpt-6-luna`** — 100 %, el más rápido y barato, **de otro proveedor** (si Anthropic
  falla o limita, responde OpenAI). No es el principal solo por su límite de 20 solicitudes/min en cuentas nuevas:
  con una cuenta establecida sería la opción óptima en costo (5.8× más barato) y latencia.
- **Estrategia: híbrida.** Empata con la determinista en este conjunto, pero agrega el respaldo del LLM para jerga
  que el vocabulario no cubre y detecta discrepancias LLM/código; la estrategia "solo LLM" es claramente peor.
- **Sonnet descartado**: misma calidad a 20× el costo de haiku.
