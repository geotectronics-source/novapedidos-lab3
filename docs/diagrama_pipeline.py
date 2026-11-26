"""Genera docs/diagrama_pipeline.png: pipeline completo de NovaPedidos (solicitud, trazas y evaluación).

    uv run python docs/diagrama_pipeline.py

Se dibuja con matplotlib (ya es dependencia del proyecto) para que sea reproducible sin herramientas externas.
Las cifras del pie corresponden a la evaluación final (evidencia/comparacion/ANALISIS.md).
"""

# ruff: noqa: E501  (textos del diagrama: cada línea es una línea dibujada)
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch  # noqa: E402

DESTINO = Path(__file__).resolve().parent / "diagrama_pipeline.png"

FONDO, TINTA, GRIS, TENUE, BLANCO, BORDE = "#F5F7FA", "#14243A", "#4A5568", "#718096", "#FFFFFF", "#D5DCE5"
AZUL, MORADO, VERDE, TEAL, NARANJA, ROJO = "#2B6CB0", "#6B46C1", "#2F855A", "#2C7A7B", "#C05621", "#C53030"

W = 24.0
TITULO, LINEA, CHIPS, PIE = 0.95, 0.31, 0.6, 0.18  # alturas (pulgadas)
SEP = 0.34  # separación vertical entre tarjetas


@dataclass
class Tarjeta:
    color: str
    titulo: str
    lineas: list[str]
    etiqueta: str = ""
    chips: list[tuple[str, str]] = field(default_factory=list)
    fondo: str = BLANCO

    @property
    def alto(self) -> float:
        return TITULO + LINEA * len(self.lineas) + (CHIPS if self.chips else PIE)


class Lienzo:
    def __init__(self, alto: float) -> None:
        self.H = alto
        self.fig = plt.figure(figsize=(W, alto), dpi=110)
        self.ax = self.fig.add_axes([0, 0, 1, 1])
        self.ax.set_xlim(0, W)
        self.ax.set_ylim(0, alto)
        self.ax.axis("off")
        self.fig.patch.set_facecolor(FONDO)
        self.renderer = self.fig.canvas.get_renderer()

    def ancho(self, artista) -> float:
        caja = artista.get_window_extent(renderer=self.renderer)
        return caja.width / self.fig.dpi

    def tarjeta(self, x: float, y_sup: float, w: float, t: Tarjeta) -> tuple[float, float, float, float]:
        """Dibuja la tarjeta con su borde superior en y_sup; devuelve (x, y, w, h)."""
        ax, h = self.ax, t.alto
        y = y_sup - h
        ax.add_patch(
            FancyBboxPatch(
                (x, y),
                w,
                h,
                boxstyle="round,pad=0,rounding_size=0.12",
                facecolor=t.fondo,
                edgecolor=BORDE,
                linewidth=1.2,
                zorder=2,
            )
        )
        ax.add_patch(
            FancyBboxPatch(
                (x + 0.2, y_sup - 0.72), 0.08, 0.44, boxstyle="square,pad=0", color=t.color, zorder=3
            )
        )
        ax.text(
            x + 0.45,
            y_sup - 0.5,
            t.titulo,
            fontsize=15,
            fontweight="bold",
            color=TINTA,
            va="center",
            zorder=3,
        )
        if t.etiqueta:
            ax.text(
                x + w - 0.25,
                y_sup - 0.5,
                t.etiqueta,
                fontsize=10.5,
                family="monospace",
                color=t.color,
                ha="right",
                va="center",
                zorder=3,
                bbox={"boxstyle": "round,pad=0.35", "facecolor": t.color + "18", "edgecolor": "none"},
            )
        yy = y_sup - TITULO + 0.08
        for linea in t.lineas:
            ax.text(x + 0.45, yy, linea, fontsize=11.3, color=GRIS, va="top", zorder=3)
            yy -= LINEA
        cx = x + 0.45
        for texto, c in t.chips:
            art = ax.text(
                cx,
                y + 0.32,
                texto,
                fontsize=10.2,
                color=c,
                fontweight="bold",
                va="center",
                zorder=3,
                bbox={"boxstyle": "round,pad=0.32", "facecolor": c + "1F", "edgecolor": "none"},
            )
            cx += self.ancho(art) + 0.35
        return x, y, w, h

    def flecha(self, a, b, color=TENUE, estilo="-", ancho=1.8, conn="arc3"):
        self.ax.add_patch(
            FancyArrowPatch(
                a,
                b,
                arrowstyle="-|>",
                mutation_scale=16,
                color=color,
                linewidth=ancho,
                linestyle=estilo,
                connectionstyle=conn,
                zorder=1,
            )
        )


