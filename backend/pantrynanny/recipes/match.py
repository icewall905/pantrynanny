"""Match recipe ingredients to the household's products and work out what is in stock.

Deterministic and explainable: the word that names the thing (the last word: "green *onion*",
"Ollineo Sunflower *Oil*") must agree between ingredient and product, allowing Danish compounds
such as "letmælk" ⊃ "mælk", plurals and Danish adjective endings ("finvalset" = "finvalsede");
every other meaningful ingredient word must be found in the product too ("sesame oil" is not
"Sunflower Oil"). Both sides are first rewritten with the synonym table in synonyms.txt
("olive oil" → "olivenolie"), so English recipes match a Danish pantry and vice versa. Words
after "med"/"with" only describe ("Oliven m. hvidløg" is olives); in product names so do a
trailing " - variant", ", variant", "(...)", a percentage and anything after the pack size
("Boo Chopped Tomatoes - Herbs" is chopped tomatoes). An explicit product link on the ingredient
always wins.

Staples ("always in the house": salt, pepper, water, ...) are a household list. A line is a
staple when every part of it ("salt og friskkværnet peber", "water or broth" → water) is on the
list once qualifiers like "friskkværnet", "kosher", "flage-" are dropped.
"""

import re
import unicodedata
from dataclasses import dataclass, field
from decimal import ROUND_UP, Decimal
from functools import cache
from pathlib import Path

from .parse import FAMILY, to_base

