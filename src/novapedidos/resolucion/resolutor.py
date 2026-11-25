"""Resolución determinista de una mención de producto a SKU(s) del catálogo.

Estrategia: FILTRAR POR RESTRICCIONES. Cada palabra y cada medida del cliente descarta productos;
lo que sobrevive decide:

    1 producto      -> UNICO      ("kola 600"            -> B01)
    varios          -> AMBIGUO    ("naranjitas"          -> B04, B05)
    ninguno         -> NO_EXISTE  ("cerveza", "kola 2 litros", "kola norte light")

Cómo se reconoce cada palabra del cliente (de más a menos confiable):
    1. exacta en el catálogo / alias, o vía sinónimo curado (más su forma de género opuesto)
    2. palabras pegadas o separadas ("kolanorte", "lava platos")
    3. diminutivo ("azuquita" -> azúcar, "aceitito" -> aceite)
    4. clave fonética ("shampu" = "shampoo", "polbo" = "polvo")
    5. error de escritura: distancia Damerau-Levenshtein <= 1 (<= 2 en palabras de 8+ letras) sobre la
       clave fonética. Es "suave": si contradice a las demás palabras no se usa.

Regla de prudencia: si queda alguna palabra que no se reconoce ("kola norte LIGHT", "jugo huerto de
PIÑA", "aceite de OLIVA"), el cliente describe una variante que no podemos verificar -> NO_EXISTE.
Ante la duda, no se adivina (politicas.md §1).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from rapidfuzz.distance import DamerauLevenshtein

from novapedidos.dominio.catalogo import Catalogo
from novapedidos.dominio.modelos import Motivo, Pendiente
from novapedidos.resolucion.normalizacion import (
    SINONIMOS_PALABRA,
    Medida,
    fonetica,
    normalizar,
    raices_diminutivo,
    singular,
)

# Palabras cortas ("sal", "te", "gas", "vela") solo coinciden exactas o por clave fonética:
# con 4 letras, 1 edición ya convierte "vela" en "bella".
LARGO_MINIMO_FUZZY = 5


def max_ediciones(palabra: str) -> int:
    """1 error; 2 solo en palabras largas. ("ensalada" está a 2 de "salada": con 8 letras no basta)."""
    return 2 if len(palabra) >= 10 else 1


class TipoResolucion(StrEnum):
    UNICO = "unico"
    AMBIGUO = "ambiguo"
    NO_EXISTE = "no_existe"


@dataclass(frozen=True)
class Resolucion:
    tipo: TipoResolucion
    skus: tuple[str, ...] = ()
    metodo: str = (
        ""  # alias | palabras | fuzzy | sin_coincidencias | conflicto | medida | desconocida | negacion
    )
    detalle: dict = field(default_factory=dict, compare=False)

    @property
    def sku(self) -> str | None:
        return self.skus[0] if self.tipo is TipoResolucion.UNICO else None

    def a_pendiente(self, texto: str) -> Pendiente:
        """Convierte una resolución fallida en el pendiente del contrato."""
        if self.tipo is TipoResolucion.AMBIGUO:
            return Pendiente(motivo=Motivo.PRODUCTO_AMBIGUO, texto=texto, opciones=list(self.skus))
        if self.tipo is TipoResolucion.NO_EXISTE:
            return Pendiente(motivo=Motivo.PRODUCTO_NO_EXISTE, texto=texto, opciones=[])
        raise ValueError("Una resolución única no es un pendiente")


@dataclass
class _Coincidencia:
    palabra: str
    canonicas: tuple[str, ...]
    skus: frozenset[str]
    fuzzy: bool
    via: str


class Resolutor:
    """Se construye una vez a partir del catálogo; `resolver()` es puro y rápido (~microsegundos)."""

    def __init__(self, catalogo: Catalogo) -> None:
        self.catalogo = catalogo
        self.indice: dict[str, set[str]] = {}  # palabra canónica (singular) -> SKUs que la contienen
        self.medidas: dict[str, tuple[Medida, ...]] = {}
        self.exactos: dict[str, str] = {}  # texto normalizado completo -> SKU

        for p in catalogo.productos.values():
            nombre = normalizar(f"{p.nombre} {p.presentacion}")
            palabras = {singular(w) for w in nombre.palabras + normalizar(p.marca).palabras}
            for w in palabras:
                self.indice.setdefault(w, set()).add(p.sku)
            self.medidas[p.sku] = nombre.medidas
            self.exactos[normalizar(p.nombre).texto] = p.sku

        for sku, aliases in catalogo.sinonimos.items():
            for alias in aliases:
                norm = normalizar(alias)
                self.exactos[norm.texto] = sku
                for w in norm.palabras:  # los alias también enriquecen el vocabulario
                    self.indice.setdefault(singular(w), set()).add(sku)

        self.vocabulario = sorted(set(self.indice) | set(SINONIMOS_PALABRA))
        self.fonetico: dict[str, set[str]] = {}  # clave fonética -> palabras del vocabulario
        for w in self.vocabulario:
            self.fonetico.setdefault(fonetica(w), set()).add(w)

    # ------------------------------------------------------------------ palabras
    def _skus_de(self, canonicas: tuple[str, ...]) -> frozenset[str]:
        return frozenset(s for c in canonicas for s in self.indice.get(singular(c), ()))

    def _exacta(self, palabra: str) -> tuple[str, ...] | None:
        """Exacta en el índice y/o en sinónimos (se unen), con plural y género opuesto."""
        variantes = [palabra]
        if len(palabra) > 3 and palabra.endswith("s"):
            variantes.append(palabra[:-1])
        if len(palabra) > 4 and palabra.endswith("es"):
            variantes.append(palabra[:-2])
        for v in variantes:
            canonicas: list[str] = []
            if v in self.indice:
                canonicas.append(v)
                if v[-1] in "ao" and (opuesta := v[:-1] + ("o" if v[-1] == "a" else "a")) in self.indice:
                    canonicas.append(opuesta)  # "saladas" también es "salado" (maní salado)
            canonicas += [c for c in SINONIMOS_PALABRA.get(v, ()) if c not in canonicas]
            if canonicas:
                return tuple(canonicas)
        return None

    def _canonizar(self, palabra: str) -> tuple[tuple[str, ...], bool, str] | None:
        """Palabra del cliente -> (palabras del catálogo, es_fuzzy, vía) o None si no se reconoce."""
        if canon := self._exacta(palabra):
            return canon, False, "exacta"
        for raiz in raices_diminutivo(palabra):
            for candidata in (raiz, raiz + "o", raiz + "a", raiz + "e"):
                if canon := self._exacta(candidata):
                    return canon, False, "diminutivo"
            if len(raiz) >= 4:
                prefijo = tuple(w for w in self.indice if w.startswith(raiz))
                if prefijo:
                    return prefijo, False, "diminutivo"
        variantes = [palabra] + ([palabra[:-1]] if palabra.endswith("s") and len(palabra) > 3 else [])
        for v in variantes:
            if (clave := fonetica(v)) in self.fonetico:
                return self._expandir(self.fonetico[clave]), False, "fonetica"
        if any(ch.isdigit() for ch in palabra):
            return None
        mejores: set[str] = set()
        limite = max_ediciones(palabra)
        mejor_d = limite + 1
        for v in variantes:
            if len(v) < LARGO_MINIMO_FUZZY:
                continue
            clave = fonetica(v)
            for w in self.vocabulario:
                # Se compara el texto tal cual y su clave fonética; vale la menor distancia.
                # (La clave cambia "c" por "k" según la letra siguiente: "picntes" vs "picante".)
                d = min(
                    DamerauLevenshtein.distance(v, w, score_cutoff=limite),
                    DamerauLevenshtein.distance(clave, fonetica(w), score_cutoff=limite),
                )
                if d > limite:  # con score_cutoff, rapidfuzz devuelve limite+1 cuando se pasa
                    continue
                if d < mejor_d:
                    mejor_d, mejores = d, {w}
                elif d == mejor_d:
                    mejores.add(w)
        return (self._expandir(mejores), True, "fuzzy") if mejores else None

    def _expandir(self, palabras: set[str]) -> tuple[str, ...]:
        """Palabras del vocabulario (o claves de sinónimos) -> palabras canónicas del índice."""
        salida: list[str] = []
        for w in sorted(palabras):
            for c in self._exacta(w) or ():
                if c not in salida:
                    salida.append(c)
        return tuple(salida)

    def _unir_y_separar(self, palabras: tuple[str, ...]) -> list[str]:
        """'lava platos' -> 'lavaplatos'; 'kolanorte' -> 'kola', 'norte'."""
        salida: list[str] = []
        i = 0
        while i < len(palabras):
            if i + 1 < len(palabras) and self._exacta(palabras[i] + palabras[i + 1]):
                salida.append(palabras[i] + palabras[i + 1])
                i += 2
                continue
            w = palabras[i]
            if len(w) >= 6 and not self._exacta(w):
                for k in range(3, len(w) - 2):
                    if self._exacta(w[:k]) and self._exacta(w[k:]):
                        salida += [w[:k], w[k:]]
                        break
                else:
                    salida.append(w)
            else:
                salida.append(w)
            i += 1
        return salida

    # ------------------------------------------------------------------ API
    def resolver(self, texto: str) -> Resolucion:
        norm = normalizar(texto)
        if norm.texto in self.exactos and not norm.negadas:
            return Resolucion(TipoResolucion.UNICO, (self.exactos[norm.texto],), "alias")

        coincidencias: list[_Coincidencia] = []
        desconocidas: list[str] = []
        for palabra in self._unir_y_separar(norm.palabras):
            canon = self._canonizar(palabra)
            if canon is None:
                desconocidas.append(palabra)
                continue
            canonicas, es_fuzzy, via = canon
            coincidencias.append(_Coincidencia(palabra, canonicas, self._skus_de(canonicas), es_fuzzy, via))

        detalle = {
            "palabras": [(c.palabra, c.canonicas, c.via) for c in coincidencias],
            "desconocidas": desconocidas,
            "medidas": [f"{m.numero}{m.unidad or ''}" for m in norm.medidas],
            "negadas": list(norm.negadas),
        }

        def no_existe(metodo: str) -> Resolucion:
            return Resolucion(TipoResolucion.NO_EXISTE, (), metodo, detalle)

        if not coincidencias:
            return no_existe("sin_coincidencias")

        # Intersección estricta con palabras confiables
        candidatos: set[str] | None = None
        for c in (c for c in coincidencias if not c.fuzzy):
            candidatos = set(c.skus) if candidatos is None else candidatos & c.skus
        if candidatos is not None and not candidatos:
            return no_existe("conflicto")

        # Intersección suave con palabras corregidas por distancia de edición
        for c in (c for c in coincidencias if c.fuzzy):
            if candidatos is None:
                candidatos = set(c.skus)
            elif candidatos & c.skus:
                candidatos &= c.skus
            else:
                desconocidas.append(c.palabra)  # la corrección contradice lo demás: no se usa

        # Prudencia: una palabra no reconocida describe algo que no podemos verificar
        if desconocidas:
            return no_existe("desconocida")

        # Medidas: filtro estricto
        for medida in norm.medidas:
            filtrados = {s for s in candidatos if any(medida.compatible_con(m) for m in self.medidas[s])}
            if not filtrados:
                return no_existe("medida")
            candidatos = filtrados

        # Negaciones ("sin picante"): se excluyen productos que tienen esa característica
        for negada in norm.negadas:
            canon = self._canonizar(negada)
            excluir = self._skus_de(canon[0]) if canon else frozenset()
            if not (candidatos & excluir):  # niega algo que ningún candidato tiene: variante desconocida
                return no_existe("negacion")
            candidatos -= excluir
            if not candidatos:
                return no_existe("negacion")

        skus = tuple(sorted(candidatos))
        metodo = "fuzzy" if any(c.fuzzy for c in coincidencias) else "palabras"
        tipo = TipoResolucion.UNICO if len(skus) == 1 else TipoResolucion.AMBIGUO
        return Resolucion(tipo, skus, metodo, detalle)
