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

<!-- Pendientes: modelo elegido (Inciso 8), estrategia de resolución de productos (Inciso 4),
     tolerancia a fallas de MLflow (Inciso 7), técnica de calificación (Inciso 8). -->
