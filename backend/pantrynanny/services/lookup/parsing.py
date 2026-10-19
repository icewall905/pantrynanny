"""Pure helpers: quantity strings, GTIN forms for providers and category mapping."""

import re

# unit token -> (canonical unit, factor)
_UNITS: dict[str, tuple[str, float]] = {
    "g": ("g", 1),
    "gr": ("g", 1),
    "gram": ("g", 1),
    "kg": ("kg", 1),
    "kilo": ("kg", 1),
    "mg": ("g", 0.001),
    "ml": ("ml", 1),
    "cl": ("cl", 1),
    "dl": ("dl", 1),
    "l": ("l", 1),
    "ltr": ("l", 1),
    "liter": ("l", 1),
    "litre": ("l", 1),
    "oz": ("g", 28.3495),
    "lb": ("g", 453.592),
    "lbs": ("g", 453.592),
    "floz": ("ml", 29.5735),
    "stk": ("pcs", 1),
    "pcs": ("pcs", 1),
    "pc": ("pcs", 1),
    "pk": ("pcs", 1),
    "pack": ("pcs", 1),
}
_NUM = r"(\d+(?:[.,]\d+)?)"
_UNIT = r"(fl\.?\s?oz|[a-zA-Zæøå]+)\.?"
_MULTI = re.compile(rf"{_NUM}\s*[x×*]\s*{_NUM}\s*{_UNIT}", re.IGNORECASE)
_SINGLE = re.compile(rf"{_NUM}\s*{_UNIT}", re.IGNORECASE)


def _num(s: str) -> float:
    return float(s.replace(",", "."))


def _tidy(size: float, unit: str) -> tuple[float, str]:
    if unit == "ml" and size >= 1000:
        return size / 1000, "l"
    if unit == "cl" and size >= 100:
        return size / 100, "l"
    if unit == "dl" and size >= 10:
        return size / 10, "l"
    if unit == "g" and size >= 1000:
        return size / 1000, "kg"
    return size, unit


def parse_quantity(text: str | None) -> tuple[float | None, str | None, str | None]:
    """Parse an Open Food Facts ``quantity`` string.

    Returns ``(size, unit, note)`` where size/unit are the *total* content of the package and note
    describes a multipack ("6 × 33 cl") or is None. Unparseable input yields ``(None, None, None)``.
    """
    if not text:
        return None, None, None
    s = text.strip()
    m = _MULTI.search(s)
    if m:
        count, each, unit_tok = _num(m.group(1)), _num(m.group(2)), m.group(3)
        key = re.sub(r"[\s.]", "", unit_tok.lower())
        if key in _UNITS and _UNITS[key][0] != "pcs":
            unit, factor = _UNITS[key]
            total, unit = _tidy(round(count * each * factor, 3), unit)
            note = f"{count:g} × {each:g} {unit_tok.strip('.')}"
            return round(total, 3), unit, note
    m = _SINGLE.search(s)
    if m:
        key = re.sub(r"[\s.]", "", m.group(2).lower())
        if key in _UNITS:
            unit, factor = _UNITS[key]
            size = round(_num(m.group(1)) * factor, 3)
            if unit != "pcs":
                size, unit = _tidy(size, unit)
            if size > 0:
                return round(size, 3), unit, None
    return None, None, None


def provider_code(code: str) -> str | None:
    """GTIN-14 (our normalised form) -> the shortest conventional form providers index.

    EAN-13/UPC-A -> 13 digits, EAN-8 -> 8 digits. ``local:``/``instore:`` codes return None.
    """
    if not code.isdigit():
        return None
    c = code.lstrip("0")
    if len(c) <= 8:
        return c.zfill(8)
    return c.zfill(13)


# --------------------------------------------------------------------------- categories

