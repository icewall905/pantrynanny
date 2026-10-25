"""What kind of dish a recipe is (breakfast, dinner, dessert, ...), so "what can we cook for
dinner" can leave out syrups and sweets.

Deterministic, in this order:
1. The page's own schema.org recipeCategory/keywords (kept as tags), e.g. "Dessert", "Aftensmad".
2. The title: the word that names the dish, i.e. the last word before "med"/"with" ("Kylling med
   honning og sennep" is chicken, "Gulerodssuppe med kokosmælk" is soup, "Jordbærroulade" ends in
   roulade). A vegetable/potato/salad head with meat, fish or tofu elsewhere in the title is a
   meal ("Sheet-Pan Balsamic Chicken & Asparagus").
3. The ingredients, only when the title says nothing: alcohol → drink, mostly sugar/chocolate →
   dessert, meat/fish/pulses → dinner.
Unknown stays None. The household can change any recipe's course; nothing here overwrites that.
"""

import re

from .match import norm

COURSES = (
    "breakfast",
    "lunch",
    "dinner",
    "side",
    "dessert",
    "baking",
    "drink",
    "snack",
    "condiment",
)

# schema.org recipeCategory / keywords seen on Danish and English recipe sites
# fmt: off
CATEGORY: dict[str, str] = {
    "breakfast": "breakfast", "morgenmad": "breakfast", "brunch": "breakfast",
    "lunch": "lunch", "frokost": "lunch", "frokostretter": "lunch", "smørrebrød": "lunch",
    "dinner": "dinner", "aftensmad": "dinner", "main course": "dinner", "main dish": "dinner",
    "main": "dinner", "mains": "dinner", "hovedret": "dinner", "hovedretter": "dinner",
    "entree": "dinner", "entrée": "dinner", "supper": "dinner", "aftensmadsretter": "dinner",
    "side": "side", "side dish": "side", "sides": "side", "tilbehør": "side", "salad": "side",
    "appetizer": "side", "starter": "side", "forret": "side", "forretter": "side",
    "dessert": "dessert", "desserts": "dessert", "desert": "dessert", "is": "dessert",
    "baking": "baking", "bagning": "baking", "bagværk": "baking", "kage": "baking",
    "kager": "baking", "cake": "baking", "bread": "baking", "brød": "baking",
    "cookies": "baking", "småkager": "baking",
    "drink": "drink", "drinks": "drink", "beverage": "drink", "beverages": "drink",
    "cocktail": "drink", "cocktails": "drink", "drikke": "drink", "drikkevarer": "drink",
    "smoothie": "drink", "smoothies": "drink",
    "snack": "snack", "snacks": "snack", "slik": "snack", "konfekt": "snack", "candy": "snack",
    "sauce": "condiment", "sauces": "condiment", "dressing": "condiment", "dip": "condiment",
    "condiment": "condiment", "condiments": "condiment", "sovs": "condiment",
    "tilbehør og saucer": "condiment",
    # valdemarsro.dk and other Danish sites
    "tilbehør aftensmad": "side", "salater": "side", "brød & boller": "baking",
    "brød og boller": "baking", "boller": "baking", "madbrød": "baking",
    "småkager og kiks": "baking",
    "kager & bagværk": "baking", "desserter & is": "dessert", "desserter og is": "dessert",
    "pålægssalat": "lunch", "pålæg": "lunch", "frokostretter og pålæg": "lunch",
    "dressinger": "condiment", "saucer": "condiment", "syltning": "condiment",
    "marmelade": "condiment", "syltetøj": "condiment", "dips": "condiment",
    "konfekt & slik": "snack",
    "snacks & småt": "snack", "gløgg": "drink", "drinks & cocktails": "drink",
    "breakfast and brunch": "breakfast", "dinners": "dinner", "salads": "side",
}
# When a page lists several categories, the more specific kind of dish wins ("Brød & Boller" +
# "Tilbehør Aftensmad" is baking, "Forretter" + "Frokost" is lunch).
TAG_PRIORITY = (
    "drink", "condiment", "baking", "dessert", "snack", "breakfast", "lunch", "side", "dinner"
)
# fmt: on