SYNONYM_FILE = Path(__file__).with_name("synonyms.txt")
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
# Compound words that end in an ingredient but are something else (also as the end of a longer
# compound: "saltkaramel", "jordnøddesmør").
# fmt: off
NOT_A_KIND_OF: dict[str, set[str]] = {
    "løg": {"hvidløg", "purløg"},
    "mælk": {"kokosmælk", "mandelmælk", "havremælk", "sojamælk", "rismælk", "kærnemælk"},
    "smør": {"mandelsmør", "nøddesmør", "peanutsmør", "jordnøddesmør", "kakaosmør", "cashewsmør"},
    "mel": {"karamel", "caramel", "krymmel", "havremel", "kokosmel", "rismel", "mandelmel",
            "kartoffelmel", "majsmel", "boghvedemel", "kikærtemel", "fuldkornshvedemel",
            "rugmel", "speltmel", "grahamsmel", "durummel", "byggmel", "maskmel"},
    "hvedemel": {"boghvedemel", "fuldkornshvedemel"},
    "ærter": {"kikærter"},
    "ost": {"kost", "frost", "rost"},
    "ris": {"pris", "gris"},
    "is": set(),
    "æble": {"granatæble"},
    "olie": {"sesamolie", "chiliolie", "trøffelolie", "kokosolie", "hvidløgsolie"},
    "sukker": {"vaniljesukker", "perlesukker", "kokossukker", "palmesukker", "muscovadosukker",
               "puddersukker", "sukkersukker"},
    "pasta": {"karrypasta", "daddelpasta", "tahinpasta", "vaniljepasta", "chilipasta",
              "rejepasta", "misopasta", "sesampasta", "tomatpasta"},
    "salt": {"hjortetaksalt", "selleri salt", "sellerisalt", "løgsalt", "hvidløgssalt"},
    "ice": {"juice", "rice", "spice", "slice"},
    "vand": {"danskvand", "kokosvand", "rosenvand", "sodavand", "appelsinblomstvand", "tonicvand"},
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
    "et", "and", "og", "some", "lidt", "mørk", "mørke", "dark", "lys", "lyse", "fine", "groft",
    "coarse", "smooth", "creamy", "stødt", "ground", "good", "god", "bio", "unsalted", "usaltet",
    "usaltede", "pure", "ren", "uncooked", "dry", "packed", "halved", "halverede",
    "afdryppede", "drained", "rinsed", "pitted", "udstenede", "quality", "full", "fat",
    "fuldkorn", "fuldkorns", "wholegrain", "flavoured", "flavored", "approx", "ca",
    # shop names that end up in product names ("Lentilles Lidl")
    "lidl", "netto", "rema", "salling", "coop", "føtex", "bilka", "irma", "meny", "spar",
    "lovbjerg", "aldi", "kvickly", "brugsen",
}
# fmt: on
# Colour words: describing, but a different colour is a different thing ("sorte bønner" are not
# "hvide bønner", "gul karrypasta" is not "rød karrypasta").
# fmt: off
COLOUR = {
    "rød": "red", "røde": "red", "grøn": "green", "grønne": "green", "gul": "yellow",
    "gule": "yellow", "hvid": "white", "hvide": "white", "sort": "black", "sorte": "black",
    "brun": "brown", "brune": "brown", "mørk": "dark", "mørke": "dark", "red": "red",
    "green": "green", "yellow": "yellow", "white": "white",
    "black": "black", "brown": "brown", "dark": "dark",
}
# fmt: on
# A product word that makes it a different thing ("Peanut butter" is not butter, "Kokos
# mælk" is not milk): such a product only matches an ingredient that says so too.
# fmt: off
CHANGES_IDENTITY = {
    "peanut", "jordnødde", "coconut", "kokos", "almond", "mandel", "cashew", "oat", "havre",
    "soy", "soja", "rice", "ris", "sour", "cocoa", "kakao", "garlic", "hvidløg", "sesame",
    "sesam", "vegan", "plant", "plante", "erstatning", "replacer", "substitute", "flavour",
    "flavor", "smag", "karry", "curry", "pickled", "syltet", "syltede", "marinated",
    "marineret", "marinerede", "ristede", "fried", "crispy", "chips", "crisps", "powder",
    "pulver", "granulat", "extract", "ekstrakt", "essens", "juice", "saft", "vanilje",
    "vanilla", "granola", "müsli", "mysli", "hakkede", "baked", "røget", "smoked", "mariniert",
    "chopped", "diced", "crushed", "flåede", "peeled",
}
# ...and so does any product word ending like this ("haveedrik kakao" is a cocoa drink)
CHANGES_IDENTITY_ENDINGS = ("drik", "drink", "pulver", "powder", "juice", "saft", "chips")
# An ingredient that is only one of these generic words ("sauce", "juice") only matches a
# product that is called just that, not any "Gochujang Sauce".
GENERIC = {"sauce", "sovs", "juice", "saft", "dressing", "krydderi", "spice", "spices", "mix"}
# fmt: on
# Package sizes and counting words ("Letmælk 1 l", "Æg 10 stk", "garlic cloves").
SIZE_WORDS = {"g", "kg", "ml", "cl", "dl", "l", "stk", "pk", "pcs", "ks", "x", "sheets", "sheet"}
# The part or form an ingredient comes in, not a different thing: "garlic cloves" and "Garlic
# bulbs" are both garlic, "fed hvidløg" is hvidløg. Dropped only when another word says what it
# is ("cloves" alone is the spice).
# fmt: off
FORM_WORDS = {
    "clove", "cloves", "bulb", "bulbs", "head", "heads", "knob", "knobs", "sprig", "sprigs",
    "stalk", "stalks", "stick", "sticks", "bunch", "bunches", "fed", "kvist", "kviste", "stilk",
    "stilke", "hoved", "hoveder",
}
# ...and as the end of a Danish compound ("hvidløgsfed", "selleristilke"). Not leaves: lime
# leaves, bay leaves and curry leaves are their own ingredient.
FORM_ENDINGS = ("fed", "kviste", "kvist", "stilke", "stilk", "stænger", "stang")
# fmt: on
# Left over at the start of English lines by the amount parser ("c. tahini", "can black beans").
# fmt: off
LEADING_JUNK = {
    "c", "cup", "cups", "can", "cans", "tin", "tins", "pint", "pints", "ounce", "ounces", "oz",
    "fl", "lb", "lbs", "pound", "pounds", "package", "packages", "pkg", "pack", "packs",
    "block", "blocks", "tbsp", "tsp", "tbls", "tablespoon", "tablespoons", "teaspoon",
    "teaspoons", "plus", "x", "jar", "jars", "bag", "bags", "box", "handful", "håndfuld",
    "dåse", "dåser", "pose", "glas", "bundt", "bdt", "stængler", "stængel", "ark",
}
# fmt: on
# A trailing generic word dropped when something more specific precedes it ("brie cheese").
GENERIC_TAIL = {"cheese", "ost"}
# Everything after these describes or offers an alternative ("Oliven m. hvidløg", "smør eller
# margarine"): cut there.
CUT = {
    "m",
    "med",
    "with",
    "w",
    "i",
    "in",
    "or",
    "eller",
    "til",
    "for",
    "på",
    "uden",
    "without",
    "such",
    "like",
    "fx",
    "eg",
}
# Danish adjective/participle and plural endings: "finvalset" = "finvalsede", "tomat" =
# "tomater", "onion" = "onions". Longest first.
ENDINGS = ("ede", "ete", "ene", "er", "es", "et", "en", "ne", "de", "te", "e", "t", "s", "r", "n")
WORD = re.compile(r"[^\W\d_]+", re.UNICODE)
# "50% Cocoa", "5% klar", "Skyr 0,2%": strength/fat descriptors, not what it is.
PERCENT = re.compile(r"\d+(?:[.,]\d+)?\s*%(?:\s*(?:cocoa|kakao|klar|fedt|fat|vol))?", re.I)
# In product names everything after the pack size is brand/marketing ("Sushi Nori 11g Blue
# Dragon"); "Æbler, grønne" / "Boo Chopped Tomatoes - Herbs" / "Bagepulver (Natron)" keep the
# main name (descriptive words such as colours after the comma are kept in front).
PACK_SIZE = re.compile(r"\s\d+(?:[.,]\d+)?\s?(?:g|kg|ml|cl|dl|l|stk)\b.*$", re.I)
PARENS = re.compile(r"\([^)]*\)")


