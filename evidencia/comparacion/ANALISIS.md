# Análisis de la evaluación y elección del modelo

Reproducir: `uv run python -m novapedidos.evaluacion.comparar` (requiere MLflow y `OPENROUTER_API_KEY`).
Tabla completa: [resultados.md](resultados.md) · datos: [resultados.csv](resultados.csv) · detalle por caso: `detalle/`.
En MLflow: experimento `novapedidos-evaluacion`, filtro `tags.comparacion_final = 'true'` (o
`tags.comparacion = 'post-auditoria-139'`). Los runs de la entrega inicial (132 casos) quedan como historial con
`tags.comparacion = 'entrega-inicial-132'`.

## 1. Conjunto de evaluación (139 casos)

| Origen | Casos | Qué cubre |
|---|---|---|
| Publicados (`mensajes_dev.jsonl`) | 84 | Los 12 tipos del catálogo de problemas |
| **Propios** (`evaluacion/casos_propios.jsonl`) | 55 | Lo que los publicados **no** cubren: 48 de la entrega inicial + 7 de regresión (PE01–PE07) |

Casos propios, por familia (12 c/u): **cantidades** (sueltas no exactas → `cantidad_no_convertible`, que no
aparece en ningún caso publicado; docenas; fracciones; paquetes/sobres; umbrales exactos de descuento),
**habitual y correcciones** ("lo de siempre" con correcciones, exclusiones y sustitutos; correcciones cruzadas en
varios mensajes), **seguridad** (7 inyecciones de instrucciones, 2 con crédito excedido; 5 fuera de alcance nuevos)
y **catálogo/negocio** (variantes que no se venden, ambigüedades nuevas, crédito en el límite exacto, 13:59 vs 14:00,
cambio de año). Familia **auditoría** (7, después de la entrega): rectificaciones que deben eliminar el pendiente de
la mención anterior, "un sobre" suelto y un pedido enorme que se calcula y va a revisión por crédito (DECISIONES D20).

**Cómo se construyó la respuesta esperada de los casos propios:** 4 agentes escribieron mensaje + interpretación
según `politicas.md` (`casos_propios_fuente.json`); el motor determinista (verificado contra los 84 publicados)
calculó la respuesta esperada (`construir_casos_propios.py`); 4 verificadores independientes, **sin ver la
interpretación**, recalcularon a mano cada caso desde los parquet: 48/48 correctos, 0 discutibles. Los 7 casos de
regresión se verificaron igual, con un verificador que no vio la respuesta esperada: 7/7.

## 2. Calificaciones (scorers por código)

Todas deterministas, gratis y reproducibles (`src/novapedidos/evaluacion/`): `pedido_exacto` (métrica principal:
todo correcto a la vez), `estado_correcto`, `lineas_correctas`, `montos_correctos` (precio, descuento, subtotal),
`total_correcto`, `fecha_correcta`, `motivos_correctos`, `pendientes_correctos` (motivo + opciones; el texto libre no cuenta),
`sustituciones_correctas`, `lineas_f1` (crédito parcial), `contrato_valido` (invariantes del Anexo, sin necesitar
la respuesta correcta), `mensaje_coherente` (§9), y `latencia_s` / `costo_usd` leídos de la traza.

**¿Por qué no un juez LLM?** Lo que el enunciado evalúa (estado, líneas, total, fecha, motivos) tiene una única
respuesta correcta: compararla con código es exacto y gratis. El único texto libre es `mensaje_cliente`, que se
genera con una plantilla a partir del pedido; sus requisitos (§9) se verifican con código.

## 3. Resultados (código final, una corrida por configuración + una repetición)

Re-ejecutada completa después de las correcciones de la auditoría externa (DECISIONES D20), con el código final.