# Words that name the dish. Matched as the whole word or the end of a Danish compound
# ("rabarbersaft" ends in "saft"); short words only as a whole word.
# fmt: off
HEADS: dict[str, tuple[str, ...]] = {
    "drink": (
        "smoothie", "smoothies", "juice", "saft", "shake", "milkshake", "latte", "kaffe",
        "coffee", "cocktail", "cocktails", "mojito", "martini", "margarita", "mule", "drink",
        "drinks", "lemonade", "limonade", "punch", "gløgg", "spritz", "mimosa", "kakao",
        "whiskey", "whisky", "milk", "sangria", "toddy", "chai", "iste", "iskaffe", "colada",
    ),
    "condiment": (
        "sauce", "sovs", "dressing", "dip", "pesto", "salsa", "chutney", "marmelade",
        "syltetøj", "gele", "sirup", "syrup", "krydderi", "krydderier", "krydderiblanding",
        "aioli", "mayonnaise", "mayo", "remoulade", "ketchup", "gravy", "hummus", "guacamole",
        "tzatziki", "chimichurri", "relish", "frosting", "glasur", "icing", "seasoning",
        "bearnaise", "ghanoush", "ganoush", "vinaigrette", "pickles", "spread", "smørepålæg",
        "nutella", "compote", "kompot", "coulis", "karamelsauce", "tahinsauce", "rub",
        "marinade", "smør", "butter", "jam", "jelly", "curd", "spice mix", "krydderiblanding",
        "raita", "ajvar", "olie", "oil",
    ),
    "baking": (
        "kage", "kager", "boller", "bolle", "brød", "muffins", "muffin", "cookies", "cookie",
        "småkager", "scones", "kiks", "cake", "cakes", "bread", "buns", "rolls", "cupcakes",
        "cupcake", "brownies", "brownie", "bars", "roulade", "snitter", "croissant",
        "croissanter", "focaccia", "foccacia", "dough", "dej", "pizzadej", "loaf", "kringle",
        "wienerbrød", "kranse", "snegle", "gateau", "biscotti", "flapjacks", "rundstykker",
        "baguette", "pitabrød", "naan", "tortillas", "wrappers", "kagemand", "måne",
        "lagkage", "tærtebund", "madeleines", "macarons", "meringue", "marengs", "napoleonshatte",
        "biscuits", "scone", "kammerjunkere", "specier", "drømmekage", "sandkage", "kanelsnegle",
        "fastelavnsboller",
    ),
    "dessert": (
        "dessert", "pudding", "mousse", "trifli", "triffli", "crumble", "cobbler",
        "cheesecake", "tiramisu", "pannacotta", "parfait", "fromage", "koldskål", "risalamande",
        "sundae", "sorbet", "granita", "flødeis", "vaniljeis", "chokoladeis", "lakridsis",
        "islagkage", "is", "clafoutis", "pie", "tart", "trifle", "custard", "brûlée", "brulee",
        "frugtsalat", "æblegrød", "rødgrød", "pandekagekage", "creme", "crème", "sticky rice",
        "æbleskiver", "churros", "jello", "gelé", "nicecream", "popsicles", "ispinde", "tarte",
        "tatin",
    ),
    "snack": (
        "konfekt", "karameller", "karamel", "fudge", "trøfler", "nougat", "marcipan",
        "rocky road", "bounty", "snickers", "chips", "popcorn", "nødder", "mandler",
        "energikugler", "kugler", "bites", "balls", "bar", "barer", "müslibar", "brud",
        "samosa", "samosas", "snack", "snacks", "crackers", "knækbrød", "deviled eggs",
        "fyldte æg", "spring rolls", "forårsruller", "nuggets", "lakrids", "slik",
    ),
    "breakfast": (
        "grød", "porridge", "oats", "overnight oats", "granola", "müsli", "mysli",
        "pandekager", "pandekage", "pancakes", "pancake", "waffles", "waffle", "vafler",
        "vaffel", "omelet", "omelette", "scrambled eggs", "røræg", "french toast", "breakfast",
        "morgenmad", "brunch", "smoothieskål", "smoothie bowl", "chia", "chiagrød", "frittata",
        "shakshuka", "bagel", "bagels", "toast", "æggekage", "crepes", "crêpes",
    ),
    "lunch": (
        "sandwich", "sandwiches", "wrap", "wraps", "smørrebrød", "pålæg", "quiche", "tatar",
        "hotdog", "hotdogs", "panini", "toast", "frokost", "lunch", "pitabread",
        "tarteletter", "bruschetta",
    ),
    "side": (
        "salat", "salad", "salade", "kartofler", "potatoes", "kartoffelmos", "mos", "mash",
        "coleslaw", "rösti", "rosti", "grøntsager", "vegetables", "veggies", "svampe",
        "tomatoes", "tomater", "radishes", "sprouts", "rosenkål", "broccoli", "blomkål",
        "cauliflower", "asparagus", "asparges", "gulerødder", "carrots", "græskar", "squash",
        "polenta", "couscous", "bulgur", "ris", "rice", "slaw", "caprese", "side",
        "tilbehør", "pickled", "syltede",
    ),
    "dinner": (
        "gryde", "gryderet", "stew", "curry", "karry", "lasagne", "lasagna", "pasta",
        "spaghetti", "risotto", "pizza", "burger", "burgere", "burgers", "tacos", "taco",
        "enchiladas", "burrito", "burritos", "chili", "frikadeller", "bolognese", "steg",
        "suppe", "soup", "soups", "meatballs", "kødboller", "biksemad", "stroganoff",
        "wellington", "dal", "dahl", "masala", "korma", "tikka", "wok", "nudler", "noodles",
        "fried rice", "bowl", "bowls", "bøf", "mørbrad", "nakke", "kotelet", "koteletter",
        "medister", "falafel", "kofta", "aloo gobi", "chana", "gnocchi", "dumplings",
        "parmigiana", "moussaka", "sushi", "ramen", "pho", "okonomiyaki", "gratin",
        "tærte", "boller i karry", "frikassé", "lapskovs", "hachis", "skipperlabskovs",
        "mac and cheese", "mac n cheese", "casserole", "bake", "traybake", "sheet pan",
        "stuffed", "fyldte", "fish n chips", "fish and chips", "ratatouille", "bouillabaisse",
        "gumbo", "pirogger", "pierogi", "gazpacho", "ragu", "ragout", "chowder", "bisque",
        "goulash", "gullasch",
        "paella", "jambalaya", "fajitas", "quesadillas", "quesadilla", "kebab", "shawarma",
        "pad thai", "teriyaki", "bulgogi", "bibimbap", "pie", "pot pie", "fiskefrikadeller",
        "fiskefilet", "fiskefileter", "stir fry", "boats", "tagine", "biryani", "pilaf",
        "sausage", "pølser", "hotpot", "dinner", "aftensmad",
    ),
}
# fmt: on
# Meat, fish and other proteins: a title naming one is a meal unless something else says
# otherwise ("Kylling med honning og sennep").
# fmt: off
PROTEIN = (
    "kylling", "chicken", "oksekød", "okse", "beef", "svinekød", "svin", "pork", "gris",
    "lam", "lamme", "lamb", "kalv", "veal", "andebryst", "duck", "kalkun", "turkey", "laks",
    "salmon",
    "torsk", "cod", "fisk", "fish", "rejer", "shrimp", "prawns", "tun", "tuna", "tofu",
    "tempeh", "linser", "lentils", "kikærter", "chickpea", "chickpeas", "bønner", "beans",
    "bacon", "skinke", "ham", "chorizo", "pølse", "pølser", "sausage", "kødsovs", "fars",
    "hakket", "mince", "steak", "bøf", "mørbrad", "nakke", "kyllingebryst", "kyllingelår",
    "rødspætte", "sej", "kuller", "makrel", "sild", "muslinger", "mussels", "seitan", "hummer",
    "hummere", "jomfruhummer", "pollo", "flæsk", "krabbe", "crab",
    "halloumi", "edamame", "æg", "eggs", "egg",
)
# fmt: on
# Sweets named after what they are made of ("Chokoladeovertrukne abrikoser"), when nothing
# else in the title names the dish.
SWEET_TITLE = ("chokolade", "chocolate", "karamel", "caramel", "lakrids", "marcipan", "nougat")
COMPOUND_ONLY = {"kylling", "kage", "pasta", "suppe", "gryde", "kaffe", "smoothie", "nakke"}
ALCOHOL = (
    "gin",
    "rum",
    "vodka",
    "whisky",
    "whiskey",
    "tequila",
    "vin",
    "wine",
    "likør",
    "liqueur",
    "aperol",
    "campari",
    "kahlua",
    "champagne",
    "prosecco",
    "cava",
    "øl",
    "beer",
    "vermouth",
    "brandy",
    "cognac",
    "snaps",
    "baileys",
)
SWEET = (
    "sukker",
    "sugar",
    "flormelis",
    "chokolade",
    "chocolate",
    "kakao",
    "cocoa",
    "marcipan",
    "honning",
    "honey",
    "sirup",
    "syrup",
    "vanilje",
    "vanilla",
    "karamel",
    "caramel",
    "nutella",
    "dadler",
    "dates",
    "flødeskum",
    "fløde",
    "piskefløde",
    "is",
)
CUT_TITLE = re.compile(r"\s(?:med|with|m\.|i|in|til|for|på|uden|without|served|over)\s")
NOISE = re.compile(
    r"\((?:[^)]*)\)|\{[^}]*\}|\[[^]]*\]|\s[-–|:]\s.*$|:.*$|\brecipe\b.*$|\bopskrift\b.*$",
    re.I,
)
WORD = re.compile(r"[^\W\d_]+(?:['’][^\W\d_]+)?")