def norm(s: str) -> str:
    s = (
        unicodedata.normalize("NFKC", s)
        .lower()
        .replace("crème", "creme")
        .replace("fraîche", "fraiche")
        .replace("purée", "puré")
    )
    return re.sub(r"\s+", " ", s).strip()


def _latin(t: str) -> bool:
    return all(ord(c) < 0x250 for c in t)  # "Gochugaru Fine 고추가루": the Korean is a label


def tokens(s: str) -> list[str]:
    return [PLURALS.get(t, t) for t in WORD.findall(norm(s)) if _latin(t)]


@cache
def _rules() -> tuple[
    dict[str, list[str]],
    dict[tuple[str, ...], list[str]],
    list[tuple[tuple[str, ...], list[str]]],
    list[tuple[list[str], list[str]]],
]:
    words: dict[str, list[str]] = {}
    phrases: dict[tuple[str, ...], list[str]] = {}
    kinds: list[tuple[tuple[str, ...], list[str]]] = []
    swaps: list[tuple[list[str], list[str]]] = []
    lines = [ln.split("#", 1)[0].strip() for ln in SYNONYM_FILE.read_text().splitlines()]
    rules = []
    for ln in lines:
        for sep in ("=", ">", "~"):
            if sep in ln:
                left, right = ln.split(sep, 1)
                rules.append((sep, tokens(left), tokens(right)))
                break
    for sep, left, right in rules:
        if sep == "=" and len(left) == 1:
            words[left[0]] = right
    for sep, left, right in rules:  # phrases see the words already rewritten
        if sep == "~":
            continue
        left, right = _words(left, words), _words(right, words)
        if sep == ">":
            kinds.append((tuple(left), right))
        elif len(left) > 1:
            phrases[tuple(left)] = right
    for sep, left, right in rules:  # substitutes see words and phrases already rewritten
        if sep == "~":
            swaps.append((left, right))
    return words, phrases, kinds, swaps


def _words(toks: list[str], words: dict[str, list[str]]) -> list[str]:
    return [PLURALS.get(w, w) for t in toks for w in words.get(t, [t])]


def canonical(toks: list[str]) -> list[str]:
    """Rewrite with the synonym table: single words first, then phrases (longest first)."""
    words, phrases, *_ = _rules()
    toks = _words(toks, words)
    out: list[str] = []
    i = 0
    while i < len(toks):
        for n in (3, 2, 1):
            key = tuple(toks[i : i + n])
            if len(key) == n and key in phrases:
                out += phrases[key]
                i += n
                break
        else:
            out.append(toks[i])
            i += 1
    return [PLURALS.get(t, t) for t in out]


def core(toks: list[str]) -> list[str]:
    """The words that say what it is: before any connector, without trailing size/filler."""
    for i, t in enumerate(toks):
        if i and t in CUT:
            toks = toks[:i]
            break
    toks = [_unform(t) for t in toks if t not in SIZE_WORDS]
    if any(t not in FORM_WORDS and t not in FILLER for t in toks):
        toks = [t for t in toks if t not in FORM_WORDS]
    while toks and toks[-1] in FILLER:
        toks = toks[:-1]
    if len(toks) > 1 and toks[-1] in GENERIC_TAIL:
        toks = toks[:-1]
    return toks


