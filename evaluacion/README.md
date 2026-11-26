# Evaluación

| Archivo | Qué es |
|---|---|
| `casos_propios.jsonl` | **55 casos de evaluación propios** (48 de la entrega inicial + 7 de regresión de la auditoría externa, PE01–PE07), en el mismo formato que `lab3/ejemplos/mensajes_dev.jsonl` (`id`, `tipo`, `entrada`, `esperado`). Generado: no se edita a mano. |
| `casos_propios_fuente.json` | La fuente de esos casos: mensaje + **interpretación** según `politicas.md` (operaciones y pendientes) + descripción de qué prueba cada uno. |
| `construir_casos_propios.py` | Calcula la respuesta esperada de cada caso a partir de su interpretación con el motor de reglas (verificado contra los 84 casos publicados) y escribe el `.jsonl`. |
| `probar_http.py` | Prueba de punta a punta **por HTTP** contra el servicio levantado: casos, solicitudes inválidas y caída de MLflow. |

Los *scorers* y la evaluación en MLflow están en el paquete: `src/novapedidos/evaluacion/`
(`comparacion.py` funciones puras, `scorers.py` `@scorer`, `ejecutar.py` una configuración, `comparar.py` la
comparación de alternativas).

```powershell
uv run python evaluacion/construir_casos_propios.py                 # regenerar casos_propios.jsonl
uv run python evaluacion/probar_http.py --interrumpir-mlflow         # con docker compose up
uv run python -m novapedidos.evaluacion.ejecutar --conjunto todos   # evaluación en MLflow
uv run python -m novapedidos.evaluacion.comparar                    # comparación de alternativas
```

Las respuestas esperadas de los casos propios fueron verificadas por revisores independientes que recalcularon
cada caso desde los datos sin ver la interpretación: 48/48 en la entrega inicial y 7/7 en los casos de regresión
PE01–PE07. Resultados: `evidencia/comparacion/`.
