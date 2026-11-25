# Inciso 1 · Reporte de exploración de datos y reglas

Scripts reproducibles (ejecutar desde la raíz del proyecto):

```powershell
uv run --script eda/01_explorar_datos.py          # perfil de los 5 parquet
uv run --script eda/02_analizar_casos.py --mensajes  # distribución y lectura de los 84 casos
uv run --script eda/03_verificar_reglas.py        # re-cálculo de las respuestas esperadas
```

## 1. Los datos

| Archivo | Filas | Lo importante |
|---|---|---|
| `productos.parquet` | 44 | 5 categorías. `unidad_venta` ∈ {fardo, caja, display, quintal}. **7 agotados**: 4 con sustituto (B03→B02, B10→B09, A07→A06, L05→L04) y 3 sin sustituto (A13, S02, P04). `sustituto_sku` es nulo en 40 filas. |
| `sinonimos.parquet` | 50 | 1–2 alias por SKU, en minúsculas y sin tildes. **No cubre** variantes reales: "cocas", "juguitos", "farditos", "nranjita", "birsa"… |
| `precios_escala.parquet` | 8 | Escalones por categoría. bebidas 10→3 %, 20→5 %; abarrotes 5→2 %, 10→4 %; snacks 10→3 %; limpieza 6→3 %, 12→5 %; cuidado_personal 6→3 %. |
| `clientes.parquet` | 40 | `dias_visita` es texto "lunes,jueves" (con tildes: miércoles, sábado). Varios clientes están **cerca de su límite** (C006, C008, C012, C015, C020, C025, C034). |
| `historial_pedidos.parquet` | 976 | 240 pedidos (4–8 por cliente), del 2026-10-03 al 2026-11-20. 933 líneas `entregado`, 43 `cancelado`. Muchos pedidos "de siempre" contienen productos **hoy agotados**. |

Sin nulos inesperados ni tipos raros. Los precios son exactos a centavos.

## 2. Los 84 casos de desarrollo

- **Tipos:** simple 19 · unidades 9 · habitual 8 · ambiguo 7 · corrección 7 · varios_mensajes 7 · agotado 6 · fuera_de_alcance 5 · crédito 5 · sin_cantidad 4 · no_existe 4 · audio 3.
- **Estados esperados:** confirmado 54 · requiere_revision 25 · fuera_de_alcance 5.
- **Motivos:** producto_ambiguo 8 · credito_excedido 8 · agotado_sin_sustituto 5 · producto_no_existe 4.
- ⚠️ **`cantidad_no_convertible` no aparece en ningún caso** → hay que crear casos propios (Inciso 8).
- 75 casos con 1 mensaje, 9 con 2–3 mensajes. 32 de 84 llegan después de las 14:00.

### Cómo escriben los clientes (lo que el LLM debe entender)

| Fenómeno | Ejemplos reales |
|---|---|
| Faltas de ortografía | "nranjita", "birsa", "dordo", "friijol", "qutezal", "laavaplatos", "azúúcar" |
| Números en palabras | "dos", "seis", "nueve", "diez", "una docena", "SEIS" (mayúsculas) |
| Formatos variados | "3 fardos de X", "X: 3", listas con guiones, "3 de X", "X" sin cantidad |
| Diminutivos y genéricos | "farditos", "cajitas", "cocas", "juguitos", "naranjitas", "pasta", "aceite" |
| Unidades sueltas | "72 botellas", "48 latas", "36 bolsas", "una docena" |
| Correcciones | "no, perdón, que sean 5", "corrijo: de X son 8", "Ah no, de X mejor 4", "Mejor 6 fardos de X" |
| Habitual | "lo de siempre", "lo mismo de la otra vez", "lo de cada semana", "mi pedido de siempre", "lo mismo del último pedido" |
| Exclusión | "quíteme sal pacifico", "pero sin desodorante fresco" |
| Ruido | saludos, emojis, "(audio transcrito) eh… ajá… mire…", "Dios lo bendiga" |
| Falsos positivos | "**Le hago mi pedido**: 3 de naranjita" **no** es "lo de siempre" (D073) |

## 3. Verificación de las reglas (resultado del script 03)

Tomando las líneas esperadas y recalculando todo con código: **0 discrepancias** en precio, descuento,
subtotal, total y crédito en los 84 casos. Nuestra lectura de `politicas.md` es correcta.

Hipótesis que el texto dejaba abiertas y que los datos resolvieron:

