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
uv run pytest
```

## Documentación

- [DECISIONES.md](DECISIONES.md): decisiones de diseño, alternativas y justificación.
- [CLAUDE.md](CLAUDE.md): contexto para agentes de programación.
- [eda/REPORTE_EDA.md](eda/REPORTE_EDA.md): exploración de datos y verificación de las reglas.