def _words(s: str) -> list[str]:
    return WORD.findall(s)


def _head_course(word: str) -> str | None:
    """The longest dish word that `word` is or ends in ("meatballs" before "balls")."""
    best, course = 0, None
    for c, words in HEADS.items():
        for kw in words:
            if " " in kw or len(kw) <= best:
                continue
            if word == kw or (len(kw) >= 3 and kw != "is" and word.endswith(kw)):
                best, course = len(kw), c
    return course


def _inner(word: str) -> str | None:
    for kw in COMPOUND_ONLY:
        if kw in word:
            return _head_course(kw)
    return None


def _has_protein(words: list[str]) -> bool:
    return any(
        w == p or (len(p) >= 4 and (w.startswith(p) or w.endswith(p)))
        for w in words
        for p in PROTEIN
    )


def from_tags(tags: list[str]) -> str | None:
    found = {c for t in tags if (c := CATEGORY.get(norm(t)))}
    return next((c for c in TAG_PRIORITY if c in found), None)


def from_title(title: str) -> str | None:
    full = norm(title)
    clean = NOISE.sub("", full).strip() or full
    main = CUT_TITLE.split(f" {clean} ", maxsplit=1)[0].strip()
    spaced = " ".join(re.sub(r"[^\w\s]|[\u0300-\u036f]", " ", clean).split())
    for phrase_course, words in HEADS.items():  # multi-word names first: "boller i karry"
        for kw in words:
            if " " in kw and f" {kw} " in f" {spaced} ":
                return phrase_course
    head_words = _words(main) or _words(clean)
    found = None
    for w in reversed(head_words):
        found = _head_course(w) or _inner(w) or ("dinner" if _has_protein([w]) else None)
        if found:
            break
    if found == "side" and _has_protein(head_words):
        found = "lunch" if _salad(head_words) else "dinner"
    if found is None:  # "Sliders - mini burgere"; never a side or sauce named after "med"
        for w in reversed(_words(full)):
            c = _head_course(w) or _inner(w)
            if c and c not in ("side", "condiment"):
                return c
        if any(s in w for w in head_words for s in SWEET_TITLE):
            return "dessert"
    return found