PASOS = [
    Tarjeta(
        AZUL,
        "1 · Solicitud del cliente (mensajes de WhatsApp)",
        [
            '{ "cliente_id": "C001", "fecha_hora": "2026-11-23T15:20", "mensajes": ["Buenas, mándeme…", "…"] }',
        ],
        "JSON",
    ),
    Tarjeta(
        AZUL,
        "2 · Validación en FastAPI, antes de llamar al modelo",
        [
            "Campos y tipos, fecha AAAA-MM-DDTHH:MM, lista no vacía, ≤ 20 mensajes, cuerpo JSON en UTF-8.",
            "El cliente se busca en el catálogo antes de gastar tokens.",
        ],
        "api/",
        [
            ("422 · detalle en español", ROJO),
            ("404 · cliente inexistente", ROJO),
            ("traza: solicitud_rechazada", TEAL),
        ],
    ),
    Tarjeta(
        MORADO,
        "3 · Extracción con LangChain + OpenRouter",
        [
            'Salida estructurada (Pydantic): es_pedido, "lo de siempre" y menciones con texto, producto,',
            "cantidad, unidad y acción (agregar · corregir · quitar). El esquema no tiene precios ni totales.",
            "Mensajes delimitados como datos · claude-haiku-5.5, respaldo gpt-6-luna, reintentos.",
        ],
        "llm/",
        [("503 · modelo no disponible", ROJO), ("defensa ante inyección", MORADO)],
    ),
    Tarjeta(
        NARANJA,
        "4 · El código valida lo que extrajo el LLM",
        [
            'Unidad desde el texto literal (latas, sobres, "1 sobre", docenas). Fracciones, 0 o cantidades',
            "absurdas → cantidad_no_convertible. Una corrección o exclusión reemplaza lo pedido antes.",
        ],
        "servicio.py",
    ),
    Tarjeta(
        TEAL,
        "5 · Resolución híbrida a SKU",
        [
            "Sinónimos, fonética, diminutivos, distancia de edición, medidas y contexto del pedido.",
            "Ante la duda no adivina: ÚNICO → SKU · AMBIGUO / NO EXISTE → pendiente para revisión.",
        ],
        "resolucion/",
    ),
    Tarjeta(
        VERDE,
        "6 · Motor de reglas del negocio",
        [
            '"Lo de siempre" = último pedido entregado · consolidación y conversión exacta de unidades.',
            "Agotados → sustituto o pendiente · precios con Decimal · descuento por escala de cantidad.",
            "Crédito: saldo + total > límite → revisión · corte 14:00 · primer día de visita posterior.",
        ],
        "dominio/",
        [("cálculo determinista y probado", VERDE)],
    ),
    Tarjeta(
        VERDE,
        "7 · Confirmación al cliente",
        [
            "Mensaje breve y cordial que sale de una plantilla con el pedido calculado (no lo redacta el LLM).",
        ],
        "plantilla",
    ),
    Tarjeta(
        VERDE,
        "Respuesta HTTP 200 · contrato del Anexo",
        [
            "líneas · total · fecha_entrega · sustituciones · pendientes · motivos_revision · mensaje_cliente",
        ],
        "",
        [("confirmado", VERDE), ("requiere_revision", NARANJA), ("fuera_de_alcance", AZUL)],
        "#E6F4EA",
    ),
]

