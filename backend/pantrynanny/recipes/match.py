"""Match recipe ingredients to the household's products and work out what is in stock.

Deterministic and explainable: an ingredient matches a product by name/alias tokens (with a
small Danish/English synonym table and Danish compound words such as "letmælk" ⊃ "mælk"). An
explicit product link on the ingredient always wins.
"""

import re
import unicodedata
from dataclasses import dataclass, field
from decimal import ROUND_UP, Decimal

from .parse import FAMILY, to_base

# English (and a few variants) -> Danish generic names, so imported English recipes match a
# Danish pantry. Kept small and boring on purpose; aliases on products cover the rest.
SYNONYMS: dict[str, str] = {
    "milk": "mælk",
    "egg": "æg",
    "eggs": "æg",
    "butter": "smør",
    "flour": "mel",
    "wheat flour": "hvedemel",
    "sugar": "sukker",
    "salt": "salt",
    "pepper": "peber",
    "onion": "løg",
    "onions": "løg",
    "garlic": "hvidløg",
    "potato": "kartoffel",
    "potatoes": "kartofler",
    "carrot": "gulerod",
    "carrots": "gulerødder",
    "rice": "ris",
    "pasta": "pasta",
    "cheese": "ost",
    "cream": "fløde",
    "yogurt": "yoghurt",
    "yoghurt": "yoghurt",
    "oil": "olie",
    "olive oil": "olivenolie",
    "tomato": "tomat",
    "tomatoes": "tomater",
    "chicken": "kylling",
    "beef": "oksekød",
    "pork": "svinekød",
    "minced beef": "hakket oksekød",
    "ground beef": "hakket oksekød",
    "bread": "brød",
    "oats": "havregryn",
    "rolled oats": "havregryn",
    "lemon": "citron",
    "apple": "æble",
    "apples": "æbler",
    "banana": "banan",
    "bananas": "bananer",
    "honey": "honning",
    "water": "vand",
    "coffee": "kaffe",
    "tea": "te",
    "beans": "bønner",
    "peas": "ærter",
    "spinach": "spinat",
    "mushrooms": "champignon",
    "mushroom": "champignon",
    "bacon": "bacon",
    "ham": "skinke",
    "salmon": "laks",
    "tuna": "tun",
    "baking powder": "bagepulver",
    "yeast": "gær",
    "vanilla sugar": "vaniljesukker",
    "cinnamon": "kanel",
    "broth": "bouillon",
    "stock": "bouillon",
    "cucumber": "agurk",
    "lettuce": "salat",
    "parsley": "persille",
    "dill": "dild",
    "chives": "purløg",
    "leek": "porre",
    "cabbage": "kål",
    "sour cream": "creme fraiche",
    "creme fraiche": "creme fraiche",
    "crème fraîche": "creme fraiche",
}
# Plural/singular Danish pairs the token rule cannot see.
PLURALS: dict[str, str] = {
    "kartofler": "kartoffel",
    "gulerødder": "gulerod",
    "tomater": "tomat",
    "æbler": "æble",
    "bananer": "banan",
    "løg": "løg",
    "æg": "æg",
    "citroner": "citron",
    "agurker": "agurk",
}
# Always assumed to be in the house; never put on the shopping list.
STAPLES = {"salt", "peber", "vand", "water", "salt og peber", "salt and pepper", "isvand"}
# Compound words that end in an ingredient but are something else.
NOT_A_KIND_OF: dict[str, set[str]] = {
    "løg": {"hvidløg", "purløg"},
    "mel": {"karamel"},
    "ost": {"kost", "frost", "rost"},
    "ris": {"pris", "gris"},
    "is": set(),
}
WORD = re.compile(r"[^\W\d_]+", re.UNICODE)


def norm(s: str) -> str:
    s = (
        unicodedata.normalize("NFKC", s)
        .lower()
        .replace("crème", "creme")
        .replace("fraîche", "fraiche")
    )
    return re.sub(r"\s+", " ", s).strip()


