"""Recipes: parsing, pantry matching, safe URL import, what-can-we-cook, shopping and meal plan."""

from datetime import date, timedelta
from decimal import Decimal

import httpx
import pytest

from pantrynanny.errors import AppError
from pantrynanny.recipes.fetch import fetch_page
from pantrynanny.recipes.jsonld import extract, minutes
from pantrynanny.recipes.match import ProductCandidate, best_match, needed_in_stock_units
from pantrynanny.recipes.parse import parse_line


@pytest.mark.parametrize(
    "line,name,qty,unit,note,optional",
    [
        ("2 dl mælk", "mælk", "2", "dl", None, False),
        ("1 1/2 cups flour, sifted", "flour", "1.5", "cup", "sifted", False),
        ("½ tsk salt", "salt", "0.5", "tsp", None, False),
        ("2-3 fed hvidløg (presset)", "hvidløg", "3", "clove", "presset", False),
        ("400 g hakket oksekød", "hakket oksekød", "400", "g", None, False),
        ("evt. 1 spsk honning", "honning", "1", "tbsp", None, True),
        ("3 æg", "æg", "3", None, None, False),
        ("Salt og peber", "Salt og peber", None, None, None, False),
        ("1,5 l vand", "vand", "1.5", "l", None, False),
    ],
)
def test_parse_line(line, name, qty, unit, note, optional):
    p = parse_line(line)
    assert (p.name, p.unit, p.note, p.optional) == (name, unit, note, optional)
    assert p.quantity == (Decimal(qty) if qty else None)
    assert p.raw == line


def cand(name, total=1, unit="pcs", size=None, punit=None, aliases=()):
    return ProductCandidate(
        id=name,
        name=name,
        aliases=list(aliases),
        total=Decimal(total),
        stock_unit=unit,
        package_size=Decimal(size) if size else None,
        package_unit=punit,
    )


def test_matching_handles_compounds_synonyms_and_traps():
    pantry = [
        cand("Letmælk", size="1", punit="l"),
        cand("Hvidløg"),
        cand("Rødløg"),
        cand("Hvedemel", unit="g", total=1000),
        cand("Karamel"),
    ]
    assert best_match("mælk", pantry).name == "Letmælk"
    assert best_match("milk", pantry).name == "Letmælk"  # English recipe, Danish pantry
    assert best_match("løg", pantry).name == "Rødløg"  # an onion, never garlic
    assert best_match("hvidløg", pantry).name == "Hvidløg"
    assert best_match("mel", pantry).name == "Hvedemel"  # not "Karamel"
    assert best_match("kanel", pantry) is None
    # in-stock product wins among equal matches
    two = [cand("Sødmælk", total=0), cand("Minimælk", total=2)]
    assert best_match("mælk", two).name == "Minimælk"


def test_amount_conversion_to_stock_units():
    carton = cand("Letmælk", size="1", punit="l")
    assert needed_in_stock_units(Decimal(2), "dl", carton) == Decimal("0.2")
    flour = cand("Mel", unit="g", total=1000)
    assert needed_in_stock_units(Decimal("0.5"), "kg", flour) == Decimal(500)
    eggs = cand("Æg", total=10)
    assert needed_in_stock_units(Decimal(3), None, eggs) == Decimal(3)
    assert needed_in_stock_units(Decimal(1), "bunch", eggs) is None  # cannot tell


PAGE = """<html><head><title>x</title>
<meta property="og:site_name" content="Madbloggen">
<script type="application/ld+json">{"@context":"https://schema.org","@graph":[
 {"@type":"WebPage","name":"page"},
 {"@type":["Recipe"],"name":"Pandekager <b>nemme</b>","recipeYield":["4","4 stk"],
  "prepTime":"PT10M","cookTime":"PT1H5M","image":{"url":"https://img.example/p.jpg"},
  "keywords":"dessert, nem","recipeCategory":"Dessert",
  "recipeIngredient":["3 æg","5 dl mælk","250 g hvedemel","1 knivspids salt"],
  "recipeInstructions":[{"@type":"HowToSection","itemListElement":[
     {"@type":"HowToStep","text":"Pisk æg og mælk."},{"@type":"HowToStep","text":"Tilsæt mel <script>x<\\/script>."}]}]}
]}</script></head><body></body></html>"""


def test_jsonld_extraction_is_plain_text_only():
    d = extract(PAGE)
    assert d.title == "Pandekager nemme"
    assert d.servings == 4 and d.prep_min == 10 and d.cook_min == 65
    assert d.ingredients[1] == "5 dl mælk" and len(d.ingredients) == 4
    assert d.instructions == ["Pisk æg og mælk.", "Tilsæt mel x ."]
    assert d.image_url == "https://img.example/p.jpg" and d.source_name == "Madbloggen"
    assert d.tags == ["dessert", "nem", "Dessert"]
    assert extract("<html>no recipe</html>") is None
    assert minutes("P1DT2H") == 1560 and minutes("garbage") is None


