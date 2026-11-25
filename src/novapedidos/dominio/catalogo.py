"""Carga y validación de los datos publicados (parquet) en estructuras inmutables y tipadas.

Se carga una sola vez al arrancar la API. Si los datos tienen un problema (un sustituto que no
existe, un día de visita mal escrito), falla al arrancar y no a mitad de una solicitud.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path

import pandas as pd

DIAS_SEMANA = ("lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo")


class ClienteNoEncontrado(LookupError):
    """El cliente_id no existe en clientes.parquet (la API responde 404)."""


class DatosInvalidos(ValueError):
    """Los archivos publicados no cumplen lo que el sistema necesita."""


def sin_tildes(texto: str) -> str:
    """'Miércoles' -> 'miercoles'. Útil para comparar textos escritos de distintas formas."""
    nfkd = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in nfkd if not unicodedata.combining(c)).lower().strip()


@dataclass(frozen=True)
class Producto:
    sku: str
    nombre: str
    marca: str
    categoria: str
    presentacion: str
    unidad_venta: str
    unidades_por_empaque: int
    precio: Decimal
    disponible: bool
    sustituto_sku: str | None


@dataclass(frozen=True)
class Cliente:
    cliente_id: str
    nombre_tienda: str
    propietario: str
    municipio: str
    dias_visita: tuple[int, ...]  # 0 = lunes ... 6 = domingo
    limite_credito: Decimal
    saldo_pendiente: Decimal


@dataclass(frozen=True)
class Escalon:
    cantidad_minima: int
    descuento_pct: int


@dataclass(frozen=True)
class PedidoHistorico:
    pedido_id: str
    fecha_entrega: date
    estado: str
    lineas: tuple[tuple[str, int], ...]  # (sku, cantidad) en el orden del archivo


@dataclass
class Catalogo:
    productos: dict[str, Producto]
    clientes: dict[str, Cliente]
    escalas: dict[str, tuple[Escalon, ...]]  # categoría -> escalones ordenados por cantidad_minima
    sinonimos: dict[str, tuple[str, ...]] = field(default_factory=dict)  # sku -> alias
    historial: dict[str, tuple[PedidoHistorico, ...]] = field(default_factory=dict)  # cliente -> pedidos

    # ------------------------------------------------------------------ consultas
    def cliente(self, cliente_id: str) -> Cliente:
        try:
            return self.clientes[cliente_id]
        except KeyError:
            raise ClienteNoEncontrado(cliente_id) from None

    def ultimo_pedido_entregado(
        self, cliente_id: str, antes_de: date | None = None
    ) -> PedidoHistorico | None:
        """Último pedido con estado 'entregado' (los cancelados no cuentan).

        `antes_de` evita usar un pedido "del futuro" respecto a la fecha del mensaje.
        """
        candidatos = [
            p
            for p in self.historial.get(cliente_id, ())
            if p.estado == "entregado" and (antes_de is None or p.fecha_entrega <= antes_de)
        ]
        if not candidatos:
            return None
        return max(candidatos, key=lambda p: (p.fecha_entrega, p.pedido_id))

    # ------------------------------------------------------------------ carga
    @classmethod
    def desde_directorio(cls, data_dir: Path) -> Catalogo:
        """Lee <data_dir>/datos/*.parquet y valida la integridad referencial."""
        datos = Path(data_dir) / "datos"
        if not datos.is_dir():
            raise DatosInvalidos(f"No existe la carpeta de datos: {datos.resolve()}")

        def leer(nombre: str) -> pd.DataFrame:
            ruta = datos / f"{nombre}.parquet"
            if not ruta.exists():
                raise DatosInvalidos(f"Falta el archivo {ruta}")
            return pd.read_parquet(ruta)

        productos = {
            r.sku: Producto(
                sku=r.sku,
                nombre=r.nombre,
                marca=r.marca,
                categoria=r.categoria,
                presentacion=r.presentacion,
                unidad_venta=r.unidad_venta,
                unidades_por_empaque=int(r.unidades_por_empaque),
                precio=Decimal(str(r.precio)),
                disponible=bool(r.disponible),
                sustituto_sku=r.sustituto_sku
                if isinstance(r.sustituto_sku, str) and r.sustituto_sku
                else None,
            )
            for r in leer("productos").itertuples(index=False)
        }

        clientes = {}
        for r in leer("clientes").itertuples(index=False):
            dias = []
            for d in str(r.dias_visita).split(","):
                nombre = sin_tildes(d)
                if nombre not in DIAS_SEMANA:
                    raise DatosInvalidos(f"Día de visita desconocido '{d}' para {r.cliente_id}")
                dias.append(DIAS_SEMANA.index(nombre))
            clientes[r.cliente_id] = Cliente(
                cliente_id=r.cliente_id,
                nombre_tienda=r.nombre_tienda,
                propietario=r.propietario,
                municipio=r.municipio,
                dias_visita=tuple(sorted(set(dias))),
                limite_credito=Decimal(str(r.limite_credito)),
                saldo_pendiente=Decimal(str(r.saldo_pendiente)),
            )

        escalas: dict[str, list[Escalon]] = {}
        for r in leer("precios_escala").itertuples(index=False):
            escalas.setdefault(r.categoria, []).append(Escalon(int(r.cantidad_minima), int(r.descuento_pct)))

        sinonimos: dict[str, list[str]] = {}
        for r in leer("sinonimos").itertuples(index=False):
            sinonimos.setdefault(r.sku, []).append(str(r.alias))

        historial: dict[str, list[PedidoHistorico]] = {}
        df_h = leer("historial_pedidos")
        for (cliente_id, pedido_id), grupo in df_h.groupby(["cliente_id", "pedido_id"], sort=False):
            historial.setdefault(cliente_id, []).append(
                PedidoHistorico(
                    pedido_id=pedido_id,
                    fecha_entrega=pd.Timestamp(grupo.fecha_entrega.iloc[0]).date(),
                    estado=str(grupo.estado.iloc[0]),
                    lineas=tuple((s, int(c)) for s, c in zip(grupo.sku, grupo.cantidad, strict=True)),
                )
            )

        catalogo = cls(
            productos=productos,
            clientes=clientes,
            escalas={k: tuple(sorted(v, key=lambda e: e.cantidad_minima)) for k, v in escalas.items()},
            sinonimos={k: tuple(v) for k, v in sinonimos.items()},
            historial={k: tuple(v) for k, v in historial.items()},
        )
        catalogo.validar()
        return catalogo

    def validar(self) -> None:
        errores = []
        for p in self.productos.values():
            if p.unidades_por_empaque < 1:
                errores.append(f"{p.sku}: unidades_por_empaque < 1")
            if p.precio <= 0:
                errores.append(f"{p.sku}: precio no positivo")
            if p.sustituto_sku and p.sustituto_sku not in self.productos:
                errores.append(f"{p.sku}: sustituto {p.sustituto_sku} no existe")
        for sku in self.sinonimos:
            if sku not in self.productos:
                errores.append(f"sinónimo de SKU inexistente {sku}")
        for cliente_id, pedidos in self.historial.items():
            for ped in pedidos:
                errores += [
                    f"{ped.pedido_id}: SKU {s} no existe" for s, _ in ped.lineas if s not in self.productos
                ]
            if cliente_id not in self.clientes:
                errores.append(f"historial de cliente inexistente {cliente_id}")
        if errores:
            raise DatosInvalidos("; ".join(errores))
