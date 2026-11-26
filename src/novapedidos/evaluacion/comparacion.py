"""Comparación de una respuesta obtenida contra la esperada (funciones puras, sin MLflow).

Cada criterio corresponde a lo que el enunciado dice que se evaluará: "que el estado, las líneas, el
total, la fecha de entrega y los motivos de revisión sean correctos". El `texto` de los pendientes se
ignora (es libre: "naranjitas" o "una caja de aceite" son igual de válidos); sí se comparan motivo y opciones.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

MOTIVOS_VALIDOS = {
    "producto_ambiguo", "producto_no_existe", "agotado_sin_sustituto", "cantidad_no_convertible", "credito_excedido",
}  # fmt: skip
CLAVES_CONTRATO = {
    "cliente_id", "estado", "lineas", "total", "fecha_entrega", "sustituciones",
    "pendientes", "motivos_revision", "mensaje_cliente",
}  # fmt: skip


ESTADOS_VALIDOS = {"confirmado", "requiere_revision", "fuera_de_alcance"}
CLAVES_LINEA = {"sku", "cantidad", "precio_unitario", "descuento_pct", "subtotal"}
_FECHA = re.compile(r"\d{4}-\d{2}-\d{2}")


def _es_numero(valor: Any) -> bool:
    return isinstance(valor, int | float) and not isinstance(valor, bool)


def _ok(obtenido: Any) -> bool:
    return isinstance(obtenido, dict) and "error" not in obtenido


def lineas_de(d: dict) -> Counter:
    return Counter((linea["sku"], linea["cantidad"]) for linea in d.get("lineas", []))


def estado_correcto(obtenido: dict, esperado: dict) -> bool:
    return _ok(obtenido) and obtenido.get("estado") == esperado["estado"]


def lineas_correctas(obtenido: dict, esperado: dict) -> bool:
    """Mismos SKU con las mismas cantidades (el orden no importa)."""
    return _ok(obtenido) and lineas_de(obtenido) == lineas_de(esperado)


def montos_correctos(obtenido: dict, esperado: dict) -> bool:
    """Precio, descuento y subtotal de cada línea, y el total (al centavo)."""
    if not _ok(obtenido) or abs(float(obtenido.get("total", -1)) - float(esperado["total"])) > 0.005:
        return False

    def montos(d: dict) -> set:
        return {
            (
                x["sku"],
                round(float(x["precio_unitario"]), 2),
                int(x["descuento_pct"]),
                round(float(x["subtotal"]), 2),
            )
            for x in d.get("lineas", [])
        }

    return montos(obtenido) == montos(esperado)


def total_correcto(obtenido: dict, esperado: dict) -> bool:
    return _ok(obtenido) and abs(float(obtenido.get("total", -1)) - float(esperado["total"])) <= 0.005


def fecha_correcta(obtenido: dict, esperado: dict) -> bool:
    return _ok(obtenido) and obtenido.get("fecha_entrega") == esperado["fecha_entrega"]


def motivos_correctos(obtenido: dict, esperado: dict) -> bool:
    return _ok(obtenido) and set(obtenido.get("motivos_revision", [])) == set(esperado["motivos_revision"])


def pendientes_correctos(obtenido: dict, esperado: dict) -> bool:
    """Mismos (motivo, opciones) — el texto libre se ignora."""

    def clave(d: dict) -> Counter:
        return Counter((p["motivo"], tuple(sorted(p.get("opciones", [])))) for p in d.get("pendientes", []))

    return _ok(obtenido) and clave(obtenido) == clave(esperado)


def sustituciones_correctas(obtenido: dict, esperado: dict) -> bool:
    def clave(d: dict) -> Counter:
        return Counter(
            (s["sku_solicitado"], s["sku_entregado"], s["cantidad"]) for s in d.get("sustituciones", [])
        )

    return _ok(obtenido) and clave(obtenido) == clave(esperado)


def pedido_exacto(obtenido: dict, esperado: dict) -> bool:
    """La métrica principal: TODO correcto a la vez."""
    return all(
        f(obtenido, esperado)
        for f in (
            estado_correcto, lineas_correctas, montos_correctos, fecha_correcta,
            motivos_correctos, pendientes_correctos, sustituciones_correctas,
        )
    )  # fmt: skip


def lineas_f1(obtenido: dict, esperado: dict) -> float:
    """Crédito parcial: F1 sobre (sku, cantidad). 1.0 si ambos no tienen líneas."""
    if not _ok(obtenido):
        return 0.0
    o, e = lineas_de(obtenido), lineas_de(esperado)
    if not o and not e:
        return 1.0
    comunes = sum((o & e).values())
    if comunes == 0:
        return 0.0
    precision, recall = comunes / sum(o.values()), comunes / sum(e.values())
    return 2 * precision * recall / (precision + recall)


def problemas_de_contrato(obtenido: dict) -> list[str]:
    """Invariantes del Anexo que deben cumplirse SIEMPRE, se conozca o no la respuesta correcta."""
    if not _ok(obtenido):
        return [f"sin respuesta: {obtenido.get('error') if isinstance(obtenido, dict) else obtenido}"]
    problemas = []
    if set(obtenido) != CLAVES_CONTRATO:
        problemas.append(f"claves distintas al contrato: {sorted(set(obtenido) ^ CLAVES_CONTRATO)}")
    estado, lineas, pendientes = (
        obtenido.get("estado"),
        obtenido.get("lineas", []),
        obtenido.get("pendientes", []),
    )
    motivos = set(obtenido.get("motivos_revision", []))
    if estado == "confirmado" and (not lineas or motivos):
        problemas.append("confirmado sin líneas o con motivos")
    if estado == "requiere_revision" and not (pendientes or "credito_excedido" in motivos):
        problemas.append("requiere_revision sin pendientes ni crédito excedido")
    if estado == "fuera_de_alcance" and (
        lineas or obtenido.get("total") or obtenido.get("fecha_entrega") is not None
    ):
        problemas.append("fuera_de_alcance con líneas, total o fecha")
    # Tipos y formatos del Anexo (auditoría Codex: antes "estado": "inventado" o "fecha_entrega": "martes"
    # pasaban; la API no puede producirlos porque usa enums de Pydantic, pero el scorer no debe asumirlo).
    if estado not in ESTADOS_VALIDOS:
        problemas.append(f"estado inválido: {estado!r}")
    fecha = obtenido.get("fecha_entrega")  # null en fuera_de_alcance (se revisa arriba)
    if estado != "fuera_de_alcance" and not (isinstance(fecha, str) and _FECHA.fullmatch(fecha)):
        problemas.append(f"fecha_entrega no es AAAA-MM-DD: {fecha!r}")
    if not _es_numero(obtenido.get("total")):
        problemas.append("total no numérico")
    if not isinstance(obtenido.get("mensaje_cliente"), str):
        problemas.append("mensaje_cliente no es texto")
    for x in lineas:
        if set(x) != CLAVES_LINEA or not isinstance(x.get("sku"), str):
            problemas.append(f"línea con claves o tipos distintos al contrato: {x}")
        elif not all(_es_numero(x[k]) for k in ("precio_unitario", "subtotal", "descuento_pct")):
            problemas.append(f"línea con montos no numéricos: {x}")
    for p in pendientes:
        if set(p) != {"motivo", "texto", "opciones"} or not isinstance(p.get("texto"), str):
            problemas.append(f"pendiente con claves o tipos distintos al contrato: {p}")
        elif p["motivo"] not in MOTIVOS_VALIDOS or not isinstance(p["opciones"], list):
            problemas.append(f"pendiente inválido: {p}")
    for s in obtenido.get("sustituciones", []):
        if set(s) != {"sku_solicitado", "sku_entregado", "cantidad"} or not isinstance(
            s.get("cantidad"), int
        ):
            problemas.append(f"sustitución con claves o tipos distintos al contrato: {s}")
    if not motivos <= MOTIVOS_VALIDOS:
        problemas.append(f"motivos inválidos: {motivos - MOTIVOS_VALIDOS}")
    if any(p.get("motivo") == "credito_excedido" for p in pendientes):
        problemas.append("credito_excedido dentro de pendientes")
    if {p.get("motivo") for p in pendientes} != motivos - {"credito_excedido"}:
        problemas.append("motivos_revision no coincide con los motivos de los pendientes")
    if any(not isinstance(x.get("cantidad"), int) or x["cantidad"] < 1 for x in lineas):
        problemas.append("cantidad no entera positiva")
    subtotales = [x.get("subtotal") for x in lineas]
    total = obtenido.get("total", 0)
    numericos = all(map(_es_numero, subtotales)) and _es_numero(total)  # si no, ya se reportó arriba
    if numericos and abs(sum(subtotales) - total) > 0.005:
        problemas.append("total distinto a la suma de subtotales")
    return problemas


def mensaje_coherente(obtenido: dict, nombres: dict[str, str]) -> bool:
    """El mensaje menciona cada producto entregado y, si hay revisión, que un asesor confirmará (§9)."""
    if not _ok(obtenido):
        return False
    texto = obtenido.get("mensaje_cliente", "")
    if not texto:
        return False
    if any(nombres.get(x["sku"], x["sku"]) not in texto for x in obtenido.get("lineas", [])):
        return False
    if obtenido.get("estado") == "requiere_revision" and "asesor" not in texto:
        return False
    return not (obtenido.get("estado") == "confirmado" and "asesor" in texto)
