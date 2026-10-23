"""Match recipe ingredients to the household's products and work out what is in stock.

Deterministic and explainable: the word that names the thing (the last word: "green *onion*",
"Ollineo Sunflower *Oil*") must agree between ingredient and product, allowing Danish compounds
such as "letmælk" ⊃ "mælk" and a small Danish/English synonym table; every other meaningful
ingredient word must be found in the product too ("sesame oil" is not "Sunflower Oil"). Words
after "med"/"with" only describe ("Oliven m. hvidløg" is olives). An explicit product link on
the ingredient always wins.
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
    "soy sauce": "soja sauce",
    "soy": "soja",
    "spring onion": "forårsløg",
    "green onion": "forårsløg",
    "scallion": "forårsløg",
    "scallions": "forårsløg",
    "coconut": "kokos",
    "almond": "mandel",
    "oat": "havre",
    "peanut": "jordnødde",
    "red": "rød",
    "green": "grøn",
    "white": "hvid",
    "yellow": "gul",
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
# Compound words that end in an ingredient but are something else (also as the end of a longer
# compound: "saltkaramel", "jordnøddesmør").
# fmt: off
NOT_A_KIND_OF: dict[str, set[str]] = {
    "løg": {"hvidløg", "purløg"},
    "mælk": {"kokosmælk", "mandelmælk", "havremælk", "sojamælk", "rismælk", "kærnemælk"},
    "smør": {"mandelsmør", "nøddesmør", "peanutsmør", "kakaosmør", "cashewsmør"},
    "mel": {"karamel", "caramel", "krymmel", "havremel", "kokosmel", "rismel", "mandelmel",
            "kartoffelmel", "majsmel", "boghvedemel", "kikærtemel"},
    "hvedemel": {"boghvedemel"},
    "ærter": {"kikærter"},
    "ost": {"kost", "frost", "rost"},
    "ris": {"pris", "gris"},
    "is": set(),
}
# fmt: on
# Describe an ingredient without changing what it is: neither needed nor penalised.
# fmt: off
FILLER = {
    "fresh", "frisk", "friske", "frozen", "frossen", "frosne", "large", "small", "medium",
    "big", "stor", "store", "stort", "lille", "små", "mellem", "cooked", "kogt", "kogte",
    "chopped", "hakket", "hakkede", "finthakket", "finthakkede", "finely", "fint", "minced",
    "diced", "sliced", "skåret", "skiver", "grated", "revet", "revne", "ripe", "moden", "modne",
    "organic", "økologisk", "økologiske", "øko", "whole", "hel", "hele", "peeled", "skrællet",
    "skrællede", "boiled", "leftover", "raw", "rå", "dried", "tørret", "tørrede", "light",
    "extra", "ekstra", "virgin", "jomfru", "plain", "naturel", "natural", "red", "rød", "røde",
    "green", "grøn", "grønne", "yellow", "gul", "gule", "white", "hvid", "hvide", "black",
    "sort", "sorte", "brown", "brun", "brune", "day", "old", "a", "an", "the", "of", "af", "en",
    "et", "and", "og", "some", "lidt",
}
# fmt: on
# A product word that makes it a different thing ("Peanut butter" is not butter, "Kokos
# mælk" is not milk): such a product only matches an ingredient that says so too.
# fmt: off
CHANGES_IDENTITY = {
    "peanut", "jordnødde", "coconut", "kokos", "almond", "mandel", "cashew", "oat", "havre",
    "soy", "soja", "rice", "ris", "sour", "cocoa", "kakao", "garlic", "hvidløg", "sesame",
    "sesam", "vegan", "plant", "plante", "erstatning", "replacer", "substitute", "flavour",
    "flavor", "smag", "karry", "curry",
}
# fmt: on
# Package sizes at the end of product names ("Letmælk 1 l", "Æg 10 stk").
SIZE_WORDS = {"g", "kg", "ml", "cl", "dl", "l", "stk", "pk", "pcs", "ks", "x"}
# Everything after these describes or offers an alternative ("Oliven m. hvidløg", "smør eller
# margarine"): cut there.
CUT = {"m", "med", "with", "w", "i", "in", "or", "eller", "til", "for"}
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


def core(toks: list[str]) -> list[str]:
    """The words that say what it is: before any connector, without trailing size/filler."""
    for i, t in enumerate(toks):
        if i and t in CUT:
            toks = toks[:i]
            break
    toks = [t for t in toks if t not in SIZE_WORDS]
    while toks and toks[-1] in FILLER:
        toks = toks[:-1]
    return toks


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
            self._keys = [k for x in [self.name, *self.aliases] if x and (k := core(tokens(x)))]
        return self._keys


def _same(a: str, b: str) -> bool:
    # jasmin/jasmine, tomato/tomatoes, onion/onions
    if a == b:
        return True
    short, long_ = sorted((a, b), key=len)
    return len(short) >= 4 and long_.startswith(short) and len(long_) - len(short) <= 2


def _trap(compound: str, word: str) -> bool:
    # "saltkaramel" ends in "karamel" just as surely as "karamel" does
    return any(compound.endswith(x) for x in NOT_A_KIND_OF.get(word, ()))


def _head_score(ih: str, ph: str, mods: list[str], plain: bool) -> float:
    if _same(ih, ph):
        return 1.0
    # a real compound (let+mælk), not an accident of spelling (r+ice)
    if len(ih) >= 3 and len(ph) - len(ih) >= 3 and ph.endswith(ih) and not _trap(ph, ih):
        if any(m + ih == ph for m in mods):
            return 1.0  # "rød løg" = "Rødløg"
        return 0.85  # letmælk ⊃ mælk
    if plain and len(ph) >= 3 and len(ih) - len(ph) >= 3 and ih.endswith(ph) and not _trap(ih, ph):
        return 0.75  # hvedemel ⊃ mel, only for a product called just "Mel"
    return 0.0


def _found(word: str, prod: list[str]) -> bool:
    # "olive" in "olivenolie", "rød" in "rødløg"
    return any(_same(word, pt) or (len(word) >= 3 and pt.startswith(word)) for pt in prod)


def _token_score(ing: list[str], prod: list[str]) -> float:
    """Both sides already reduced with core()."""
    head = _head_score(ing[-1], prod[-1], ing[:-1], len(prod) == 1)
    if not head:
        return 0.0
    mods = [t for t in ing[:-1] if t not in FILLER]
    if not all(_found(t, prod) for t in mods):
        return 0.0
    if any(t in CHANGES_IDENTITY and not _found(t, ing) for t in prod[:-1]):
        return 0.0
    # describing words that the product also has ("red" onion → Rødløg) tip the balance
    described = sum(_found(t, prod) for t in ing[:-1] if t in FILLER)
    extra = max(0, len(prod) - 1 - len(mods))  # brand names etc.: a slight tie-breaker only
    return head + 0.05 * (len(mods) + described) - 0.02 * min(extra, 5)


def _first_choice(toks: list[str]) -> list[str]:
    """ "olive or rapeseed oil" → olive oil (a lone word before "or" shares the last noun)."""
    for i, t in enumerate(toks):
        if i and t in {"or", "eller"}:
            rest = toks[i + 1 :]
            if i == 1 and len(rest) > 1:
                return [toks[0], rest[-1]]
            return toks[:i]
    return toks


def _variants(ingredient_name: str) -> list[list[str]]:
    toks = _first_choice(tokens(ingredient_name))
    variants = {
        tuple(toks),
        tuple(_first_choice(tokens(generic_name(ingredient_name)))),
        tuple(PLURALS.get(SYNONYMS.get(t, t), SYNONYMS.get(t, t)) for t in toks),  # green løg
    }
    return [c for v in variants if (c := core(list(v)))]


def _score(variants: list[list[str]], p: ProductCandidate) -> float:
    return max((_token_score(v, k) for v in variants for k in p.token_keys()), default=0.0)


def score(ingredient_name: str, p: ProductCandidate) -> float:
    return _score(_variants(ingredient_name), p)


def best_match(
    ingredient_name: str, products: list[ProductCandidate], threshold: float = 0.5
) -> ProductCandidate | None:
    if isinstance(products, Pantry):
        return products.best(ingredient_name, threshold)
    variants = _variants(ingredient_name)
    ranked = sorted(
        ((_score(variants, p), p) for p in products),
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


class Pantry(list[ProductCandidate]):
    """The household's products for one request; remembers each ingredient name's match
    (thousands of recipes share "salt", "hvidløg", ...) and only scores products whose head
    word could agree with the ingredient's."""

    def __init__(self, products: list[ProductCandidate]):
        super().__init__(products)
        self._best: dict[tuple[str, float], ProductCandidate | None] = {}
        # every way _head_score/_same can relate two heads, as dictionary lookups:
        # ph itself, ph's suffixes (ph ⊃ ih) and ph minus up to two letters (onions/onion)
        self._by_key: dict[str, list[ProductCandidate]] = {}
        for p in products:
            for ph in {k[-1] for k in p.token_keys()}:
                keys = {ph[i:] for i in range(len(ph) - 2)} | {ph[: len(ph) - n] for n in (1, 2)}
                for key in keys | {ph}:
                    self._by_key.setdefault(key, []).append(p)

    def _candidates(self, ingredient_name: str) -> list[ProductCandidate]:
        found: dict[int, ProductCandidate] = {}
        for v in _variants(ingredient_name):
            ih = v[-1]
            # ih itself (same / ph ⊃ ih / ph = ih minus letters), ih's suffixes (ih ⊃ ph) and
            # ih minus up to two letters (ph = onions for ih = onion is ph's own key above)
            keys = {ih, *(ih[i:] for i in range(1, len(ih) - 2))}
            keys |= {ih[: len(ih) - n] for n in (1, 2)}
            for key in keys:
                for p in self._by_key.get(key, ()):
                    found[id(p)] = p
        return list(found.values())

    def best(self, ingredient_name: str, threshold: float = 0.5) -> ProductCandidate | None:
        key = (norm(ingredient_name), threshold)
        if key not in self._best:
            self._best[key] = best_match(
                ingredient_name, self._candidates(ingredient_name), threshold
            )
        return self._best[key]


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
