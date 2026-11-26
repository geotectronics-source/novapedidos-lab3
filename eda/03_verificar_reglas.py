# /// script
# requires-python = ">=3.12"
# dependencies = ["pandas", "pyarrow"]
# ///
"""Inciso 1 - ¿Entendimos bien las políticas?

Toma las líneas esperadas (sku, cantidad) de cada caso de desarrollo y vuelve a
calcular con código: precio, descuento, subtotal, total, crédito y fecha de entrega.
Si todo coincide con las respuestas esperadas, nuestra lectura de politicas.md es correcta
y la podremos programar en el Inciso 3.

También revisa las hipótesis que el texto de las políticas deja abiertas:
  H1  fecha de entrega: ¿la visita debe ser ESTRICTAMENTE posterior a la fecha efectiva?
  H2  crédito: ¿"supera" significa  saldo + total > límite  (o >=)?
  H3  "lo de siempre": ¿último pedido 'entregado' (por fecha) antes de la solicitud?

Uso:  uv run --script eda/03_verificar_reglas.py
"""

import json
from collections import Counter
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import pandas as pd

RAIZ = Path(__file__).resolve().parent.parent / "lab3"
productos = pd.read_parquet(RAIZ / "datos/productos.parquet").set_index("sku")
escala = pd.read_parquet(RAIZ / "datos/precios_escala.parquet")
clientes = pd.read_parquet(RAIZ / "datos/clientes.parquet").set_index("cliente_id")
historial = pd.read_parquet(RAIZ / "datos/historial_pedidos.parquet")
casos = [
    json.loads(l)
    for l in (RAIZ / "ejemplos/mensajes_dev.jsonl").read_text(encoding="utf-8").splitlines()
    if l.strip()
]

DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]


def redondear(x: Decimal) -> Decimal:
    return x.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def descuento(categoria: str, cantidad: int) -> int:
    filas = escala[(escala.categoria == categoria) & (escala.cantidad_minima <= cantidad)]
    return int(filas.descuento_pct.max()) if len(filas) else 0


def fecha_entrega(cliente_id: str, fecha_hora: str, estricta: bool) -> date:
    recibido = datetime.fromisoformat(fecha_hora)
    efectiva = recibido.date() + timedelta(days=1 if recibido.hour >= 14 else 0)
    visitas = {DIAS.index(d) for d in clientes.loc[cliente_id, "dias_visita"].split(",")}
    d = efectiva + timedelta(days=1)  # siempre posterior a la fecha de RECEPCIÓN
    if not estricta and recibido.hour >= 14:  # variante: la fecha efectiva ya cuenta
        d = efectiva
    while d.weekday() not in visitas:
        d += timedelta(days=1)
    return d


errores = Counter()
fechas = Counter()
credito_bordes = []
for c in casos:
    e, ent = c["esperado"], c["entrada"]
    total = Decimal(0)
    for l in e["lineas"]:
        p = productos.loc[l["sku"]]
        assert bool(p.disponible), f"{c['id']}: línea con producto agotado {l['sku']}"
        pct = descuento(p.categoria, l["cantidad"])
        sub = redondear(Decimal(str(p.precio)) * l["cantidad"] * (1 - Decimal(pct) / 100))
        if float(p.precio) != l["precio_unitario"]:
            errores["precio"] += 1
            print("precio", c["id"], l)
        if pct != l["descuento_pct"]:
            errores["descuento"] += 1
            print("descuento", c["id"], l, pct)
        if float(sub) != l["subtotal"]:
            errores["subtotal"] += 1
            print("subtotal", c["id"], l, sub)
        total += sub
    if float(total) != e["total"]:
        errores["total"] += 1
        print("total", c["id"], total, e["total"])

    cli = clientes.loc[ent["cliente_id"]]
    saldo, limite = int(cli.saldo_pendiente), int(cli.limite_credito)
    excede = saldo + total > limite
    if excede != ("credito_excedido" in e["motivos_revision"]):
        errores["credito"] += 1
        print("credito", c["id"], saldo, total, limite)
    if abs(saldo + total - limite) < 300:
        credito_bordes.append((c["id"], float(saldo + total), limite, excede))

    if e["fecha_entrega"] is not None:
        for estricta in (True, False):
            ok = str(fecha_entrega(ent["cliente_id"], ent["fecha_hora"], estricta)) == e["fecha_entrega"]
            fechas[("H1 estricta" if estricta else "H1 no estricta", ok)] += 1

print("\n== Discrepancias en cálculos (0 = nuestra lectura coincide) ==", dict(errores) or "ninguna")
print("== Fecha de entrega (hipótesis, coincide?) ==", dict(fechas))
print("== Casos cerca del límite de crédito (id, saldo+total, límite, excede) ==", credito_bordes)

# ---------- H3: "lo de siempre"
print("\n== Historial ==")
print("estados:", historial.estado.value_counts().to_dict())
print("fechas de entrega:", historial.fecha_entrega.min().date(), "->", historial.fecha_entrega.max().date())
print("pedidos por cliente:", historial.groupby("cliente_id").pedido_id.nunique().describe().to_dict())

for c in casos:
    if c["tipo"] not in ("habitual", "varios_mensajes"):
        continue
    cid = c["entrada"]["cliente_id"]
    h = historial[(historial.cliente_id == cid) & (historial.estado == "entregado")]
    ultimo = h[h.fecha_entrega == h.fecha_entrega.max()]
    canc = historial[(historial.cliente_id == cid) & (historial.estado != "entregado")]
    print(
        f"\n{c['id']} {cid} recibido {c['entrada']['fecha_hora']} | {' || '.join(c['entrada']['mensajes'])}"
    )
    print(
        f"   último entregado {ultimo.pedido_id.iloc[0]} ({ultimo.fecha_entrega.iloc[0].date()}):",
        ", ".join(
            f"{r.sku}x{r.cantidad}{'' if productos.loc[r.sku].disponible else '(AGOTADO)'}"
            for r in ultimo.itertuples()
        ),
    )
    if len(canc):
        ult_c = canc[canc.fecha_entrega == canc.fecha_entrega.max()]
        print(
            f"   último NO entregado {ult_c.pedido_id.iloc[0]} ({ult_c.estado.iloc[0]}, {ult_c.fecha_entrega.iloc[0].date()}):",
            ", ".join(f"{r.sku}x{r.cantidad}" for r in ult_c.itertuples()),
        )
    e = c["esperado"]
    print(
        "   esperado:",
        ", ".join(f"{l['sku']}x{l['cantidad']}" for l in e["lineas"]),
        "| sust:",
        [(s["sku_solicitado"], s["sku_entregado"], s["cantidad"]) for s in e["sustituciones"]],
        "| pend:",
        [(p["motivo"], p["texto"], p["opciones"]) for p in e["pendientes"]],
    )