def _salad(words: list[str]) -> bool:
    return any(w.endswith(("salat", "salad", "salade")) for w in words)


def from_ingredients(names: list[str]) -> str | None:
    words = [w for n in names for w in _words(norm(n))]
    if not words:
        return None
    if any(w in ALCOHOL for w in words) and len(names) <= 8:
        return "drink"
    sweet = sum(any(s in w for s in SWEET) for w in words)
    if _has_protein(words) and sweet <= 1:
        return "dinner"
    if sweet >= 2 and sweet * 3 >= len(names):
        return "dessert"
    return None


def classify(title: str, tags: list[str] | None = None, ingredients: list[str] | None = None):
    """The recipe's course, or None when nothing says."""
    c = from_tags(tags or []) or from_title(title or "")
    if c == "dinner" and title and _savoury_tart(title, ingredients):
        c = "lunch"
    if c == "dinner" and "tærte" in norm(title or "") and _sweet(ingredients):
        c = "baking"
    return c or from_ingredients(ingredients or [])


def _savoury_tart(title: str, ingredients: list[str] | None) -> bool:
    t = norm(title)
    return ("quiche" in t) and not _sweet(ingredients)


def _sweet(ingredients: list[str] | None) -> bool:
    words = [w for n in ingredients or [] for w in _words(norm(n))]
    return sum(any(s in w for s in SWEET[:12]) for w in words) >= 2