DERECHA = [
    Tarjeta(
        MORADO,
        "Datos del curso",
        [
            "lab3/ montado como volumen de solo lectura",
            "(fuera del repositorio y de la imagen):",
            "catálogo, sinónimos, escalas de descuento,",
            "clientes, historial y politicas.md.",
        ],
        "volumen :ro",
    ),
    Tarjeta(
        TEAL,
        "Observabilidad · MLflow",
        [
            "Una traza por solicitud: extraccion → ChatOpenAI",
            "→ resolucion → motor_reglas, con tokens, costo,",
            "latencia, estado, modelo y versión del prompt.",
            "Exportación asíncrona: si MLflow cae, la API",
            "sigue respondiendo.",
            "GET /health → ok | degradado + motivo",
            "(datos · mlflow · trazas · llm).",
        ],
        "puerto 5000",
    ),
    Tarjeta(
        AZUL,
        "Evaluación reproducible",
        [
            "84 casos publicados + 55 propios = 139.",
            "mlflow.genai.evaluate con 14 scorers por código",
            "(pedido_exacto es la métrica principal).",
            "7 configuraciones (modelos × estrategias) en",
            "calidad, latencia y costo → evidencia/.",
            "probar_http.py: punta a punta por HTTP.",
            "431 pruebas pytest que no llaman al modelo.",
        ],
        "evaluacion/",
    ),
    Tarjeta(
        GRIS,
        "Despliegue · docker compose up",
        [
            "api :8000 · uv, usuario sin privilegios, healthcheck",
            "mlflow :5000 · volumen persistente",
            "Clave de OpenRouter por env_file (.env).",
        ],
        "Docker",
    ),
]


