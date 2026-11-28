import json

import pytest

from pantrynanny.recipes.match import (
    Pantry,
    best_match,
    best_substitute,
    ingredient_key,
)

from .test_ai import FakeAI, install
from .test_recipes import _stock, cand


@pytest.fixture(autouse=True)
def _no_ai(app):
    yield
    if hasattr(app.state, "ai_client"):
        del app.state.ai_client


def test_the_form_an_ingredient_comes_in_is_the_same_thing():
    pantry = [cand("Garlic bulbs"), cand("Persille"), cand("Nelliker"), cand("Kanelstang")]
    for line in ["garlic cloves", "3 cloves garlic", "fed hvidløg", "hvidløgsfed", "garlic"]:
        assert best_match(line, pantry).name == "Garlic bulbs", line
    assert best_match("hvidløg", [cand("Hvidløg 3 stk")]).name == "Hvidløg 3 stk"
    assert best_match("cinnamon stick", pantry).name == "Kanelstang"
    # "cloves" on its own is the spice, never garlic
    assert best_match("whole cloves", [cand("Garlic bulbs")]) is None
    # leaves are their own ingredient: lime leaves are not limes
    assert best_match("lime", [cand("Tørrede limeblade")]) is None
    assert ingredient_key("2 fed hvidløg") == ingredient_key("garlic cloves") == "hvidløg"


def test_substitutes_stand_in_only_when_the_real_thing_is_missing():
    pantry = [cand("Smør", total=0), cand("Becel margarine"), cand("Løg, gule"), cand("Citroner")]
    assert best_substitute("butter", pantry).name == "Becel margarine"
    assert best_substitute("shallots", pantry).name == "Løg, gule"
    assert best_substitute("lime", pantry).name == "Citroner"
    assert best_substitute("kanel", pantry) is None
    # one direction only: margarine is not a stand-in rule target for lemons
    assert best_substitute("citron", [cand("Becel margarine")]) is None
    # an out-of-stock stand-in is no help
    assert best_substitute("butter", [cand("Becel margarine", total=0)]) is None
    # household answers come first and are found through the Pantry cache too
    approved = {"grønkål": ["Persille"]}
    p = Pantry([cand("Persille"), cand("Spinat")], substitutes=approved)
    assert p.substitute("grønkål").name == "Persille"


async def _recipe(env, title, lines):
    r = await env.client.post(
        "/api/recipes",
        json={"title": title, "ingredients": [{"raw": x} for x in lines]},
        headers=env.member,
    )
    assert r.status_code == 201, r.text
    return r.json()


async def test_swap_status_is_not_have_and_is_not_shopped(env):
    c, h = env.client, env.member
    await _stock(env, "Garlic bulbs", 2)
    await _stock(env, "Becel margarine", 1)
    await _stock(env, "Æg", 6)
    rec = await _recipe(env, "Kage", ["3 garlic cloves", "200 g smør", "4 æg", "1 l fløde"])
    a = (await c.get(f"/api/recipes/{rec['id']}/availability", headers=h)).json()
    st = {i["ingredient"]["name"]: i for i in a["items"]}
    garlic = next(v for k, v in st.items() if "garlic" in k)
    assert garlic["status"] == "have" and garlic["product"]["name"] == "Garlic bulbs"
    assert st["smør"]["status"] == "swap" and st["smør"]["substitute"]["name"] == "Becel margarine"
    assert st["fløde"]["status"] == "missing"
    assert (a["have"], a["swaps"], a["missing"], a["required"]) == (2, 1, 1, 4)
    r = await c.post(f"/api/recipes/{rec['id']}/shopping", json={}, headers=h)
    assert r.json()["added"] == ["fløde"]  # the swap line is covered by margarine
    brief = (await c.get("/api/recipes?include=summary", headers=h)).json()[0]
    assert brief["swaps"] == 1 and brief["swap_names"] == ["smør"]


async def test_admin_lists_misses_and_approves_same_and_swap(env):
    c, h = env.client, env.admin
    kale = await _stock(env, "Grønkål", 0)
    spinach = await _stock(env, "Spinat", 1)
    celery = await _stock(env, "Bladselleri", 1)
    await _recipe(env, "Suppe", ["1 bundt celery", "200 g kale", "100 g quinoa"])
    await _recipe(env, "Salat", ["celery", "quinoa"])
    assert (await c.get("/api/admin/replacements", headers=env.member)).status_code == 403
    r = (await c.get("/api/admin/replacements", headers=h)).json()
    misses = {m["ingredient"]: m["recipes"] for m in r["misses"]}
    assert misses == {"celery": 2, "quinoa": 2, "kale": 1}  # kale: no product by that name
    assert kale

    body = {"ingredient": "celery", "product_id": celery["id"], "kind": "same"}
    assert (await c.post("/api/admin/replacements", json=body, headers=h)).json() == {
        "result": "alias"
    }
    assert (await c.post("/api/admin/replacements", json=body, headers=h)).json() == {
        "result": "already"
    }
    body = {"ingredient": "kale", "product_id": spinach["id"], "kind": "swap", "source": "ai"}
    assert (await c.post("/api/admin/replacements", json=body, headers=h)).json() == {
        "result": "substitute"
    }
    r = (await c.get("/api/admin/replacements", headers=h)).json()
    assert [m["ingredient"] for m in r["misses"]] == ["quinoa"]
    [sub] = r["substitutes"]
    assert (sub["ingredient"], sub["product_name"], sub["source"]) == ("kale", "Spinat", "ai")

    rec = await _recipe(env, "Grøn", ["celery", "200 g kale"])
    a = (await c.get(f"/api/recipes/{rec['id']}/availability", headers=h)).json()
    assert [i["status"] for i in a["items"]] == ["have", "swap"]

    assert (await c.delete(f"/api/admin/replacements/{sub['id']}", headers=h)).status_code == 204
    a = (await c.get(f"/api/recipes/{rec['id']}/availability", headers=h)).json()
    assert [i["status"] for i in a["items"]] == ["have", "missing"]


async def test_ai_suggestions_are_checked_and_never_saved(env, app):
    c, h = env.client, env.admin
    await _stock(env, "Bladselleri", 1)
    await _stock(env, "Spinat", 1)
    await _recipe(env, "Suppe", ["celery", "200 g kale"])

    def reply(body):
        text = body["messages"][-1]["content"]
        assert "1. Bladselleri" in text and "- celery" in text
        return json.dumps(
            {
                "answers": [
                    {"ingredient": "celery", "product": 1, "kind": "same", "reason": "same"},
                    {"ingredient": "kale", "product": 2, "kind": "swap"},
                    {"ingredient": "invented", "product": 1, "kind": "same"},
                    {"ingredient": "kale", "product": 99, "kind": "swap"},
                    {"ingredient": "celery", "product": 2, "kind": "maybe"},
                ]
            }
        )

    install(app, FakeAI([reply]))
    r = await c.post("/api/admin/replacements/suggest", json={"locale": "en"}, headers=h)
    assert r.status_code == 200, r.text
    got = {(s["ingredient"], s["product_name"], s["kind"]) for s in r.json()}
    assert got == {("celery", "Bladselleri", "same"), ("kale", "Spinat", "swap")}
    r = (await c.get("/api/admin/replacements", headers=h)).json()
    assert r["substitutes"] == [] and len(r["misses"]) == 2