def _unform(t: str) -> str:
    """ "hvidløgsfed" → hvidløg, "kanelstang" → kanel."""
    for e in FORM_ENDINGS:
        if t.endswith(e) and len(t) - len(e) >= 4:
            head = t[: -len(e)]
            return head[:-1] if head.endswith("s") and len(head) > 4 else head
    return t


def _strip_leading_junk(toks: list[str]) -> list[str]:
    i = 0
    while i < len(toks) - 1 and toks[i] in LEADING_JUNK:
        i += 1
    return toks[i:]


def product_tokens(name: str) -> list[str]:
    """A product name reduced to its main name ("Sushi Nori 11g Blue Dragon" → sushi nori)."""
    s = PERCENT.sub(" ", PARENS.sub(" ", norm(name)))
    s = PACK_SIZE.sub("", " " + s)
    parts = re.split(r"\s-\s|,", s, maxsplit=1)
    main, tail = parts[0], parts[1] if len(parts) > 1 else ""
    extra = [t for t in tokens(tail) if t in FILLER]  # "Æbler, grønne" → grønne æbler
    return extra + tokens(main)


def generic_name(name: str) -> str:
    return " ".join(canonical(tokens(name)))


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
    _described: set[str] = field(default_factory=set, repr=False)

    def described(self) -> set[str]:
        """Describing words in the name ("light" in "Coconut Milk Light")."""
        if not self._keys:
            self.token_keys()
        return self._described

    def token_keys(self) -> list[list[str]]:
        if not self._keys:
            keys: list[list[str]] = []
            for x in [self.name, *self.aliases]:
                if not x:
                    continue
                raw = product_tokens(x)
                if x == self.name:
                    self._described = {t for t in raw if t in FILLER} - set(COLOUR)
                for k in (core(raw), core(canonical(raw))):
                    if k and k not in keys:
                        keys.append(k)
            for k in list(keys):
                for left, right in _rules()[2]:
                    if tuple(k[-len(left) :]) == left and right not in keys:
                        keys.append(list(right))
            self._keys = keys
        return self._keys


def _stem(w: str) -> str:
    for e in ENDINGS:
        if len(w) - len(e) >= 4 and w.endswith(e):
            return w[: -len(e)]
    return w


def _same(a: str, b: str) -> bool:
    # jasmin/jasmine, tomato/tomatoes, onion/onions, finvalset/finvalsede (not tamari/tamarind)
    if a == b:
        return True
    short, long_ = sorted((a, b), key=len)
    if len(short) < 4:
        return False
    if long_.startswith(short) and long_[len(short) :] in ENDINGS:
        return True
    return _stem(a) == _stem(b) and len(_stem(a)) >= 4


def _trap(compound: str, word: str) -> bool:
    # "saltkaramel" ends in "karamel" just as surely as "karamel" does
    return any(compound.endswith(x) for x in NOT_A_KIND_OF.get(word, ()))


def _joins(prefix: str, word: str) -> bool:
    """`prefix` is the first half of a compound: "vanilje"+"sukker", "fuldkorns"+"spaghetti"."""
    return bool(prefix) and (
        _same(prefix, word)
        or (prefix[-1] in "se" and _same(prefix[:-1], word))
        or (len(prefix) >= 4 and word.startswith(prefix))
    )


def _ends(compound: str, word: str) -> int:
    """Length of the part of `compound` before `word` (allowing an ending on it), or 0:
    "blommetomater" ends in "tomat" after "blomme"."""
    for e in ("", *ENDINGS):
        w = word + e
        if len(compound) - len(w) >= 3 and compound.endswith(w):
            return len(compound) - len(w)
    return 0


def _head_score(ih: str, ph: str, mods: list[str], prod: list[str]) -> float:
    if _same(ih, ph):
        return 1.0
    # a real compound (let+mælk), not an accident of spelling (r+ice)
    if len(ih) >= 3 and (n := _ends(ph, ih)) and not _trap(ph, ih):
        if any(_same(m, ph[:n]) or m == ph[:n] for m in mods):
            return 1.0  # "rød løg" = "Rødløg"
        return 0.85  # letmælk ⊃ mælk
    if len(ph) >= 3 and (n := _ends(ih, ph)):
        if len(prod) > 1 and _joins(ih[:n], prod[-2]):
            return 1.0  # "vaniljesukker" = "Vanilje sukker", "jasminris" = "Jasmine rice"
        if len(prod) == 1 and not _trap(ih, ph):
            return 0.75  # hvedemel ⊃ mel, only for a product called just "Mel"
    return 0.0