def main() -> None:
    cuerpo = sum(t.alto for t in PASOS) + SEP * (len(PASOS) - 1)
    H = 1.6 + 1.0 + cuerpo + 1.05  # encabezado + subtítulos + tarjetas + pie
    lz = Lienzo(H)
    ax = lz.ax

    ax.add_patch(FancyBboxPatch((0, H - 1.6), W, 1.6, boxstyle="square,pad=0", color=TINTA, zorder=1))
    ax.add_patch(FancyBboxPatch((0, H - 1.66), W, 0.06, boxstyle="square,pad=0", color="#38B2AC", zorder=1))
    ax.text(
        0.6, H - 0.62, "Pipeline de NovaPedidos", fontsize=30, fontweight="bold", color=BLANCO, va="center"
    )
    ax.text(
        0.62,
        H - 1.18,
        "De mensajes de WhatsApp a un pedido verificable: el LLM extrae, el código calcula y decide",
        fontsize=14,
        color="#CBD5E0",
        va="center",
    )
    ax.text(
        W - 0.6,
        H - 0.82,
        "tag entrega-lab3 · versión final",
        fontsize=12,
        family="monospace",
        color="#E2E8F0",
        ha="right",
        va="center",
        bbox={"boxstyle": "round,pad=0.5", "facecolor": "#2D3E55", "edgecolor": "none"},
    )

    y0 = H - 2.6
    ax.text(
        0.6,
        y0 + 0.42,
        "Flujo de una solicitud · POST /v1/pedidos/interpretar",
        fontsize=15,
        fontweight="bold",
        color=TINTA,
        va="center",
    )
    RX, RW, X, A = 15.6, 7.8, 0.6, 13.4
    BUS_TRAZAS, BUS_DATOS = 14.5, 15.05  # buses verticales en el pasillo entre columnas
    ax.text(
        RX,
        y0 + 0.42,
        "Datos, observabilidad, evaluación y despliegue",
        fontsize=15,
        fontweight="bold",
        color=TINTA,
        va="center",
    )

    cajas, y = [], y0
    for i, t in enumerate(PASOS):
        cajas.append(lz.tarjeta(X, y, A, t))
        y -= t.alto
        if i < len(PASOS) - 1:
            lz.flecha((X + A / 2, y - 0.02), (X + A / 2, y - SEP + 0.02))
            y -= SEP
    y_final = y

    # Columna derecha: misma altura total que la izquierda, sobrante repartido entre tarjetas
    hueco = (y0 - y_final - sum(t.alto for t in DERECHA)) / (len(DERECHA) - 1)
    der, y = [], y0
    for t in DERECHA:
        der.append(lz.tarjeta(RX, y, RW, t))
        y -= t.alto + hueco
    datos, mlflow, evaluacion, _ = der

    def y_en(c, f):
        return c[1] + c[3] * f

    # Trazas (teal): extracción, resolución, motor y rechazos -> bus -> MLflow
    origenes = [y_en(c, 0.32) for c in (cajas[1], cajas[2], cajas[4], cajas[5])]
    y_ml = y_en(mlflow, 0.5)
    for yy in origenes:
        ax.plot([X + A + 0.04, BUS_TRAZAS], [yy, yy], color=TEAL, linestyle="--", linewidth=1.3, zorder=1)
    ax.plot(
        [BUS_TRAZAS, BUS_TRAZAS],
        [min(origenes + [y_ml]), max(origenes + [y_ml])],
        color=TEAL,
        linestyle="--",
        linewidth=1.3,
        zorder=1,
    )
    lz.flecha((BUS_TRAZAS, y_ml), (RX - 0.04, y_ml), TEAL, "--", 1.3)
    # Datos (morado): catálogo -> bus -> validación del cliente, resolución y motor
    destinos = [y_en(c, 0.68) for c in (cajas[1], cajas[4], cajas[5])]
    y_dt = y_en(datos, 0.5)
    ax.plot([RX - 0.04, BUS_DATOS], [y_dt, y_dt], color=MORADO, linestyle="--", linewidth=1.5, zorder=1)
    ax.plot(
        [BUS_DATOS, BUS_DATOS], [min(destinos), y_dt], color=MORADO, linestyle="--", linewidth=1.5, zorder=1
    )
    for yy in destinos:
        lz.flecha((BUS_DATOS, yy), (X + A + 0.04, yy), MORADO, "--", 1.5)
    # Evaluación → MLflow (runs y trazas de evaluación)
    lz.flecha(
        (RX + RW / 2, evaluacion[1] + evaluacion[3] + 0.03), (RX + RW / 2, mlflow[1] - 0.03), AZUL, "--", 1.6
    )
    ax.text(
        RX + RW / 2 + 0.15,
        (evaluacion[1] + evaluacion[3] + mlflow[1]) / 2,
        "runs y trazas de evaluación",
        fontsize=10,
        color=AZUL,
        va="center",
    )

    ax.plot([0.6, W - 0.6], [0.95, 0.95], color=BORDE, linewidth=1)
    ax.text(
        0.6,
        0.48,
        "Resultados finales:  139/139 pedidos exactos (haiku-5.5 · híbrida, 2 corridas)  ·  HTTP en "
        "Docker 139/139, p95 1.9 s  ·  US$0.61 por 1 000 pedidos  ·  inéditos de la auditoría 19/19",
        fontsize=11.5,
        color=TINTA,
        va="center",
    )
    for i, (texto, c, est) in enumerate(
        [("flujo", TENUE, "-"), ("datos", MORADO, "--"), ("trazas", TEAL, "--")]
    ):
        x0 = W - 5.4 + i * 1.75
        ax.plot([x0, x0 + 0.55], [0.48, 0.48], color=c, linestyle=est, linewidth=2)
        ax.text(x0 + 0.7, 0.48, texto, fontsize=11, color=GRIS, va="center")

    lz.fig.savefig(DESTINO, dpi=110, facecolor=FONDO)
    print(f"Diagrama -> {DESTINO.relative_to(DESTINO.parents[1])}")


if __name__ == "__main__":
    main()