| Configuración | Exactos | Latencia p50 / p95 | Costo por 1 000 pedidos | Fallas |
|---|---|---|---|---|
| **claude-haiku-5.5 · híbrida** | **139/139 (100 %)** | 2.5 s / 4.4 s | US$0.61 | — |
| claude-haiku-5.5 · híbrida (repetición) | 139/139 (100 %) | 2.3 s / 3.5 s | US$0.61 | — |
| claude-haiku-5.5 · determinista | 139/139 (100 %) | 2.4 s / 4.3 s | US$0.61 | — |
| claude-haiku-5.5 · **solo LLM** | 136/139 (97.8 %) | 2.2 s / 3.7 s | US$0.61 | D008, D014, PA10 |
| deepseek-v4.1-flash · híbrida | 139/139 (100 %) | 2.6 s / **5.9 s** | US$0.36 | — |
| gpt-6-luna · híbrida | 139/139 (100 %) | **1.9 s** / 5.4 s | **US$0.11** | — |
| claude-sonnet-5.5 · híbrida | 138/139 (99.3 %) | 2.2 s / 4.1 s | US$11.90 | PE06: error del proveedor (sin respuesta) |

El costo se leyó de la traza en 139/139 casos de cada configuración (138/139 en Sonnet: el caso sin respuesta no
tuvo costo). Las latencias son de la evaluación y varían entre corridas: el p95 de haiku híbrido fue 4.4 s y 3.5 s
en las dos corridas de este mismo código.

![Comparación](comparacion.png)

### Lectura de las fallas

- **Solo LLM (136/139 = 97.8 %)**: el modelo responde "lo que probablemente quiso decir" en vez de "todo lo que podría
  significar": "pasta" sin la pasta dental (D008, D014); y al revés, marcó "frijol negro" como ambiguo con
  el frijol rojo aunque el cliente dijo el color (PA10). Es la razón de
  la estrategia híbrida: **la ambigüedad la decide el código**.
- **deepseek**: en la comparación de la entrega inicial falló D025 (extrajo "lo mismo que la vez pasada" como si
  fuera un producto); en esta corrida acertó los 139. Es variabilidad del modelo, no un cambio de código que lo
  afecte.
- **Sonnet (PE06)**: no fue una respuesta incorrecta sino un error del proveedor (sin respuesta tras los
  reintentos); la evaluación lo cuenta como falla.
- **Variabilidad entre corridas**: en una corrida intermedia (no publicada, con el código de ese momento), haiku
  segmentó mal "pasta: 2, seis fardos de espagueti" en D008. Ese caso se interpretó bien en las otras corridas de
  haiku híbrido: con temperatura 0 los modelos no son 100 % deterministas.

### Dentro vs. fuera de muestra (lectura honesta del 100 %)

El 139/139 es exactitud **dentro de la muestra**: los 84 casos publicados se usaron para ajustar el prompt
(v1 → v3, ver DECISIONES D10), dos casos propios (PA11, PB05) revelaron defectos que se corrigieron y los 7 casos
PE se escribieron a partir de la auditoría externa. Por eso la cota "regla del 3" (~2.2 % de error) **no** se puede
leer como el error esperado con mensajes nuevos.

| Medición (haiku · híbrida) | Exactos | IC 95 % (Wilson) | Tipo |
|---|---|---|---|
| Prompt v1 sobre los 84 publicados, antes de ajustar | 72/84 = 85.7 % | [76.7 %, 91.6 %] | punto de partida |
| **Primer contacto con los 48 casos propios** (creados después de cerrar el prompt v3; falló PA11) | **47/48 = 97.9 %** | **[89.1 %, 99.6 %]** | **fuera de muestra** |
| Auditoría externa: 19 mensajes inéditos con expectativa no discutible (N01–N20, tag `entrega-lab3`) | 13/19 = 68.4 % | [46.0 %, 84.6 %] | fuera de muestra, **casos límite elegidos para romper** |
| Los mismos 19 tras las correcciones | 19/19 = 100 % | [83.2 %, 100 %] | dentro de la muestra (se corrigió con ellos) |
| Versión final sobre los 139 | 139/139 = 100 % | [97.3 %, 100 %] | dentro de la muestra |

