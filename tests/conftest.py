"""Fixtures compartidas.

- `catalogo_mini`: catálogo sintético y pequeño, construido en código. Permite probar cada regla
  con números controlados, sin depender de los archivos del GES.
- `catalogo_real` / `casos_dev`: los datos publicados en lab3/ (se omiten si no están).
"""

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from novapedidos.dominio.catalogo import Catalogo, Cliente, Escalon, PedidoHistorico, Producto

RAIZ = Path(__file__).resolve().parent.parent
DATA_DIR = RAIZ / "lab3"


def _producto(sku, nombre, categoria, upe, precio, disponible=True, sustituto=None, unidad="fardo"):
    return Producto(
        sku=sku,
        nombre=nombre,
        marca=nombre.split()[0],
        categoria=categoria,
        presentacion="",
        unidad_venta=unidad,
        unidades_por_empaque=upe,
        precio=Decimal(str(precio)),
        disponible=disponible,
        sustituto_sku=sustituto,
    )


@pytest.fixture
def catalogo_mini() -> Catalogo:
    productos = [
        _producto("K1", "Kola 600 ml", "bebidas", 24, 120),
        _producto("K2", "Kola 1.5 L", "bebidas", 12, 144),
        _producto("K3", "Kola 3 L", "bebidas", 6, 132, disponible=False, sustituto="K2"),
        _producto("C1", "Cloro 1 L", "limpieza", 12, 108, unidad="caja"),
        _producto("X1", "Galleta agotada", "snacks", 12, 48, disponible=False),
        _producto("X2", "Producto con sustituto agotado", "snacks", 12, 50, disponible=False, sustituto="X1"),
        _producto("R1", "Redondeo", "snacks", 10, 10.05),
    ]
    clientes = [
        Cliente("T1", "Tienda Uno", "Ana", "Mixco", (0, 3), Decimal(8000), Decimal(1200)),  # lunes, jueves
        Cliente("T2", "Tienda Justa", "Beto", "Mixco", (5,), Decimal(1000), Decimal(760)),  # sábado
        Cliente("T3", "Tienda Nueva", "Caro", "Mixco", (1, 4), Decimal(5000), Decimal(0)),  # sin historial
    ]
    historial = {
        "T1": (
            PedidoHistorico("P1", date(2026, 11, 2), "entregado", (("K1", 1),)),
            PedidoHistorico("P2", date(2026, 11, 9), "entregado", (("K1", 2), ("K3", 1), ("X1", 3))),
            PedidoHistorico("P3", date(2026, 11, 12), "cancelado", (("C1", 9),)),
            PedidoHistorico("P4", date(2026, 12, 31), "entregado", (("C1", 7),)),  # "futuro"
        ),
        "T2": (PedidoHistorico("P5", date(2026, 11, 7), "cancelado", (("K1", 1),)),),
    }
    escalas = {
        "bebidas": (Escalon(10, 3), Escalon(20, 5)),
        "limpieza": (Escalon(6, 3), Escalon(12, 5)),
        "snacks": (Escalon(10, 3),),
    }
    return Catalogo(
        productos={p.sku: p for p in productos},
        clientes={c.cliente_id: c for c in clientes},
        escalas=escalas,
        historial=historial,
    )


@pytest.fixture(scope="session")
def catalogo_real() -> Catalogo:
    if not (DATA_DIR / "datos").exists():
        pytest.skip("Datos del GES no colocados en lab3/")
    return Catalogo.desde_directorio(DATA_DIR)


@pytest.fixture(scope="session")
def casos_dev() -> dict[str, dict]:
    ruta = DATA_DIR / "ejemplos" / "mensajes_dev.jsonl"
    if not ruta.exists():
        pytest.skip("mensajes_dev.jsonl no disponible")
    casos = (json.loads(linea) for linea in ruta.read_text(encoding="utf-8").splitlines() if linea.strip())
    return {c["id"]: c for c in casos}
