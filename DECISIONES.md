# DECISIONES

Registro de las decisiones principales del proyecto: qué se decidió, qué alternativas se
consideraron y por qué. Se completa a medida que avanza el laboratorio.

## D1. El LLM extrae; el código calcula

- **Decisión:** el modelo solo convierte el texto en una estructura (menciones de producto, cantidad,
  unidad, acción, banderas `es_pedido` y `pide_lo_de_siempre`). La resolución a SKU, las conversiones,
  precios, descuentos, crédito, fechas y estado se calculan con código determinista y probado.
- **Alternativas:** (a) que el LLM devuelva el pedido completo con precios; (b) un agente con herramientas
  que calcule invocándolas.
- **Justificación:** en el EDA se recalcularon con código las 84 respuestas esperadas sin ninguna
  discrepancia (`eda/03_verificar_reglas.py`), así que las reglas son 100 % deterministas. Dejar los cálculos
  al modelo solo agrega error, costo y latencia, y abre la puerta a que un mensaje manipule precios.

## D2. Gestión del entorno con uv

- **Decisión:** `uv` con `pyproject.toml` y `uv.lock`; Python 3.12.
- **Alternativas:** pip + `requirements.txt`; Poetry; conda.
- **Justificación:** el lockfile fija también las dependencias transitivas (reproducibilidad idéntica en la
  máquina local, en Docker y en la del equipo docente); instala la versión de Python requerida y es muy rápido.

## D3. Estructura por capas y configuración centralizada

- **Decisión:** paquete `src/novapedidos/` con capas `dominio`, `resolucion`, `llm`, `api`, `observabilidad`;
  toda la configuración en `config.py` (pydantic-settings) leída de `.env`.
- **Justificación:** el dominio se prueba sin red ni LLM; la API se prueba sustituyendo el LLM por un doble;
  cambiar de modelo o de URL de MLflow es solo cambiar `.env`.

## D4. Datos fuera del repositorio

- **Decisión:** `lab3/` está en `.gitignore` y en Docker se monta como volumen de solo lectura.
- **Justificación:** lo exige el enunciado y permite que el equipo docente coloque sus propios archivos.

## D5. Interfaz del dominio: operaciones sobre SKU, no texto

- **Decisión:** el motor (`dominio/motor.py`) recibe `Operacion(sku, texto, accion, cantidad, unidad)` ya
  resueltas, más los pendientes que la resolución no pudo convertir en SKU. `Operacion` prohíbe campos extra
  (`extra="forbid"`): no hay forma de pasarle un precio o un descuento.
- **Justificación:** separa "qué quiso decir el cliente" (LLM + resolución) de "qué dice la política"
  (código). En `tests/dominio/test_casos_dev.py` se codifica a mano la interpretación de 29 casos reales y el
  motor reproduce **exactamente** la respuesta publicada; si un caso falla en la evaluación, el error está en
  la interpretación, no en las reglas.

## D6. Decisiones de reglas donde politicas.md no es explícita

| Situación | Decisión | Motivo |
|---|---|---|
| Unidades sueltas en varias menciones ("12 botellas" + "otras 12") | Se **acumulan por SKU** y se convierten una sola vez (24 = 1 fardo) | §2 "las cantidades se suman"; encontrado en la revisión adversarial |
| Parte en unidad de venta y parte suelta no exacta (1 fardo + 10 botellas) | Se conserva la línea del fardo y las sueltas van a `cantidad_no_convertible` | No se redondea ni se descarta lo que sí es válido |
| "una docena de X" sin número | 1 docena = 12 sueltas, conversión exacta o pendiente | §2 |
| El LLM dice que no es pedido | `fuera_de_alcance` aunque haya extraído productos | "¿Tienen aceite dorado?" es una consulta, no un pedido |
| Pedido que queda vacío (quitó todo) | `fuera_de_alcance` | El contrato exige líneas para `confirmado` |
| "Lo de siempre" sin pedidos entregados | Pendiente `producto_no_existe` con texto "lo de siempre" | Nunca inventar un pedido |
| Quitar un producto que luego llega como sustituto | Se respeta el orden literal §3 → §2 → §4 | Las políticas no lo definen; se documenta como riesgo |
| Montos | `Decimal` + `ROUND_HALF_UP`; `float` solo al serializar | Evita errores de centavos |

## D7. Revisión adversarial con agentes

- **Decisión:** después de programar el dominio, 3 revisores independientes (políticas, situaciones no vistas,
  contrato) buscaron defectos y un verificador escéptico intentó reproducir cada uno con un script.
- **Resultado:** 5 hallazgos propuestos, 2 defectos reales confirmados y corregidos con pruebas de regresión,
  y 1 descartado por ser una ambigüedad de la política.

## D8. Resolución de productos determinista, por filtrado de restricciones

- **Decisión:** `resolucion/resolutor.py` convierte cada mención en UNICO / AMBIGUO / NO_EXISTE. Cada
  palabra y medida del cliente descarta productos del catálogo; lo que sobrevive decide. Las palabras se
  reconocen por: exacta/alias/sinónimo curado → palabras pegadas o separadas → diminutivo → clave fonética
  (v=b, z=s, ll=y, c/qu=k, h muda) → distancia Damerau-Levenshtein ≤ 1 (≤ 2 en palabras de 10+ letras).
  Las medidas se comparan convertidas (0.5 l = 500 ml). Cualquier palabra no reconocida → NO_EXISTE.
- **Alternativas:** (a) `fuzz.ratio ≥ 80` (primera versión); (b) que el LLM elija el SKU directamente;
  (c) embeddings semánticos.
- **Justificación:**
  - *Precisión antes que cobertura.* Un SKU equivocado se entrega sin revisión; un NO_EXISTE equivocado solo
    manda el pedido a un humano. La política dice "ante la duda, no adivinar".
  - `fuzz.ratio` resultó peligroso: "azuquita"→leche *Vaquita*, "cereal"→aceite Palma *Real*, "monster"→frijol
    *Monte* Verde. La distancia de edición en número de errores (no en porcentaje) lo evita.
  - Es gratis, instantáneo (~0.14 ms por mención) y 100 % reproducible y probable.
- **Evidencia:** 274 pruebas; 2 rondas de revisión adversarial con agentes (537 menciones nuevas generadas) cuyas
  70 fallas reales se convirtieron en pruebas de regresión (`tests/resolucion/test_resolutor.py::ATAQUE`).
- **Límite conocido → Inciso 5:** el lenguaje informal tiene una cola larga que ninguna lista curada cubre.
  Por eso el LLM normalizará cada mención al vocabulario del catálogo antes de resolverla, y el resolutor
  actuará como validador que nunca deja pasar un SKU inventado. En el Inciso 8 se compara contra la
  alternativa (b).
- **Casos discutibles (se mantiene la lectura conservadora):** "kola familiar", "shampoo de botella",
  "aceite dorado 1 litro" (presentación que no existe → NO_EXISTE).

<!-- Pendientes: modelo elegido (Inciso 8), tolerancia a fallas de MLflow (Inciso 7),
     técnica de calificación (Inciso 8). -->