Detalle por caso del primer contacto: [primer_contacto_casos_propios.json](primer_contacto_casos_propios.json),
exportado del run de MLflow de ese momento (commit `b3a1ce5`, prompt v3). Ese run no guardaba el id de cada caso; se
emparejó por la entrada con los casos propios. Los mensajes inéditos y sus resultados antes y después están en
[../auditoria/ineditos_N01_N20.json](../auditoria/ineditos_N01_N20.json).

Las dos mediciones fuera de muestra no se contradicen: miden poblaciones distintas. El 97.9 % corresponde a
mensajes **del estilo** de los publicados; el 68.4 % a mensajes **diseñados para romper el sistema**, concentrados en
rectificaciones entre mensajes, que fue justamente el fenómeno que fallaba (4 de los 6 errores; los otros 2 fueron "1 sobre" y el tope de cantidad). La estimación
honesta para los mensajes no publicados del docente es **alta para pedidos típicos, menor en casos límite**, con
intervalos amplios por el tamaño de los conjuntos. Las revisiones adversariales de los incisos 4 y 6 (537 menciones y
267 solicitudes) y la auditoría externa encontraron fallas en fenómenos que no estaban en ningún caso. Con mensajes
realmente nuevos es esperable una tasa de error mayor que el 100 % dentro de la muestra.

Para **comparar alternativas**, en cambio, todas se midieron sobre los mismos 139 casos: la comparación es
justa entre ellas, y en este conjunto la calidad no distingue a haiku, luna y sonnet; por eso decidieron costo,
latencia y operación.

### Latencia: evaluación vs. servicio

Las latencias de la tabla incluyen la exportación **síncrona** de trazas de la evaluación y 2–4 solicitudes en
paralelo. La latencia del **servicio en Docker**, medida por HTTP (`evidencia/docker/prueba_http.json`), es
menor: **p50 1.3 s, p95 1.9 s** (máx. 2.5 s) sobre los 139 casos; los 20 mensajes inéditos, p95 1.4 s.

**Trazas durante la caída de MLflow (medido).** En esa prueba HTTP, MLflow estuvo detenido 30 s de los 46 s de la
corrida. Las 139 solicitudes respondieron 200 y `/health` reportó `degradado` a los 2.5 s. En el MLflow del compose
quedaron 32 trazas de pedidos (las atendidas antes de la caída), las 7 de los rechazos 422 y la del 404. Las ~100
solicitudes atendidas con MLflow caído no dejaron traza: es el costo aceptado del diseño (DECISIONES D16), porque
la alternativa sería que las solicitudes esperaran a MLflow.

## 4. Hallazgos operativos (también son evidencia)

| Hallazgo | Consecuencia en el producto |
|---|---|
| `claude-sonnet-5.5` rechaza `function_calling` (no admite `tool_choice` forzado) | El extractor prueba el otro método de salida estructurada automáticamente |
| `gpt-6-luna` y `claude-sonnet-5.5`: **20 solicitudes/minuto** en cuentas nuevas (429) | Riesgo para un modelo principal bajo la carga de la evaluación |
| Un caso propio (PA11, "72 jaboncitos rosa **sueltos**") reveló que "sueltos" no se reconocía como unidad suelta | Corregido; sin casos propios habría pasado inadvertido |
| Un caso propio (PB05, "de **naranjita** mejor 4") reveló que una corrección ambigua no usaba el contexto | Corregido: correcciones/exclusiones se resuelven con lo ya pedido |
| La auditoría externa (N04–N08, N15) mostró que una rectificación dejaba el pendiente de la mención anterior, que "1 sobre" se cobraba como display y que 10 001 fardos no se calculaban | Corregidos con pruebas y 7 casos de regresión; la primera versión de la corrección tenía 3 regresiones que encontró la revisión adversarial antes de evaluar (D20) |

## 5. Evidencia en MLflow (capturas en `evidencia/mlflow/`)