# Ordered: first rule with a matching tag wins. Values are the default Danish category names.
_CATEGORY_RULES: list[tuple[str, frozenset[str]]] = [
    ("Frost", frozenset({"en:frozen-foods", "en:ice-creams-and-sorbets", "en:frozen-desserts"})),
    (
        "Mejeri",
        frozenset(
            {
                "en:dairies",
                "en:milks",
                "en:cheeses",
                "en:yogurts",
                "en:butters",
                "en:creams",
                "en:eggs",
                "en:fermented-milk-products",
                "en:dairy-desserts",
            }
        ),
    ),
    (
        "Kød & fisk",
        frozenset(
            {
                "en:meats",
                "en:meats-and-their-products",
                "en:fishes",
                "en:seafood",
                "en:fish-and-meat-and-eggs",
                "en:poultry",
                "en:sausages",
                "en:charcuterie",
                "en:cured-meats",
            }
        ),
    ),
    (
        "Brød & bagværk",
        frozenset({"en:breads", "en:pastries", "en:bakery-products", "en:viennoiseries"}),
    ),
    (
        "Drikkevarer",
        frozenset(
            {
                "en:beverages",
                "en:waters",
                "en:sodas",
                "en:juices-and-nectars",
                "en:fruit-juices",
                "en:beers",
                "en:wines",
                "en:alcoholic-beverages",
                "en:coffees",
                "en:teas",
                "en:energy-drinks",
            }
        ),
    ),
    (
        "Frugt & grønt",
        frozenset(
            {
                "en:fruits",
                "en:vegetables",
                "en:fresh-vegetables",
                "en:fresh-fruits",
                "en:fruits-and-vegetables-based-foods",
                "en:salads",
            }
        ),
    ),
    (
        "Snacks & slik",
        frozenset(
            {
                "en:snacks",
                "en:sweet-snacks",
                "en:salty-snacks",
                "en:chocolates",
                "en:candies",
                "en:confectioneries",
                "en:biscuits-and-cakes",
                "en:biscuits",
                "en:chips-and-fries",
            }
        ),
    ),
    ("Krydderier", frozenset({"en:spices", "en:seasonings", "en:herbs", "en:salts"})),
    (
        "Kolonial",
        frozenset(
            {
                "en:cereals-and-potatoes",
                "en:cereals-and-their-products",
                "en:pastas",
                "en:rices",
                "en:flours",
                "en:canned-foods",
                "en:sauces",
                "en:groceries",
                "en:breakfast-cereals",
                "en:legumes",
                "en:oils",
                "en:fats",
                "en:spreads",
                "en:sugars",
                "en:condiments",
                "en:soups",
                "en:meals",
            }
        ),
    ),
]
_NONFOOD_RULES: list[tuple[str, frozenset[str]]] = [
    (
        "Personlig pleje",
        frozenset(
            {
                "en:hygiene",
                "en:cosmetics",
                "en:body-care",
                "en:hair-care",
                "en:oral-hygiene",
                "en:soaps",
                "en:personal-care",
                "en:deodorants",
                "en:toothpastes",
                "en:shampoos",
            }
        ),
    ),
    (
        "Husholdning",
        frozenset(
            {
                "en:cleaning-products",
                "en:household",
                "en:detergents",
                "en:dishwashing",
                "en:laundry",
            }
        ),
    ),
]


def map_category(tags: list[str] | None) -> str | None:
    """Map Open*Facts ``categories_tags`` to one of the default Danish category names."""
    if not tags:
        return None
    s = set(tags)
    for name, keys in [*_CATEGORY_RULES, *_NONFOOD_RULES]:
        if s & keys:
            return name
    return None


_ALLERGENS_DA = {
    "milk": "mælk",
    "gluten": "gluten",
    "eggs": "æg",
    "soybeans": "soja",
    "nuts": "nødder",
    "peanuts": "jordnødder",
    "fish": "fisk",
    "crustaceans": "krebsdyr",
    "celery": "selleri",
    "mustard": "sennep",
    "sesame-seeds": "sesam",
    "sulphur-dioxide-and-sulphites": "svovldioxid og sulfitter",
    "lupin": "lupin",
    "molluscs": "bløddyr",
}


def allergen_names(tags: list[str] | None) -> list[str]:
    out: list[str] = []
    for t in tags or []:
        slug = t.split(":", 1)[-1]
        name = _ALLERGENS_DA.get(slug, slug.replace("-", " "))
        if name not in out:
            out.append(name)
    return out