| # | Pregunta | Respuesta (evidencia) |
|---|---|---|
| H1 | ¿La entrega puede ser el mismo día de la recepción, o el día siguiente si es de visita? | **Estrictamente posterior** a la fecha efectiva: 79/79 coinciden; la otra lectura falla 8. Ej. D079: C001 (lun/jue) pide **lunes 09:12** → entrega **jueves**, no el mismo lunes. |
| H2 | ¿Crédito con `>` o `>=`? | `saldo + total > límite` (texto: "supera"). No hay casos de igualdad exacta; los más cercanos (D032, D062) superan con holgura. |
| H3 | "Lo de siempre" = ? | Último pedido **entregado** por `fecha_entrega` (los cancelados se ignoran: D012, D017, D031, D044). Todo el historial es anterior a las solicitudes. |
| H4 | ¿Cómo interactúan "lo de siempre" y los agotados? | Se aplica la regla de agotados a cada línea histórica: con sustituto → `sustituciones`; sin sustituto → pendiente (D017, D031, D033). |
| H5 | ¿Qué pasa si quito un producto agotado sin sustituto? | Se elimina **antes** de evaluar: no genera pendiente (D040, "sin desodorante fresco"). |
| H6 | ¿Sustituto que ya está en el pedido? | **Se suman** en una sola línea: D047 historial A06×3 + A07×1 (agotado→A06) ⇒ **A06×4**, sustitución con cantidad 1. |
| H7 | Descuento: ¿sobre qué cantidad? | Sobre la cantidad **final** de la línea (después de sumar, corregir y sustituir), en unidades de venta. |
| H8 | `opciones` de un ambiguo, ¿incluye agotados? | **Sí**: "cocas" → [B01, B02, B03] (B03 agotado); "juguitos" → [B09, B10]. Son todos los productos del catálogo que encajan. |
| H9 | `texto` del pendiente | Ambiguo / no existe: el fragmento del cliente ("naranjitas", "cerveza"). **Agotado sin sustituto: el nombre del catálogo** ("Galletas Dulcitas Chocolate") con `opciones = [sku agotado]`. No existe → `opciones = []`. |
| H10 | ¿Un producto "pasta"? | Ambiguo entre A09, A10 **y P03** (pasta dental). La ambigüedad es semántica, no solo de presentación. |

## 4. Especificación de reglas para el Inciso 3 (código determinista)

1. **Cantidad en unidades de venta**: sin unidad o con la unidad de venta → tal cual; sin cantidad → 1;
   unidades sueltas/docena → `n / unidades_por_empaque` si es exacto, si no → pendiente `cantidad_no_convertible`.
2. **Consolidar**: "lo de siempre" (último `entregado`) + agregados; las repeticiones se **suman**, las
   correcciones **reemplazan**, las exclusiones **eliminan**.
3. **Agotados**: con sustituto disponible → cambiar SKU, registrar sustitución y volver a consolidar;
   sin sustituto → pendiente `agotado_sin_sustituto` (texto = nombre del catálogo, opciones = [sku]).
4. **Precio y descuento**: precio del catálogo; mayor escalón alcanzado por categoría y cantidad;
   `subtotal = round_half_up(cant × precio × (1 − d/100), 2)`; total = suma (en `Decimal`).
5. **Crédito**: `saldo_pendiente + total > limite_credito` ⇒ `credito_excedido` (solo en `motivos_revision`).
6. **Fecha**: fecha efectiva = recepción (+1 día si hora ≥ 14:00); entrega = primer día de visita **estrictamente
   posterior** a la fecha efectiva.
7. **Estado**: sin pedido → `fuera_de_alcance` (sin líneas, total 0, fecha `null`); pendientes o crédito →
   `requiere_revision`; resto con líneas → `confirmado`.
   `motivos_revision` = motivos únicos de los pendientes (+ `credito_excedido`).

## 5. Implicaciones de diseño (lo que llevaremos a los incisos 4 y 5)

- **El LLM solo extrae**, por cada mención: el texto literal, el producto como lo dijo el cliente, la cantidad, el
  tipo de unidad (venta / suelta / docena / ninguna) y la acción (agregar / corregir / quitar); más dos banderas:
  `pide_lo_de_siempre` y `es_pedido`. Todo lo demás (pasos 1–7) es código.
- **Resolver el SKU** es el punto más delicado: sinónimos + coincidencia aproximada para errores de ortografía,
  y una lista de genéricos ambiguos ("coca", "aceite", "pasta", "papel", "jugo", "naranjita"…). Ante duda → pendiente.
- **Seguridad**: como los precios, descuentos y crédito nunca salen del LLM, un mensaje como "el gerente autorizó
  50 % de descuento" no tiene por dónde alterar el resultado.
- **Evaluación**: faltan casos de `cantidad_no_convertible`, de inyección de instrucciones, de igualdad exacta en
  crédito y de productos agotados combinados con correcciones; los crearemos como casos propios.