| Captura | Qué muestra |
|---|---|
| `trazas_lista.jpg` | Trazas de solicitudes reales (experimento `novapedidos`): entrada, salida, duración, estado y tokens |
| `trazas_lista_version_final.jpg` | Trazas de la versión final en el MLflow del `docker compose`: un pedido con rectificación (`confirmado`) y una traza `solicitud_rechazada` (422) arriba de las anteriores |
| `traza_detalle_rectificacion.jpg` | Detalle de esa traza: entrada con 3 mensajes ("ah no, el aceite ya no"), salida `confirmado` B01×2 + B11×4 y el árbol de spans |
| `traza_resolucion_rectificacion.jpg` | Span `resolucion` de esa traza: las menciones que extrajo el modelo, incluida la de `accion: quitar` del aceite |
| `traza_detalle_ejemplo_anexo.jpg` | Árbol de spans del ejemplo del Anexo: `interpretar_pedido` → `extraccion` → `ChatOpenAI` (1.8 s, ~US$0.0006) → `resolucion` → `motor_reglas` |
| `comparacion_post_auditoria.jpg` | `pedido_exacto` de los 7 runs de la comparación final (139 casos, filtro `tags.comparacion = 'post-auditoria-139'`) |
| `comparacion_pedido_exacto.jpg` | Lo mismo para la comparación de la entrega inicial (132 casos; hoy `tags.comparacion = 'entrega-inicial-132'`) |
| `evaluaciones_historial.jpg` | Historial de **todas** las evaluaciones del experimento `novapedidos-evaluacion`. Las caídas a 0 % y 28.8 % son intentos **descartados** de Sonnet (incompatibilidad de método y límite de 20 solicitudes/min) antes de corregirlos; se conservan como historial. Los resultados publicados son los runs con la etiqueta `comparacion_final` |

Capturas de funcionamiento (`evidencia/funcionamiento/`): `swagger_pedido_rectificado.jpg` (la misma solicitud
desde la documentación interactiva `/docs` del contenedor: 200 con el pedido completo y el mensaje al cliente) y
`health_degradado_mlflow_detenido.png` (`GET /health` con el contenedor de MLflow detenido: `degradado` con el
motivo; en ese momento un POST siguió respondiendo 200 y, al levantar MLflow, `/health` volvió a `ok` solo).

Las evaluaciones se ejecutaron contra un MLflow local de desarrollo. El MLflow del `docker compose` arranca vacío:
el experimento `novapedidos-evaluacion` aparece al correr `ejecutar` o `comparar` (ver README).

## 6. Decisión

- **Modelo principal: `anthropic/claude-haiku-5.5`** — 100 % en dos corridas (y en las dos de la entrega inicial),
  sin límite de solicitudes observado con 4 en paralelo, p95 de 3.5–4.4 s en evaluación y 1.9 s en el servicio,
  US$0.61 por 1 000 pedidos.
- **Modelo de respaldo: `openai/gpt-6-luna`** — 100 %, el más rápido y barato, **de otro proveedor** (si Anthropic
  falla o limita, responde OpenAI). No es el principal solo por su límite de 20 solicitudes/min en cuentas nuevas:
  con una cuenta establecida sería la opción óptima en costo (5.8× más barato) y latencia.
- **Estrategia: híbrida.** Empata con la determinista en este conjunto, pero agrega el respaldo del LLM para jerga
  que el vocabulario no cubre y detecta discrepancias LLM/código. La estrategia "solo LLM" falló 3 casos que la
  híbrida acertó (y ninguno al revés). Con 139 casos esa diferencia sola no es estadísticamente significativa
  (McNemar exacto, p = 0.25), pero se repitió en las dos comparaciones (129/132 y 136/139) y los 3 errores son
  justo el tipo que la arquitectura quiere evitar: el modelo elige un producto cuando el mensaje es ambiguo.
- **Sonnet descartado**: misma calidad a 20× el costo de haiku.
