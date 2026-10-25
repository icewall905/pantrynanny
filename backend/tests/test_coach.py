"""What a machine client (the diet coach) needs: matching quality on the golden set, staples,
courses, meal ranking, the summary view, read-only tokens and quick stock placement."""

import importlib.util
import uuid
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from pantrynanny.recipes.course import classify
from pantrynanny.recipes.match import Pantry, ProductCandidate, Staples, best_match, is_staple

EVAL = Path(__file__).resolve().parents[2] / "scripts" / "match_eval.py"


def _eval_module():
    spec = importlib.util.spec_from_file_location("match_eval", EVAL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_golden_set_precision_and_recall():
    """A false "you have it" is worse than a false "missing": precision must stay perfect on the
    hand-checked set; recall was 0.52 before the matcher learned inflection and synonyms."""
    ev = _eval_module()
    rep = ev.golden_report(ev.load_golden())
    assert rep["cases"] >= 300 and rep["positives"] >= 150
    assert rep["precision"] == 1.0, rep["wrong"]
    assert rep["recall"] >= 0.95, rep["missed"]
    assert rep["staples_missed"] == [] and rep["not_staples_wrongly_staple"] == []


def cand(name, total=1):
    return ProductCandidate(
        id=name,
        name=name,
        aliases=[],
        total=Decimal(total),
        stock_unit="pcs",
        package_size=None,
        package_unit=None,
    )


def test_inflection_product_main_name_and_colours():
    pantry = [
        cand("Finvalsede økologiske havregryn"),
        cand("Boo Chopped Tomatoes - Herbs"),
        cand("Sushi Nori 11g Blue Dragon"),
        cand("hvide bønner"),
        cand("Vanilje sukker"),
        cand("Tamarind"),
    ]
    assert best_match("finvalset havregryn", pantry).name.startswith("Finvalsede")
    assert best_match("hakkede tomater", pantry).name.startswith("Boo")
    assert best_match("can chopped tomatoes", pantry).name.startswith("Boo")
    assert best_match("herbs", pantry) is None  # the variant is not what the product is
    assert best_match("tomater", [cand("Boo Chopped Tomatoes - Herbs")]) is None  # canned
    assert best_match("nori sheets", pantry).name.startswith("Sushi Nori")
    assert best_match("sorte bønner", pantry) is None  # another colour, another bean
    assert best_match("white beans", pantry).name == "hvide bønner"
    assert best_match("vaniljesukker", pantry).name == "Vanilje sukker"
    assert best_match("sukker", pantry) is None  # vanilla sugar is not sugar
    assert best_match("tamari", pantry) is None  # not a plural of tamarind


def test_staples_normalise_phrasing_and_are_household_specific():
    for s in [
        "salt og friskkværnet peber",
        "kosher salt",
        "flagesalt",
        "water or broth",
        "Salt & pepper",
        "kogende vand",
        "ground cumin",
    ]:
        assert is_staple(s), s
    for s in ["hjortetaksalt", "danskvand", "rød peberfrugt", "pistaciekerner uden salt"]:
        assert not is_staple(s), s
    mine = Staples(["salt", "rosiner"])
    assert "rosiner" in mine and "salt og peber" not in mine and "kosher salt" in mine


def test_course_classifier():
    assert classify("Kylling med honning og sennep") == "dinner"
    assert classify("Chokoladeovertrukne abrikoser", [], ["mørk chokolade", "abrikoser"]) in (
        "dessert",
        "snack",
    )
    assert classify("Granatæblesirup") == "condiment"
    assert classify("Gulerodssuppe med kokosmælk") == "dinner"
    assert classify("Pina Colada Smoothie") == "drink"
    assert classify("Speltbrød") == "baking"
    assert classify("Overnight oats") == "breakfast"
    assert classify("Anything", ["Dessert"]) == "dessert"  # the page's own category wins
    assert classify("Sheet-Pan Balsamic Chicken & Asparagus") == "dinner"
    assert classify("Baked Chicken Ricotta Meatballs") == "dinner"


# --------------------------------------------------------------------------- API


async def _stock(env, name, qty=1, **kw):
    p = await env.product(name, **kw)
    if qty:
        await env.ops(env.op("add", product_id=p["id"], quantity=qty))
    return p


async def _recipe(env, title, lines, **kw):
    r = await env.client.post(
        "/api/recipes",
        json={"title": title, "ingredients": [{"raw": x} for x in lines], **kw},
        headers=env.member,
    )
    assert r.status_code == 201, r.text
    return r.json()


async def test_household_staples_setting_and_products_win(env):
    c = env.client
    s = (await c.get("/api/settings", headers=env.member)).json()
    assert "salt" in s["staples"] and s["staples"] == s["default_staples"]
    r = await c.patch(
        "/api/settings", json={"staples": ["Salt", "rosiner", "salt"]}, headers=env.admin
    )
    assert r.status_code == 200 and r.json()["staples"] == ["salt", "rosiner"]
    assert (
        await c.patch("/api/settings", json={"staples": []}, headers=env.member)
    ).status_code == 403

    rec = await _recipe(env, "Rosinboller", ["2 dl rosiner", "1 tsk salt", "100 g sukker"])
    a = (await c.get(f"/api/recipes/{rec['id']}/availability", headers=env.member)).json()
    st = {i["ingredient"]["name"]: i["status"] for i in a["items"]}
    assert st == {"rosiner": "staple", "salt": "staple", "sukker": "missing"}  # not on my list

    # a staple the household keeps as a product is counted like any product
    await _stock(env, "Rosiner", 0)
    a = (await c.get(f"/api/recipes/{rec['id']}/availability", headers=env.member)).json()
    assert {i["ingredient"]["name"]: i["status"] for i in a["items"]}["rosiner"] == "missing"

    r = await c.patch("/api/settings", json={"staples": None}, headers=env.admin)
    assert r.json()["staples"] == r.json()["default_staples"]


async def test_course_ranking_filters_and_summary(env):
    c, h = env.client, env.member
    for name in ["Kyllingebryst", "Ris", "Løg", "Gulerødder", "Mørk chokolade", "Abrikoser"]:
        await _stock(env, name)
    sweet = await _recipe(env, "Chokoladeovertrukne abrikoser", ["mørk chokolade", "abrikoser"])
    dinner = await _recipe(
        env,
        "Kylling i karry med ris",
        ["kyllingebryst", "ris", "løg", "gulerødder", "salt og friskkværnet peber", "karry"],
    )
    almost = await _recipe(
        env, "Kyllingegryde", ["kyllingebryst", "løg", "gulerødder", "ris", "fløde", "vand"]
    )
    assert sweet["course"] in ("dessert", "snack") and dinner["course"] == "dinner"

    r = await c.get("/api/recipes/suggest?max_missing=1", headers=h)
    titles = [x["recipe"]["title"] for x in r.json()]
    # cookable first; a two-line sweet does not beat a real dish of the same kind
    assert titles == [dinner["title"], sweet["title"], almost["title"]]

    r = await c.get("/api/recipes/suggest?course=dinner&max_missing=2&include=summary", headers=h)
    rows = r.json()
    assert [x["title"] for x in rows] == [dinner["title"], almost["title"]]
    first = rows[0]
    assert "instructions" not in first and "items" not in first
    assert first["course"] == "dinner" and first["missing"] == 0 and first["coverage"] == 1.0
    assert set(first["staple_names"]) == {"salt og friskkværnet peber", "karry"}
    assert rows[1]["missing_names"] == ["fløde"]

    r = await c.get("/api/recipes/suggest?exclude_course=dinner&max_missing=2", headers=h)
    assert [x["recipe"]["title"] for x in r.json()] == [sweet["title"]]
    r = await c.get("/api/recipes/suggest?min_ingredients=3&max_missing=2", headers=h)
    assert sweet["title"] not in [x["recipe"]["title"] for x in r.json()]

    # tags and course filters on the plain list too; a course set by hand is kept on edit
    body = {"title": "Kylling i karry med ris", "course": "lunch", "tags": ["Hverdag"]}
    body["ingredients"] = [{"raw": "kyllingebryst"}]
    r = await c.put(f"/api/recipes/{dinner['id']}", json=body, headers=h)
    assert r.json()["course"] == "lunch"
    del body["course"]
    r = await c.put(f"/api/recipes/{dinner['id']}", json=body, headers={**h, "If-Match": "2"})
    assert r.json()["course"] == "lunch"
    r = await c.get("/api/recipes?tag=hverdag&include=summary", headers=h)
    assert [x["title"] for x in r.json()] == [dinner["title"]]
    r = await c.get("/api/recipes?course=lunch&course=dinner", headers=h)
    assert {x["recipe"]["title"] for x in r.json()} == {dinner["title"], almost["title"]}


async def test_read_only_token(env):
    c = env.client
    r = await c.post(
        "/api/auth/token",
        json={
            "username": "member",
            "password": "correct-horse-battery",
            "device_name": "Diet coach",
            "scope": "read",
        },
    )
    assert r.status_code == 200, r.text
    ro = {"Authorization": f"Bearer {r.json()['token']}"}
    for path in [
        "/api/inventory?sort=expiry",
        "/api/locations",
        "/api/dashboard",
        "/api/recipes/suggest?max_missing=1&include=summary",
        "/api/recipes?q=x",
        "/api/settings",
    ]:
        assert (await c.get(path, headers=ro)).status_code == 200, path
    assert (await c.get("/api/auth/me", headers=ro)).json()["read_only"] is True
    r = await c.post("/api/products", json={"name": "X"}, headers=ro)
    assert r.status_code == 403 and r.json()["code"] == "read_only_token"
    r = await c.post("/api/sync/ops", json={"ops": []}, headers=ro)
    assert r.status_code == 403
    devices = (await c.get("/api/devices", headers=env.admin)).json()
    assert {d["device_name"]: d["scope"] for d in devices}["Diet coach"] == "read"


async def test_place_after_scan_and_undo(env):
    c, h = env.client, env.member
    milk = await env.product("Mælk")
    add = env.op("add", product_id=milk["id"], quantity=2)
    await env.ops(add)
    week = (date.today() + timedelta(days=7)).isoformat()
    body = {
        "client_op_id": str(uuid.uuid4()),
        "add_client_op_id": add["client_op_id"],
        "expires_at": week,
        "location_id": env.locations["Køleskab"],
    }
    r = await c.post("/api/inventory/place", json=body, headers=h)
    assert r.status_code == 200, r.text
    assert (await c.post("/api/inventory/place", json=body, headers=h)).json()["status"] == (
        "duplicate"
    )
    inv = (await c.get(f"/api/inventory/{milk['id']}", headers=h)).json()
    assert inv["next_expiry"] == week and inv["total_quantity"] == 2
    live = [b for b in inv["batches"] if b["quantity"] > 0]
    assert [(b["location_id"], b["expires_at"]) for b in live] == [
        (env.locations["Køleskab"], week)
    ]
    # the product (and its category) now remember the fridge
    p = (await c.get(f"/api/products/{milk['id']}", headers=h)).json()
    assert p["default_location_id"] == env.locations["Køleskab"]

    # a second tap moves it on from where the first one put it
    freezer = {"client_op_id": str(uuid.uuid4()), "add_client_op_id": add["client_op_id"]}
    freezer["location_id"] = env.locations["Fryser"]
    assert (await c.post("/api/inventory/place", json=freezer, headers=h)).status_code == 200
    inv = (await c.get(f"/api/inventory/{milk['id']}", headers=h)).json()
    live = [b for b in inv["batches"] if b["quantity"] > 0]
    assert [(b["location_id"], b["expires_at"], b["quantity"]) for b in live] == [
        (env.locations["Fryser"], week, 2)
    ]

    # undoing the scan takes the placed stock back too
    r = await env.ops(env.op("undo", quantity=None, undoes_client_op_id=add["client_op_id"]))
    assert r[0]["status"] == "applied", r
    assert await env.total(milk["id"]) == 0

    missing = {**body, "client_op_id": str(uuid.uuid4()), "add_client_op_id": str(uuid.uuid4())}
    assert (await c.post("/api/inventory/place", json=missing, headers=h)).status_code == 404


async def test_bulk_fix_up(env):
    c, h = env.client, env.member
    ids = []
    for name in ["Ost", "Ærter", "Ris"]:
        p = await _stock(env, name, 2)
        ids.append(p["id"])
    inv = (await c.get("/api/inventory", headers=h)).json()
    batch_ids = [b["id"] for it in inv for b in it["batches"]]
    soon = (date.today() + timedelta(days=30)).isoformat()
    r = await c.post(
        "/api/batches/fix-up",
        json={
            "batch_ids": batch_ids[:2],
            "location_id": env.locations["Fryser"],
            "expires_at": soon,
        },
        headers=h,
    )
    assert r.status_code == 200 and r.json() == {"changed": 2, "unchanged": 0}
    inv = {i["product"]["id"]: i for i in (await c.get("/api/inventory", headers=h)).json()}
    moved = [i for i in inv.values() if i["next_expiry"] == soon]
    assert len(moved) == 2 and all(
        b["location_id"] == env.locations["Fryser"]
        for i in moved
        for b in i["batches"]
        if b["quantity"] > 0
    )
    assert sum(i["total_quantity"] for i in inv.values()) == 6
    # clearing the expiry only
    r = await c.post(
        "/api/batches/fix-up", json={"batch_ids": batch_ids, "expires_at": None}, headers=h
    )
    assert r.status_code == 200
    bad = {"batch_ids": batch_ids, "location_id": str(uuid.uuid4())}
    assert (await c.post("/api/batches/fix-up", json=bad, headers=h)).status_code == 422


async def test_category_defaults(env):
    c, h = env.client, env.member
    cat = next(iter(env.categories.values()))
    r = await c.patch(
        f"/api/categories/{cat}",
        json={"default_expiry_days": 5, "default_location_id": env.locations["Fryser"]},
        headers=h,
    )
    assert r.status_code == 200 and r.json()["default_expiry_days"] == 5
    # a product of that category without a place of its own goes where the category goes
    p = await env.product("Frosne ærter", category_id=cat)
    await env.ops(env.op("add", product_id=p["id"], quantity=1))
    inv = (await c.get(f"/api/inventory/{p['id']}", headers=h)).json()
    assert inv["batches"][0]["location_id"] == env.locations["Fryser"]


@pytest.mark.parametrize("name", ["c. tahini", "pint cherry tomatoes", "can coconut milk"])
def test_leading_unit_words_are_ignored(name):
    pantry = Pantry([cand("Tahini"), cand("Cherry Blommetomater"), cand("Kokosmælk")])
    assert pantry.best(name) is not None


async def test_admin_backfill_fills_times_and_course_and_resumes(env, app):
    c = env.client
    page = """<script type="application/ld+json">{"@type":"Recipe","name":"Gryde",
      "recipeIngredient":["1 løg"],"totalTime":"PT1H15M","recipeCategory":"Aftensmad"}</script>"""
    calls = []

    async def fake_fetch(url):
        calls.append(url)
        if url.endswith("/broken"):
            from pantrynanny.errors import AppError

            raise AppError(422, "import_blocked", "nope")
        return url, page

    for n in ("a", "b", "broken"):
        await _recipe(env, f"Opskrift {n}", ["1 løg"], source_url=f"https://ex.example/{n}")
    typed = await _recipe(
        env, "Min egen", ["1 løg"], source_url="https://ex.example/own", prep_min=5, course="side"
    )
    assert (
        await c.post("/api/admin/recipes/backfill", json={}, headers=env.member)
    ).status_code == 403
    app.state.recipe_fetcher = fake_fetch
    try:
        r = await c.post(
            "/api/admin/recipes/backfill", json={"limit": 2, "delay_s": 0.5}, headers=env.admin
        )
        assert r.status_code == 202 and r.json()["running"] is True
        task = app.state.recipe_backfill[env.household_id]._task
        await task
        st = (await c.get("/api/admin/recipes/backfill", headers=env.admin)).json()
        assert st["checked"] == 2 and st["remaining"] == 1 and not st["running"]
        r = await c.post("/api/admin/recipes/backfill", json={"delay_s": 0.5}, headers=env.admin)
        await app.state.recipe_backfill[env.household_id]._task
        st = (await c.get("/api/admin/recipes/backfill", headers=env.admin)).json()
    finally:
        del app.state.recipe_fetcher
    assert st["checked"] == 1 and st["remaining"] == 0 and st["failed"] == 1
    assert len(calls) == 3  # every page once; the household's own recipe was complete
    recs = {
        x["recipe"]["title"]: x["recipe"]
        for x in (await c.get("/api/recipes", headers=env.member)).json()
    }
    assert recs["Opskrift a"]["cook_min"] == 75 and recs["Opskrift a"]["minutes"] == 75
    assert recs["Opskrift a"]["course"] == "dinner"
    assert recs["Min egen"]["prep_min"] == 5 and recs["Min egen"]["course"] == "side"
    assert typed


MICRO = """<html><head><meta property="og:site_name" content="Valdemarsro"></head><body>
<div class="main" itemscope="itemscope" itemtype="http://schema.org/Recipe">
 <span itemprop="publisher" itemscope="itemscope" itemtype="https://schema.org/Organization">
  <span itemprop="name">Valdemarsro</span></span>
 <div class="hidden-schema"><span itemprop="cookTime">PT60M</span>
  <span itemprop="totalTime">PT20M</span><span itemprop="recipeYield">4</span></div>
 <h2 itemprop="name">Enchiladas</h2>
 <ul><li itemprop="recipeIngredient">1 tsk <b>stødt</b> spidskommen</li>
     <li itemprop="recipeIngredient">8 tortillas</li></ul>
 <div itemprop="recipeInstructions"><div><p>Rist krydderierne.</p></div><p>Bag i 15 min.</p></div>
 <span itemprop="recipeCategory">Aftensmad</span><span itemprop="keywords">Mexicansk, Nem</span>
 <img src="https://img.example/e.jpg" itemprop="image"><script>alert(1)</script>
</div></body></html>"""


def test_microdata_recipe_and_total_time():
    from pantrynanny.recipes.jsonld import extract, times

    d = extract(MICRO)
    assert d.title == "Enchiladas" and d.servings == 4
    assert d.ingredients == ["1 tsk stødt spidskommen", "8 tortillas"]
    assert d.instructions == ["Rist krydderierne.", "Bag i 15 min."]
    assert (d.prep_min, d.cook_min) == (None, 60)  # the larger of the two is the total
    assert d.tags == ["Mexicansk", "Nem", "Aftensmad"] and classify(d.title, d.tags) == "dinner"
    assert d.image_url == "https://img.example/e.jpg" and d.source_name == "Valdemarsro"
    assert times(10, 20, 45) == (10, 35) and times(10, 20, 30) == (10, 20)
    assert times(None, None, 25) == (None, 25)
