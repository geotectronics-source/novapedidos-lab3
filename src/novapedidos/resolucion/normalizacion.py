"""Normalización de textos de producto: el mismo proceso se aplica al catálogo y a los mensajes.

Si ambos lados pasan por la misma función, "Kola Norte 1.5 L", "kola de litro y medio" y
"KOLA 1,5" terminan representados igual y se pueden comparar.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal

from novapedidos.dominio.catalogo import sin_tildes

# ---------------------------------------------------------------- vocabulario curado
# Palabras que no ayudan a identificar el producto (artículos, empaques, relleno).
STOPWORDS = frozenset(
    """
    de del la las el los lo y e o con en para por a al un una unos unas su sus mi mis me le les que
    mas tambien bien porfa favor solo nada eso este esta otro otra otros otras mismo misma
    fardo fardito caja cajita cajon display docena botella botellita lata latita bolsa bolsita
    unidad paquete paquetito sobre sobrecito pieza pastilla bebida
    helada helado fria frias grande grandes pequena pequeno chiquita chiquito sabor marca tipo
    presentacion original normal natural pues mire aja eh oiga
    """.split()
)

# Sinónimos y nombres informales -> palabras del catálogo. No es exhaustivo (como sinonimos.parquet):
# la capa LLM complementa lo que aquí no está. Si la palabra también existe en el catálogo, se UNEN
# ("naranja" = Jugo Huerto Naranja + la marca Naranjita).
SINONIMOS_PALABRA: dict[str, tuple[str, ...]] = {
    "coca": ("kola",),
    "cocacola": ("kola",),
    "cola": ("kola",),
    "gaseosa": ("kola", "naranjita", "limonada"),
    "refresco": ("kola", "naranjita", "limonada"),
    "soda": ("kola", "naranjita", "limonada"),
    "naranja": ("naranja", "naranjita"),
    "limon": ("limon", "limonada"),
    "papalina": ("papita",),
    "galletita": ("galleta",),
    "fideo": ("codito", "espagueti"),
    "spaghetti": ("espagueti",),
    "spagueti": ("espagueti",),
    "champu": ("shampoo",),
    "lavatrastos": ("lavaplatos",),
    "lavatrastes": ("lavaplatos",),
    "trastes": ("lavaplatos",),
    "trastos": ("lavaplatos",),
    "lejia": ("cloro",),
    "energizante": ("energia",),
    "mania": ("mani",),  # Guatemala: "unas manías"
    "cacahuate": ("mani",),
    "cacahuete": ("mani",),
    "bolita": ("roll",),  # desodorante de bolita = roll-on
}

# Frases de varias palabras -> forma canónica (se aplican antes de separar en palabras).
SINONIMOS_FRASE: tuple[tuple[str, str], ...] = (
    (r"\blitro y medio\b", "1.5 l"),
    (r"\bmedio litro\b", "0.5 l"),
    (r"\bde libra\b", "1 lb"),
    (r"\bcoca cola\b", "kola"),
    (r"\b(pasta|crema) (de|para) (los )?dientes\b", "pasta dental"),
    (r"\bcrema dental\b", "pasta dental"),
    (r"\bpasta dent[a-z]*\b", "pasta dental"),  # dental, dentífrica, dentrífica...
    (r"\bpapel (de bano|sanitario)\b", "papel higienico"),
    (r"\bjabon(cito)? (de|para) (lavar )?(los )?(trastes|trastos|platos)\b", "lavaplatos"),
    (r"\bjabon(cito)? (de|para) (lavar )?(la )?ropa\b", "jabon lavandero"),
    (r"\bjabon(cito)? de (bano|olor)\b", "jabon tocador"),
    (r"\b(detergente|jabon) en polvo\b", "detergente"),
    (r"\bgalletas? de soda\b", "galleta salada"),
    (r"\bsopas? instantaneas?\b", "sopa"),
    (r"\baceite (de|para) (cocina|cocinar)\b", "aceite"),
    (r"\bharina (de maiz )?para tortillas\b", "harina de maiz"),
    (r"\bfrijol(es)? colorado(s)?\b", "frijol rojo"),
    (r"\bbebida energ(etica|izante)\b", "energia"),
)

# Forma escrita -> símbolo de la unidad.
UNIDADES_MEDIDA: dict[str, str] = {
    **dict.fromkeys(["ml", "mls", "mililitro", "mililitros", "cc"], "ml"),
    **dict.fromkeys(["l", "lt", "lts", "ltr", "ltrs", "lit", "litro", "litros"], "l"),
    **dict.fromkeys(["g", "gr", "grs", "gramo", "gramos"], "g"),
    **dict.fromkeys(["kg", "kilo", "kilos", "kilogramo", "kilogramos"], "kg"),
    **dict.fromkeys(["lb", "lbs", "libra", "libras"], "lb"),
    **dict.fromkeys(["rollo", "rollos"], "rollo"),
    **dict.fromkeys(["paquete", "paquetes"], "paquete"),
    **dict.fromkeys(["bolsita", "bolsitas"], "bolsita"),
    **dict.fromkeys(["sobre", "sobres"], "sobre"),
}
# Símbolo -> (dimensión, factor a la unidad base). Así 0.5 l = 500 ml y 1000 ml = 1 l.
DIMENSIONES: dict[str, tuple[str, Decimal]] = {
    "ml": ("volumen", Decimal(1)),
    "l": ("volumen", Decimal(1000)),
    "g": ("masa", Decimal(1)),
    "kg": ("masa", Decimal(1000)),
}

# Palabras de empaque: un número seguido de ellas es una CANTIDAD ("2 fardos"), no una medida.
EMPAQUES = frozenset(
    "fardo fardos fardito farditos caja cajas cajita cajitas display displays docena docenas botella "
    "botellas lata latas bolsa bolsas unidad unidades quintal quintales".split()
)

UNIDADES_NUM = {
    "un": 1, "uno": 1, "una": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5, "seis": 6, "siete": 7,
    "ocho": 8, "nueve": 9, "diez": 10, "once": 11, "doce": 12, "trece": 13, "catorce": 14, "quince": 15,
    "dieciseis": 16, "veinte": 20, "veinticuatro": 24, "treinta": 30, "cuarenta": 40, "cincuenta": 50,
    "sesenta": 60, "setenta": 70, "ochenta": 80, "noventa": 90, "cien": 100, "ciento": 100,
    "doscientos": 200, "trescientos": 300, "cuatrocientos": 400, "quinientos": 500, "seiscientos": 600,
    "setecientos": 700, "ochocientos": 800, "novecientos": 900, "mil": 1000,
}  # fmt: skip
ARTICULOS_NUMERO = {"un", "uno", "una"}  # solo son número delante de una unidad o un empaque


@dataclass(frozen=True)
class Medida:
    """Una presentación: 600 ml, 1.5 l, 100 lb, 12 rollos. `unidad` None = número suelto ("kola 600")."""

    numero: Decimal
    unidad: str | None  # ml, l, g, kg, lb, rollo, paquete, bolsita, sobre

    def en_base(self) -> tuple[str, Decimal] | None:
        """(dimensión, valor en unidad base) o None si la unidad no es convertible."""
        if self.unidad is None:
            return None
        dimension, factor = DIMENSIONES.get(self.unidad, (self.unidad, Decimal(1)))
        return dimension, self.numero * factor

    def compatible_con(self, otra: Medida) -> bool:
        if self.unidad is None or otra.unidad is None:  # "kola 600" vs "600 ml"
            return self.numero == otra.numero
        return self.en_base() == otra.en_base()


@dataclass(frozen=True)
class TextoNormalizado:
    texto: str
    palabras: tuple[str, ...]
    medidas: tuple[Medida, ...]
    negadas: tuple[str, ...] = ()  # "chicharritos sin picante" -> ("picante",)


def _numero(texto: str) -> Decimal:
    """'600' -> 600, '1.50' -> 1.5 (sin notación científica: normalize() daría 6E+2)."""
    d = Decimal(texto)
    return d.quantize(Decimal(1)) if d == d.to_integral_value() else d.normalize()


def _fraccion(m: re.Match) -> str:
    entero = Decimal(m.group(1) or 0)
    return str(_numero(str(entero + Decimal(m.group(2)) / Decimal(m.group(3)))))


def limpiar(texto: str) -> str:
    """Minúsculas, sin tildes, sin signos, con fracciones y sinónimos de frase aplicados."""
    t = texto.replace("½", " 1/2").replace("¼", " 1/4").replace("¾", " 3/4")
    t = sin_tildes(t)
    t = re.sub(r"(\d),(\d)", r"\1.\2", t)  # 1,5 -> 1.5
    t = re.sub(r"(?:(\d+)\s+)?(\d+)/(\d+)", _fraccion, t)  # 1 1/2 -> 1.5 ; 1/2 -> 0.5
    t = re.sub(r"(\d)([a-z])", r"\1 \2", t)  # 600ml -> 600 ml
    t = re.sub(r"([a-z])(\d)", r"\1 \2", t)  # norte600 -> norte 600
    t = re.sub(r"[^a-z0-9. ]+", " ", t)  # signos, emojis, guiones
    t = re.sub(r"(?<!\d)\.|\.(?!\d)", " ", t)  # puntos que no son decimales
    t = re.sub(r"\s+", " ", t).strip()
    for patron, reemplazo in SINONIMOS_FRASE:
        t = re.sub(patron, reemplazo, t)
    return re.sub(r"\s+", " ", t).strip()


def _numeros_en_palabras(tokens: list[str]) -> list[str]:
    """'seiscientos' -> '600', 'cuatrocientos setenta y tres' -> '473'.

    'un/uno/una' solo cuentan como número delante de una unidad o un empaque ("una caja").
    """
    salida: list[str] = []
    i = 0
    while i < len(tokens):
        j, total, actual, hay = i, 0, 0, False
        while j < len(tokens):
            tok = tokens[j]
            if tok == "y" and hay and j + 1 < len(tokens) and tokens[j + 1] in UNIDADES_NUM:
                j += 1
                continue
            if tok not in UNIDADES_NUM:
                break
            valor = UNIDADES_NUM[tok]
            if valor == 1000:
                total, actual = total + max(actual, 1) * 1000, 0
            else:
                actual += valor
            hay = True
            j += 1
        if not hay:
            salida.append(tokens[i])
            i += 1
            continue
        siguiente = tokens[j] if j < len(tokens) else None
        solo_articulo = j - i == 1 and tokens[i] in ARTICULOS_NUMERO
        if solo_articulo and siguiente not in UNIDADES_MEDIDA and siguiente not in EMPAQUES:
            salida.append(tokens[i])  # "una caja" sí es número; "un aceite" es artículo
        else:
            salida.append(str(total + actual))
        i = j
    return salida


def normalizar(texto: str) -> TextoNormalizado:
    """Separa el texto en palabras significativas, medidas (número + unidad) y palabras negadas."""
    t = limpiar(texto)
    tokens = _numeros_en_palabras(t.split())
    palabras: list[str] = []
    medidas: list[Medida] = []
    negadas: list[str] = []
    negar = False
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        siguiente = tokens[i + 1] if i + 1 < len(tokens) else None
        if re.fullmatch(r"\d+(\.\d+)?", tok):
            if siguiente in EMPAQUES:  # "2 fardos": es una cantidad, no describe el producto
                if siguiente.startswith("quintal"):  # ...salvo "quintal", que distingue al arroz A02
                    palabras.append("quintal")
                i += 2
                continue
            if i == 0 and siguiente is not None and siguiente not in UNIDADES_MEDIDA:
                i += 1  # número inicial seguido del producto: cantidad ("3 kola 600")
                continue
            numero = _numero(tok)
            if siguiente in UNIDADES_MEDIDA:
                medidas.append(Medida(numero, UNIDADES_MEDIDA[siguiente]))
                i += 2
                continue
            medidas.append(Medida(numero, None))
            i += 1
            continue
        if tok == "sin":
            negar = True
        elif not es_stopword(tok) and tok not in UNIDADES_MEDIDA and len(tok) > 1:
            (negadas if negar else palabras).append(tok)
            negar = False
        i += 1
    return TextoNormalizado(t, tuple(palabras), tuple(medidas), tuple(negadas))


def es_stopword(palabra: str) -> bool:
    """Incluye plurales: 'cajitas', 'farditos', 'botellas', 'displays'."""
    return (
        palabra in STOPWORDS
        or (palabra.endswith("s") and palabra[:-1] in STOPWORDS)
        or (palabra.endswith("es") and palabra[:-2] in STOPWORDS)
    )


def singular(palabra: str) -> str:
    """Plural simple del catálogo: 'galletas' -> 'galleta'. (Para los mensajes se usa el vocabulario)."""
    return palabra[:-1] if len(palabra) > 3 and palabra.endswith("s") else palabra


def fonetica(palabra: str) -> str:
    """Clave fonética del español de Guatemala: v=b, z=s, ll=y, c/qu=k, h muda, letras dobles.

    'vaniya' y 'vainilla' -> 'baniya'/'bainiya' (a 1 edición); 'shampu' y 'shampoo' -> 'shampu'.
    """
    w = palabra.replace("ll", "y").replace("v", "b").replace("z", "s").replace("oo", "u")
    w = w.replace("qu", "k").replace("ce", "se").replace("ci", "si")
    w = re.sub(r"c(?=[aou])", "k", w)
    w = re.sub(r"(?<![cs])h", "", w)
    return re.sub(r"(.)\1+", r"\1", w)


DIMINUTIVOS = (
    "ecitos",
    "ecitas",
    "ecito",
    "ecita",
    "citos",
    "citas",
    "cito",
    "cita",
    "itos",
    "itas",
    "ito",
    "ita",
)


def raices_diminutivo(palabra: str) -> list[str]:
    """'azuquita' -> ['azuc', ...]; 'aceitito' -> ['aceit']; 'manicito' -> ['mani']; 'salita' -> ['sal']."""
    raices = []
    for sufijo in DIMINUTIVOS:
        if palabra.endswith(sufijo) and len(palabra) - len(sufijo) >= 3:
            raiz = palabra[: -len(sufijo)]
            raiz = re.sub(r"qu$", "c", raiz)
            raiz = re.sub(r"gu$", "g", raiz)
            raices.append(raiz)
    return raices