def _found(word: str, prod: list[str]) -> bool:
    # "olive" in "olivenolie", "rød" in "rødløg"
    return any(_same(word, pt) or (len(word) >= 3 and pt.startswith(word)) for pt in prod)


COLOUR_PREFIX = {"rød": "red", "grøn": "green", "gul": "yellow", "hvid": "white", "sort": "black"}


def _colours(toks: list[str]) -> set[str]:
    out = set()
    for t in toks:
        if t in COLOUR:
            out.add(COLOUR[t])
        else:  # "rødløg", "hvidvin"
            out |= {c for p, c in COLOUR_PREFIX.items() if t.startswith(p) and len(t) - len(p) >= 3}
    return out


def _token_score(ing: list[str], prod: list[str], colours: set[str] | None = None) -> float:
    """Both sides already reduced with core(); `colours` are the product's under any name."""
    head = _head_score(ing[-1], prod[-1], ing[:-1], prod)
    if not head:
        return 0.0
    mods = [t for t in ing[:-1] if t not in FILLER]
    if not all(_found(t, prod) for t in mods):
        return 0.0
    if any(
        (t in CHANGES_IDENTITY or t.endswith(CHANGES_IDENTITY_ENDINGS)) and not _found(t, ing)
        for t in prod[:-1]
    ):
        return 0.0
    if len(ing) == 1 and ing[0] in GENERIC and len(prod) > 1:
        return 0.0
    # a colour the recipe asks for must be the product's ("brune ris" is not Jasmine rice,
    # "sorte bønner" are not "hvide bønner")
    ic, pc = _colours(ing), _colours(prod) | (colours or set())
    if ic and not ic & pc:
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
            if i == 1 and toks[0] in FILLER and rest:
                return rest[1:] if rest[0] in FILLER and len(rest) > 1 else rest  # fresh or frozen
            if i == 1 and len(rest) > 1:
                return [toks[0], rest[-1]]
            return toks[:i]
    return toks


ELIDED = re.compile(r"\w+-\s+(?:eller|or)\s+")  # "kage- eller hvedemel": take the second


def _variants(ingredient_name: str) -> list[list[str]]:
    toks = _first_choice(_strip_leading_junk(tokens(ELIDED.sub("", norm(ingredient_name)))))
    variants = {tuple(toks), tuple(canonical(toks))}
    return [c for v in variants if (c := core(list(v)))]


def _score(variants: list[list[str]], p: ProductCandidate) -> float:
    keys = p.token_keys()
    colours = {c for k in keys for c in _colours(k)}  # cannellini beans are white beans
    best = max((_token_score(v, k, colours) for v in variants for k in keys), default=0.0)
    if best:  # "full-fat coconut milk" prefers plain Kokosmælk to "Coconut Milk Light"
        asked = {t for v in variants for t in v}
        best -= 0.03 * sum(1 for t in p.described() if not _found(t, list(asked)))
    return best


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


# --------------------------------------------------------------------------- substitutes


def ingredient_key(ingredient_name: str) -> str:
    """What an ingredient line asks for, as a stable key ("2 fed hvidløg" → hvidløg): the key a
    household's approved substitutes are stored under."""
    toks = _first_choice(_strip_leading_junk(tokens(ELIDED.sub("", norm(ingredient_name)))))
    return " ".join(core(canonical(toks)) or core(toks))


@cache
def _swap_rules() -> list[tuple[list[str], str]]:
    """`a ~ b` lines: the ingredient (as reduced keys) and what can stand in for it."""
    out = []
    for left, right in _rules()[3]:
        k = ingredient_key(" ".join(left))
        if k:
            out.append((k.split(), " ".join(right)))
    return out