async def _resolver_for(table):
    async def resolve(host, port):
        return table[host]

    return resolve


@pytest.mark.parametrize(
    "url,addrs",
    [
        ("http://localhost/x", ["127.0.0.1"]),
        ("http://router.lan/", ["192.168.1.1"]),
        ("http://pantry.example/", ["10.0.10.163"]),
        ("http://metadata/", ["169.254.169.254"]),
        ("http://v6.example/", ["::1"]),
        ("http://mapped.example/", ["::ffff:10.0.0.1"]),
        ("http://mixed.example/", ["93.184.216.34", "10.0.0.5"]),
    ],
)
async def test_fetch_refuses_private_networks(url, addrs):
    host = httpx.URL(url).host
    with pytest.raises(AppError) as e:
        await fetch_page(
            url,
            resolve=await _resolver_for({host: addrs}),
            transport=httpx.MockTransport(lambda r: httpx.Response(200)),
        )
    assert e.value.code == "import_blocked"


async def test_fetch_rechecks_redirects_and_pins_the_ip():
    seen = []

    def handler(req: httpx.Request):
        seen.append((req.url.host, req.headers["host"]))
        if req.headers["host"] == "good.example":
            return httpx.Response(302, headers={"location": "http://evil.example/"})
        return httpx.Response(200, html="<html></html>")

    resolve = await _resolver_for({"good.example": ["93.184.216.34"], "evil.example": ["10.1.1.1"]})
    with pytest.raises(AppError) as e:
        await fetch_page(
            "http://good.example/r", resolve=resolve, transport=httpx.MockTransport(handler)
        )
    assert e.value.code == "import_blocked"
    assert seen == [("93.184.216.34", "good.example")]  # connected to the checked address
    for bad in (
        "file:///etc/passwd",
        "ftp://x.example/",
        "http://u:p@x.example/",
        "http://x.example:22/",
    ):
        with pytest.raises(AppError):
            await fetch_page(bad, resolve=resolve)


# --------------------------------------------------------------------------- API


async def _stock(env, name, qty, **kw):
    p = await env.product(name, **kw)
    if qty:
        await env.ops(env.op("add", product_id=p["id"], quantity=qty))
    return p


PANCAKES = {
    "title": "Pandekager",
    "servings": 4,
    "prep_min": 10,
    "cook_min": 20,
    "instructions": ["Pisk", "Steg"],
    "ingredients": [
        {"raw": "3 æg"},
        {"raw": "5 dl mælk"},
        {"raw": "250 g hvedemel"},
        {"raw": "1 knivspids salt"},
        {"raw": "evt. sukker"},
    ],
}


async def test_recipe_crud_availability_and_shopping(env):
    c, h = env.client, env.member
    await _stock(env, "Æg", 6)
    await _stock(env, "Letmælk", 1, package_size=1, package_unit="l")
    r = await c.post("/api/recipes", json=PANCAKES, headers=h)
    assert r.status_code == 201, r.text
    rec = r.json()
    assert [i["name"] for i in rec["ingredients"]][:3] == ["æg", "mælk", "hvedemel"]
    assert rec["ingredients"][4]["optional"] is True

    a = (await c.get(f"/api/recipes/{rec['id']}/availability?servings=8", headers=h)).json()
    st = {i["ingredient"]["name"]: i for i in a["items"]}
    assert st["æg"]["status"] == "have" and st["æg"]["need"] == 6
    assert st["mælk"]["status"] == "have" and st["mælk"]["need"] == 1  # 10 dl of a 1 l carton
    assert st["hvedemel"]["status"] == "missing"
    assert st["salt"]["status"] == "staple" and st["sukker"]["status"] == "optional"
    assert (a["have"], a["missing"], a["required"]) == (2, 1, 3)

    a = (await c.get(f"/api/recipes/{rec['id']}/availability?servings=12", headers=h)).json()
    st = {i["ingredient"]["name"]: i for i in a["items"]}
    assert st["mælk"]["status"] == "low" and st["mælk"]["enough"] is False

    r = await c.post(f"/api/recipes/{rec['id']}/shopping", json={}, headers=h)
    assert r.json()["added"] == ["hvedemel"]
    shop = (await c.get("/api/shopping", headers=h)).json()
    assert [s["name"] for s in shop] == ["hvedemel"]
    # asking again does not put a second "hvedemel" on the list
    r = await c.post(f"/api/recipes/{rec['id']}/shopping", json={}, headers=h)
    assert r.json() == {"added": [], "skipped": ["hvedemel"]}

    # editing replaces the ingredient list; a stale version is refused
    body = {**PANCAKES, "title": "Pandekager (dobbelt)", "ingredients": [{"raw": "6 æg"}]}
    assert (
        await c.put(f"/api/recipes/{rec['id']}", json=body, headers={**h, "If-Match": "99"})
    ).status_code == 409
    r = await c.put(f"/api/recipes/{rec['id']}", json=body, headers={**h, "If-Match": "1"})
    assert r.status_code == 200 and r.json()["version"] == 2
    assert len(r.json()["ingredients"]) == 1
    assert (await c.delete(f"/api/recipes/{rec['id']}", headers=h)).status_code == 204
    assert (await c.get(f"/api/recipes/{rec['id']}", headers=h)).status_code == 404


