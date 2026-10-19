"""Parse free-text ingredient lines ("2 dl mælk", "1 1/2 cups flour, sifted") in Danish and English.

The parser is deliberately forgiving: whatever it cannot read stays in ``name``/``note`` and the
original line is always kept, so nothing typed by the user is lost.
"""

import re
import unicodedata
from dataclasses import dataclass
from decimal import Decimal

FRACTIONS = {"½": "1/2", "¼": "1/4", "¾": "3/4", "⅓": "1/3", "⅔": "2/3", "⅛": "1/8", "⅕": "1/5"}

# alias -> canonical unit
UNITS: dict[str, str] = {}
for canon, aliases in {
    "g": ["g", "gr", "gram", "grams", "gramme"],
    "kg": ["kg", "kilo", "kilogram", "kilograms"],
    "ml": ["ml", "milliliter", "millilitre", "milliliters"],
    "cl": ["cl", "centiliter"],
    "dl": ["dl", "deciliter"],
    "l": ["l", "liter", "litre", "liters", "litres"],
    "tsp": ["tsk", "tl", "teske", "teskefuld", "tsp", "teaspoon", "teaspoons"],
    "tbsp": ["spsk", "sk", "el", "spiseske", "spiseskefuld", "tbsp", "tablespoon", "tablespoons"],
    "cup": ["cup", "cups", "kop", "kopper"],
    "oz": ["oz", "ounce", "ounces"],
    "lb": ["lb", "lbs", "pound", "pounds"],
    "pcs": ["stk", "styk", "styks", "pcs", "piece", "pieces", "st"],
    "clove": ["fed", "clove", "cloves"],
    "can": ["dåse", "dåser", "can", "cans", "tin", "tins"],
    "pkg": ["pakke", "pakker", "pk", "pkg", "package", "packages", "pack", "bakke", "pose"],
    "pinch": ["knivspids", "pinch", "pinches", "nip"],
    "bunch": ["bundt", "bunch", "bunches"],
    "slice": ["skive", "skiver", "slice", "slices"],
    "handful": ["håndfuld", "handful", "handfuls"],
    "sprig": ["kvist", "kviste", "sprig", "sprigs"],
}.items():
    for a in aliases:
        UNITS[a] = canon

# canonical unit -> (family, factor to the family's base unit: g or ml)
FAMILY: dict[str, tuple[str, Decimal]] = {
    "g": ("mass", Decimal(1)),
    "kg": ("mass", Decimal(1000)),
    "oz": ("mass", Decimal("28.35")),
    "lb": ("mass", Decimal("453.6")),
    "ml": ("volume", Decimal(1)),
    "cl": ("volume", Decimal(10)),
    "dl": ("volume", Decimal(100)),
    "l": ("volume", Decimal(1000)),
    "tsp": ("volume", Decimal(5)),
    "tbsp": ("volume", Decimal(15)),
    "cup": ("volume", Decimal(240)),
    "pcs": ("count", Decimal(1)),
}

OPTIONAL_RE = re.compile(
    r"(?<!\w)(evt\.?|eventuelt|valgfri|optional|if desired|efter smag|to taste|kan udelades)"
    r"(?!\w)",
    re.IGNORECASE,
)
_NUM = r"\d+\s+\d+/\d+|\d+/\d+|\d+(?:[.,]\d+)?"
QTY_RE = re.compile(rf"^\s*(?P<a>{_NUM})(?:\s*(?:-|–|til|to)\s*(?P<b>{_NUM}))?\s*", re.IGNORECASE)
UNIT_RE = re.compile(r"^(?P<u>[^\W\d_]+)\.?(?=\s|$|,)", re.UNICODE)
LEADING_OF = re.compile(r"^(of|af)\s+", re.IGNORECASE)


@dataclass
class ParsedIngredient:
    raw: str
    name: str
    quantity: Decimal | None
    unit: str | None
    note: str | None
    optional: bool


def _num(s: str) -> Decimal:
    s = s.strip().replace(",", ".")
    total = Decimal(0)
    for part in s.split():
        if "/" in part:
            n, d = part.split("/", 1)
            total += Decimal(n) / Decimal(d) if Decimal(d) else Decimal(0)
        else:
            total += Decimal(part)
    return total.quantize(Decimal("0.001"))


def clean_text(s: str) -> str:
    s = unicodedata.normalize("NFKC", s).replace("\u2044", "/")  # "½" -> "1⁄2" -> "1/2"
    return re.sub(r"\s+", " ", s).strip()


def parse_line(line: str) -> ParsedIngredient:
    raw = re.sub(r"\s+", " ", line).strip()[:300]  # kept as typed
    s = clean_text(raw)
    for k, v in FRACTIONS.items():
        s = re.sub(rf"(\d)\s*{k}", rf"\1 {v}", s).replace(k, v)
    s = re.sub(r"^[-•*·–]\s*", "", s)
    optional = bool(OPTIONAL_RE.search(s))
    s = OPTIONAL_RE.sub("", s).strip(" ,;:.")

    quantity: Decimal | None = None
    m = QTY_RE.match(s)
    if m:
        a = _num(m.group("a"))
        b = _num(m.group("b")) if m.group("b") else None
        quantity = max(a, b) if b is not None else a  # a range: plan for the larger amount
        s = s[m.end() :]
    unit: str | None = None
    m = UNIT_RE.match(s)
    if m and m.group("u").lower() in UNITS:
        unit = UNITS[m.group("u").lower()]
        s = s[m.end() :].lstrip(". ")
    s = LEADING_OF.sub("", s)

    note_parts: list[str] = []
    paren = re.findall(r"\(([^)]*)\)", s)
    if paren:
        note_parts += [p.strip() for p in paren if p.strip()]
        s = re.sub(r"\([^)]*\)", " ", s)
    if "," in s:
        s, rest = s.split(",", 1)
        note_parts.append(rest.strip())
    name = clean_text(s).strip(" .;:-")
    if not name:  # e.g. "salt og peber" parsed to nothing would be odd; keep the line
        name = raw
    if quantity is not None and quantity <= 0:
        quantity = None
    return ParsedIngredient(
        raw=raw,
        name=name[:200],
        quantity=quantity,
        unit=unit,
        note=", ".join(p for p in note_parts if p)[:300] or None,
        optional=optional,
    )


def to_base(quantity: Decimal, unit: str | None) -> tuple[str, Decimal] | None:
    """(family, amount in g / ml / count) or None when the unit is not measurable."""
    fam = FAMILY.get(unit or "pcs")
    if fam is None:
        return None
    return fam[0], quantity * fam[1]