def best_substitute(
    ingredient_name: str,
    products: list[ProductCandidate],
    approved: dict[str, list[object]] | None = None,
) -> ProductCandidate | None:
    """An in-stock product that can stand in when the ingredient itself is not in the house:
    the household's approved swaps first (by product id), then the built-in `a ~ b` rules."""
    if isinstance(products, Pantry):
        return products.substitute(ingredient_name)
    key = ingredient_key(ingredient_name)
    if not key:
        return None
    by_id = {p.id: p for p in products}
    for pid in (approved or {}).get(key, []):
        p = by_id.get(pid)
        if p is not None and p.total > 0:
            return p
    asked = key.split()
    for left, right in _swap_rules():
        if _token_score(asked, left) < 0.5:
            continue
        p = best_match(right, [p for p in products if p.total > 0])
        if p is not None:
            return p
    return None


# --------------------------------------------------------------------------- staples

# Seed for a household's "always in the house" list (editable in Admin -> Settings).
# fmt: off
DEFAULT_STAPLES = [
    "salt", "peber", "vand", "isterninger", "olie", "neutral olie", "olivenolie", "sukker",
    "hvedemel", "bagepulver", "natron", "stødt spidskommen", "stødt kanel", "paprika",
    "røget paprika", "sød paprika", "stødt gurkemeje", "tørret timian", "tørret oregano",
    "stødt koriander", "chiliflager", "cayennepeber", "laurbærblade", "muskatnød", "karry",
    "stødt ingefær", "stødt kardemomme",
]
# Dropped before a line is compared with the staple list: "friskkværnet peber" is pepper,
# "kosher salt" and "flagesalt" are salt, "kogende vand" is water.
STAPLE_QUALIFIERS = {
    "friskkværnet", "friskkværnede", "kværnet", "kværnede", "nykværnet", "fint", "fine",
    "finely", "groft", "groftkværnet", "coarse", "coarsely", "kosher", "flaky", "flage", "sea",
    "hav", "freshly", "fresh", "frisk", "ground", "stødt", "cracked", "finkornet", "kogende",
    "koldt", "kold", "lunkent", "lunken", "varmt", "varm", "iskoldt", "iskold", "boiling",
    "cold", "warm", "hot", "lukewarm", "ice", "black", "sort", "sorte", "hvid", "white", "taste",
    "to", "smag", "efter", "evt", "lidt",
    "a", "pinch", "of", "knivspids", "dash", "some", "more", "needed", "as", "for",
    "serving", "servering", "the",
}
STAPLE_COMPOUNDS = {
    "flagesalt": "salt", "havsalt": "salt", "finsalt": "salt", "grovsalt": "salt",
    "bordsalt": "salt", "isvand": "vand", "postevand": "vand", "kildevand": "vand",
}
# fmt: on
_AND = re.compile(r"\s+(?:og|and|&|\+)\s+|\s*&\s*|,\s*")
_OR = re.compile(r"\s+(?:or|eller)\s+|\s*/\s*")


def _staple_parts(name: str) -> list[str]:
    """ "salt og friskkværnet peber" → [salt, peber]; "water or broth" → [water]."""
    out = []
    for part in _AND.split(norm(name)):
        first = _OR.split(part)[0]
        words = [t for t in tokens(first) if t not in STAPLE_QUALIFIERS]
        if not words:  # "coarse or flaky sea salt": the alternatives were only qualifiers
            words = [t for t in tokens(part) if t not in STAPLE_QUALIFIERS | {"or", "eller"}]
        words = [STAPLE_COMPOUNDS.get(w, w) for w in words]  # "flagesalt" → salt
        if words:
            out.append(" ".join(words))
    return out


class Staples:
    """A household's "always in the house" list, matched with the same rules as products."""

    def __init__(self, names: list[str] | None = None):
        names = DEFAULT_STAPLES if names is None else names
        self.names = [n for n in dict.fromkeys(norm(n) for n in names) if n]
        self._pantry = Pantry(
            [
                ProductCandidate(
                    id=i,
                    name=n,
                    aliases=[],
                    total=Decimal(1),
                    stock_unit="pcs",
                    package_size=None,
                    package_unit=None,
                )
                for i, n in enumerate(self.names)
            ],
            staples=False,
        )
        self._exact = set(self.names) | {" ".join(canonical(tokens(n))) for n in self.names}
        self._cache: dict[str, bool] = {}

    def _one(self, part: str) -> bool:
        if part in self._exact or " ".join(canonical(tokens(part))) in self._exact:
            return True
        return self._pantry.best(part, 0.7) is not None

    def __contains__(self, name: str) -> bool:
        key = norm(name)
        if key not in self._cache:
            parts = _staple_parts(key)
            self._cache[key] = bool(parts) and all(self._one(p) for p in parts)
        return self._cache[key]