async def test_what_can_we_cook_ranks_cookable_and_expiring_first(env):
    c, h = env.client, env.member
    eggs = await _stock(env, "Æg", 6)
    soon = (date.today() + timedelta(days=1)).isoformat()
    spinach = await env.product("Spinat")
    await env.ops(env.op("add", product_id=spinach["id"], quantity=1, expires_at=soon))
    mk = lambda title, lines, mins=20: c.post(  # noqa: E731
        "/api/recipes",
        json={"title": title, "cook_min": mins, "ingredients": [{"raw": x} for x in lines]},
        headers=h,
    )
    await mk("Kage", ["4 æg", "200 g smør"])
    await mk("Omelet", ["3 æg", "salt"])
    await mk("Spinatomelet", ["3 æg", "100 g spinat"])
    await mk("Langtidsstegt", ["2 æg"], mins=300)
    r = await c.get("/api/recipes/suggest?max_minutes=60", headers=h)
    titles = [x["recipe"]["title"] for x in r.json()]
    assert titles == ["Spinatomelet", "Omelet", "Kage"]
    assert r.json()[0]["availability"]["uses_expiring"] == ["Spinat"]
    assert r.json()[2]["availability"]["missing"] == 1
    assert eggs  # untouched: suggesting never changes stock
    inv = (await c.get(f"/api/inventory/{eggs['id']}", headers=h)).json()
    assert inv["total_quantity"] == 6


async def test_import_uses_safe_fetcher_and_returns_a_draft(env, app):
    async def fake_fetch(url):
        assert url == "https://madbloggen.example/pandekager"
        return url, PAGE

    app.state.recipe_fetcher = fake_fetch
    try:
        r = await env.client.post(
            "/api/recipes/import",
            json={"url": "https://madbloggen.example/pandekager"},
            headers=env.member,
        )
    finally:
        del app.state.recipe_fetcher
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["title"] == "Pandekager nemme" and d["source_url"].startswith("https://")
    assert (await env.client.get("/api/recipes", headers=env.member)).json() == []  # not saved

    # the real fetcher is used by default and refuses local addresses
    r = await env.client.post(
        "/api/recipes/import", json={"url": "http://127.0.0.1:8734/"}, headers=env.member
    )
    assert r.status_code == 422 and r.json()["code"] == "import_blocked"


async def test_meal_plan_never_touches_stock_and_shops_for_the_week(env):
    c, h = env.client, env.member
    eggs = await _stock(env, "Æg", 4)
    rec = (
        await c.post(
            "/api/recipes",
            json={
                "title": "Omelet",
                "servings": 2,
                "ingredients": [{"raw": "3 æg"}, {"raw": "1 dl fløde"}],
            },
            headers=h,
        )
    ).json()
    monday = date(2026, 10, 19)
    for d in (0, 2):
        r = await c.post(
            "/api/meal-plan",
            json={"day": (monday + timedelta(days=d)).isoformat(), "recipe_id": rec["id"]},
            headers=h,
        )
        assert r.status_code == 201, r.text
    await c.post(
        "/api/meal-plan",
        json={"day": monday.isoformat(), "slot": "lunch", "title": "Rester"},
        headers=h,
    )
    plan = (await c.get(f"/api/meal-plan?start={monday}&days=7", headers=h)).json()
    assert [(p["slot"], p["recipe_title"] or p["title"], p["missing"]) for p in plan] == [
        ("dinner", "Omelet", 1),
        ("lunch", "Rester", None),
        ("dinner", "Omelet", 1),
    ]
    inv = (await c.get(f"/api/inventory/{eggs['id']}", headers=h)).json()
    assert inv["total_quantity"] == 4  # planning deducts nothing

    r = await c.post("/api/meal-plan/shopping", json={"start": monday.isoformat()}, headers=h)
    # two omelets need 6 eggs, 4 in stock -> buy 2; cream is missing entirely
    assert sorted(r.json()["added"]) == ["fløde", "Æg"]
    shop = {s["name"]: s["quantity"] for s in (await c.get("/api/shopping", headers=h)).json()}
    assert shop == {"Æg": 2, "fløde": 1}

    first = plan[0]["id"]
    r = await c.patch(f"/api/meal-plan/{first}", json={"cooked": True}, headers=h)
    assert r.json()["cooked_at"] is not None
    assert (await c.delete(f"/api/meal-plan/{first}", headers=h)).status_code == 204
    assert (
        await c.post("/api/meal-plan", json={"day": monday.isoformat()}, headers=h)
    ).status_code == 422