def tokens(s: str) -> list[str]:
    return [PLURALS.get(t, t) for t in WORD.findall(norm(s))]


def generic_name(name: str) -> str:
    n = norm(name)
    return SYNONYMS.get(n, n)


@dataclass
class ProductCandidate:
    id: object
    name: str
    aliases: list[str]
    total: Decimal
    stock_unit: str
    package_size: Decimal | None
    package_unit: str | None
    next_expiry: object = None
    image_url: str | None = None
    _keys: list[list[str]] = field(default_factory=list, repr=False)

    def token_keys(self) -> list[list[str]]:
        if not self._keys:
            self._keys = [tokens(x) for x in [self.name, *self.aliases] if x]
        return self._keys


def _token_score(ing: list[str], prod: list[str]) -> float:
    if not ing or not prod:
        return 0.0
    if ing == prod:
        return 1.0
    head = ing[-1]  # "hakket løg" / "red onion": the last word names the thing
    best = 0.0
    for it in ing:
        w = 0.1 if it == head else 0.0
        for pt in prod:
            if it == pt:
                best = max(best, 0.8 + w)
            elif len(it) >= 3 and pt.endswith(it) and pt not in NOT_A_KIND_OF.get(it, set()):
                best = max(best, 0.6 + w)  # letmælk ⊃ mælk
            elif len(pt) >= 3 and it.endswith(pt) and it not in NOT_A_KIND_OF.get(pt, set()):
                best = max(best, 0.5 + w)  # hvedemel ⊃ mel (product called just "Mel")
    return best


def score(ingredient_name: str, p: ProductCandidate) -> float:
    g = generic_name(ingredient_name)
    variants = {tuple(tokens(ingredient_name)), tuple(tokens(g))}
    return max(_token_score(list(v), k) for v in variants for k in p.token_keys())


def best_match(
    ingredient_name: str, products: list[ProductCandidate], threshold: float = 0.5
) -> ProductCandidate | None:
    ranked = sorted(
        ((score(ingredient_name, p), p) for p in products),
        key=lambda x: (-x[0], x[1].total <= 0, x[1].name.lower()),
    )
    if not ranked or ranked[0][0] < threshold:
        return None
    top = ranked[0][0]
    # among equally good matches prefer one that is actually in stock
    for s, p in ranked:
        if s < top - 0.15:
            break
        if p.total > 0:
            return p
    return ranked[0][1]


def is_staple(name: str) -> bool:
    return norm(name) in STAPLES or generic_name(name) in STAPLES


def stock_in_base(p: ProductCandidate) -> tuple[str, Decimal] | None:
    """How much of the product the household has, in g / ml / count (None = unknown)."""
    if p.stock_unit in FAMILY and FAMILY[p.stock_unit][0] != "count":
        return to_base(p.total, p.stock_unit)
    if p.package_size and p.package_unit in FAMILY:
        fam, f = FAMILY[p.package_unit]
        return fam, p.total * p.package_size * f
    return "count", p.total


def needed_in_stock_units(
    quantity: Decimal | None, unit: str | None, p: ProductCandidate
) -> Decimal | None:
    """Convert a recipe amount to the product's stock unit (e.g. 2 dl of a 1 l carton = 0.2)."""
    if quantity is None:
        return None
    need = to_base(quantity, unit)
    if need is None:
        return None
    fam, amount = need
    if p.stock_unit in FAMILY and FAMILY[p.stock_unit][0] == fam and fam != "count":
        return _round(amount / FAMILY[p.stock_unit][1])
    if p.package_size and p.package_unit in FAMILY and FAMILY[p.package_unit][0] == fam:
        per_pkg = p.package_size * FAMILY[p.package_unit][1]
        if per_pkg > 0:
            return _round(amount / per_pkg)
    if fam == "count":
        return _round(amount)
    return None


def _round(d: Decimal) -> Decimal:
    return d.quantize(Decimal("0.01"), rounding=ROUND_UP)