class Pantry(list[ProductCandidate]):
    """The household's products for one request; remembers each ingredient name's match
    (thousands of recipes share "salt", "hvidløg", ...) and only scores products whose head
    word could agree with the ingredient's. Also carries the household's staples list."""

    def __init__(
        self,
        products: list[ProductCandidate],
        staples: "Staples | list[str] | bool | None" = None,
        substitutes: dict[str, list[object]] | None = None,
    ):
        super().__init__(products)
        self.substitutes = substitutes or {}
        self._swap: dict[str, ProductCandidate | None] = {}
        if staples is False:
            self.staples = None
        else:
            self.staples = staples if isinstance(staples, Staples) else _staples(staples)
        self._best: dict[tuple[str, float], ProductCandidate | None] = {}
        # every way _head_score/_same can relate two heads, as dictionary lookups:
        # ph itself, ph's suffixes (ph ⊃ ih) and ph's stems (onions/onion, finvalsede/finvalset)
        self._by_key: dict[str, list[ProductCandidate]] = {}
        for p in products:
            for ph in {k[-1] for k in p.token_keys()}:
                keys = {x[i:] for x in {ph} | _shorter(ph) for i in range(len(x) - 2)}
                for key in keys | {ph}:
                    self._by_key.setdefault(key, []).append(p)

    def _candidates(self, ingredient_name: str) -> list[ProductCandidate]:
        found: dict[int, ProductCandidate] = {}
        for v in _variants(ingredient_name):
            ih = v[-1]
            # ih itself (same / ph ⊃ ih / ph = ih minus an ending), ih's suffixes (ih ⊃ ph) and
            # ih's stems (ph = onions for ih = onion is ph's own key above)
            keys = {ih, *(ih[i:] for i in range(1, len(ih) - 2))} | _shorter(ih)
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

    def substitute(self, ingredient_name: str) -> ProductCandidate | None:
        key = norm(ingredient_name)
        if key not in self._swap:
            self._swap[key] = best_substitute(ingredient_name, list(self), self.substitutes)
        return self._swap[key]

    def is_staple(self, name: str) -> bool:
        return self.staples is not None and name in self.staples


def _shorter(w: str) -> set[str]:
    # the forms _same() can reach from w by dropping an ending: tomater → tomat, -ede → stem
    out = {w[: -len(e)] for e in ENDINGS if len(w) - len(e) >= 4 and w.endswith(e)}
    return out | {_stem(x) for x in out}


@cache
def _default_staples() -> Staples:
    return Staples()


def _staples(names: list[str] | None) -> Staples:
    return _default_staples() if names is None else Staples(names)


def is_staple(name: str, staples: Staples | None = None) -> bool:
    return name in (staples or _default_staples())


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


# What one counted piece is: "3 cloves" of garlic are not 3 of the household's garlic bulbs.
FORM_GROUP = {
    "clove": "clove", "cloves": "clove", "fed": "clove",
    "bulb": "head", "bulbs": "head", "head": "head", "heads": "head", "hoved": "head",
    "hoveder": "head", "knold": "head",
    "stalk": "stalk", "stalks": "stalk", "stilk": "stalk", "stilke": "stalk",
    "stick": "stick", "sticks": "stick", "stang": "stick", "stænger": "stick",
    "sprig": "sprig", "sprigs": "sprig", "kvist": "sprig", "kviste": "sprig",
    "knob": "knob", "knobs": "knob", "bunch": "bunch", "bunches": "bunch", "bundt": "bunch",
}  # fmt: skip


def _forms(words: list[str]) -> set[str]:
    out = set()
    for w in words:
        if w in FORM_GROUP:
            out.add(FORM_GROUP[w])
        else:
            out |= {FORM_GROUP[e] for e in FORM_ENDINGS if w.endswith(e) and len(w) - len(e) >= 4}
    return out


def counts_compare(ingredient_name: str, unit: str | None, p: ProductCandidate) -> bool:
    """False when the recipe counts a part the product is not counted in (cloves vs. bulbs):
    the amount then cannot be checked, only that it is in the house."""
    asked = _forms(tokens(ingredient_name) + ([unit.lower()] if unit else []))
    if not asked:
        return True
    return asked <= _forms(product_tokens(p.name))


def _round(d: Decimal) -> Decimal:
    return d.quantize(Decimal("0.01"), rounding=ROUND_UP)
