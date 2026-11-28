"""Repairing recipes whose import stored a placeholder instead of ingredients or method."""

import uuid
from types import SimpleNamespace

import pytest

from pantrynanny.errors import AppError
from pantrynanny.models import Recipe, RecipeIngredient
from pantrynanny.recipes import ai_reader
from pantrynanny.services import recipe_repair

PLACEHOLDER_STEPS = ["Could not detect instructions"]
PLACEHOLDER_LINE = "Could not detect ingredients"

PAGE = """<script type="application/ld+json">{"@type":"Recipe","name":"Gryde",
  "recipeIngredient":["2 dl mælk","400 g kartofler","1 tsk salt"],
  "recipeInstructions":[{"@type":"HowToStep","text":"Skræl kartoflerne."},
    {"@type":"HowToStep","text":"Kog dem møre i mælken."},
    {"@type":"HowToStep","text":"Smag til med salt."}],
  "totalTime":"PT40M","recipeCategory":"Aftensmad"}</script>"""


async def _recipe(env, title, lines, instructions=(), **kw):
    r = await env.client.post(
        "/api/recipes",
        json={
            "title": title,
            "ingredients": [{"raw": x} for x in lines],
            "instructions": list(instructions),
            **kw,
        },
        headers=env.member,
    )
    assert r.status_code == 201, r.text
    return r.json()


async def _broken(env, title="Gryde", **kw):
    return await _recipe(
        env,
        title,
        [PLACEHOLDER_LINE],
        instructions=PLACEHOLDER_STEPS,
        source_url=f"https://ex.example/{title.lower().replace(' ', '-')}",
        **kw,
    )


def _fetcher(pages=None, calls=None):
    async def fetch(url):
        if calls is not None:
            calls.append(url)
        if pages is None or url not in pages:
            raise AppError(422, "not_a_page", "nope")
        return url, pages[url]

    return fetch


async def test_repair_fills_the_placeholder_and_keeps_everything_else(env, app):
    c = env.client
    r = await _broken(env, tags=["Vinter", "Gryde"], prep_min=10, servings=2)
    sm = app.state.sessionmaker

    calls = []
    st = await recipe_repair.run(
        sm,
        env.household_id,
        recipe_repair.RepairStatus(),
        fetcher=_fetcher({r["source_url"]: PAGE}, calls),
        delay_s=0,
    )

    assert calls == [r["source_url"]]
    assert (st.checked, st.failed) == (1, 0)
    assert (st.instructions_filled, st.ingredients_filled) == (1, 1)
    assert st.remaining == 0
    after = (await c.get(f"/api/recipes/{r['id']}", headers=env.member)).json()
    assert after["instructions"] == [
        "Skræl kartoflerne.",
        "Kog dem møre i mælken.",
        "Smag til med salt.",
    ]
    assert [i["name"] for i in after["ingredients"]] == ["mælk", "kartofler", "salt"]
    assert [i["quantity"] for i in after["ingredients"]] == [2, 400, 1]
    assert after["ingredients"][0]["unit"] == "dl"
    # what the household had stays as it was
    assert after["title"] == r["title"]
    assert after["tags"] == ["Vinter", "Gryde"]
    assert after["prep_min"] == 10
    assert after["servings"] == 2
    assert after["version"] == r["version"] + 1


async def test_a_complete_recipe_is_never_fetched(env, app):
    await _recipe(env, "Færdig", ["1 løg"], instructions=["Hak løget."])
    calls = []
    st = await recipe_repair.run(
        app.state.sessionmaker,
        env.household_id,
        recipe_repair.RepairStatus(),
        fetcher=_fetcher({}, calls),
        delay_s=0,
    )
    assert calls == [] and st.checked == 0 and st.remaining == 0


async def test_only_the_broken_field_is_replaced(env, app):
    r = await _recipe(
        env,
        "Halv",
        ["2 dl mælk", "400 g kartofler"],
        instructions=PLACEHOLDER_STEPS,
        source_url="https://ex.example/halv",
    )
    before = (await env.client.get(f"/api/recipes/{r['id']}", headers=env.member)).json()
    st = await recipe_repair.run(
        app.state.sessionmaker,
        env.household_id,
        recipe_repair.RepairStatus(),
        fetcher=_fetcher({r["source_url"]: PAGE}),
        delay_s=0,
    )
    after = (await env.client.get(f"/api/recipes/{r['id']}", headers=env.member)).json()
    assert (st.instructions_filled, st.ingredients_filled) == (1, 0)
    assert after["instructions"] != PLACEHOLDER_STEPS
    # the ingredient rows are the ones that were already there, untouched
    assert [(i["id"], i["name"]) for i in after["ingredients"]] == [
        (i["id"], i["name"]) for i in before["ingredients"]
    ]


async def test_a_page_without_ingredients_is_not_a_recipe_page(env, app):
    # the extractor only accepts a JSON-LD block that has both a name and ingredients
    step_page = (
        '<script type="application/ld+json">{"@type":"Recipe","name":"Sovs",'
        '"recipeInstructions":["Rør det hele sammen."]}</script>'
    )
    r = await _recipe(
        env,
        "Sovs",
        [PLACEHOLDER_LINE],
        instructions=["Rør det hele sammen."],
        source_url="https://ex.example/sovs",
    )
    st = await recipe_repair.run(
        app.state.sessionmaker,
        env.household_id,
        recipe_repair.RepairStatus(),
        fetcher=_fetcher({r["source_url"]: step_page}),
        delay_s=0,
    )
    assert st.failed == 1 and st.problems[0]["reason"] == "page has no recipe data"
    assert st.remaining == 1  # still broken, so a later run with a better page can fix it


def test_a_draft_without_steps_only_fills_ingredients():
    r = Recipe(
        instructions=["Rør det hele sammen."],
        ingredients=[RecipeIngredient(raw=PLACEHOLDER_LINE, name=PLACEHOLDER_LINE)],
    )
    draft = SimpleNamespace(instructions=[], ingredients=["2 dl mælk"])
    assert recipe_repair._fill(r, draft) == (False, True)
    assert [i.name for i in r.ingredients] == ["mælk"]


async def test_a_page_without_recipe_data_changes_nothing(env, app):
    r = await _broken(env, "Død")
    junk = "<html><body><p>Page not found</p></body></html>"
    st = await recipe_repair.run(
        app.state.sessionmaker,
        env.household_id,
        recipe_repair.RepairStatus(),
        fetcher=_fetcher({r["source_url"]: junk}),
        delay_s=0,
    )
    assert st.failed == 1 and st.repaired == []
    assert st.problems[0]["reason"] == "page has no recipe data"
    after = (await env.client.get(f"/api/recipes/{r['id']}", headers=env.member)).json()
    assert after["instructions"] == PLACEHOLDER_STEPS
    assert after["version"] == r["version"]
    assert st.remaining == 1


async def test_network_failure_is_reported_and_skipped(env):
    await _broken(env, "Netværk")
    st = await recipe_repair.run(
        env.app.state.sessionmaker,
        env.household_id,
        recipe_repair.RepairStatus(),
        fetcher=_fetcher({}),
        delay_s=0,
    )
    assert st.failed == 1 and st.problems[0]["reason"].startswith("not_a_page")


async def test_dry_run_reads_the_page_and_writes_nothing(env, app):
    r = await _broken(env, "Tør")
    st = await recipe_repair.run(
        app.state.sessionmaker,
        env.household_id,
        recipe_repair.RepairStatus(),
        fetcher=_fetcher({r["source_url"]: PAGE}),
        delay_s=0,
        dry_run=True,
    )
    assert st.dry_run and st.instructions_filled == 1 and st.ingredients_filled == 1
    after = (await env.client.get(f"/api/recipes/{r['id']}", headers=env.member)).json()
    assert after["instructions"] == PLACEHOLDER_STEPS
    assert after["version"] == r["version"]
    assert st.remaining == 1


async def test_override_gives_a_recipe_without_link_a_page(env, app):
    r = await _recipe(env, "Uden link", [PLACEHOLDER_LINE], instructions=PLACEHOLDER_STEPS)
    found = "https://other.example/gryde"
    async with app.state.sessionmaker() as s:
        links = await recipe_repair.missing_links(s, env.household_id)
        assert [str(x.id) for x in links] == [r["id"]]
    st = await recipe_repair.run(
        app.state.sessionmaker,
        env.household_id,
        recipe_repair.RepairStatus(),
        fetcher=_fetcher({found: PAGE}),
        delay_s=0,
        overrides={uuid.UUID(r["id"]): found},
    )
    assert st.instructions_filled == 1 and st.ingredients_filled == 1
    after = (await env.client.get(f"/api/recipes/{r['id']}", headers=env.member)).json()
    assert len(after["instructions"]) == 3 and len(after["ingredients"]) == 3
    assert after["source_url"] is None  # the link we found is not written behind the user's back


async def test_remaining_and_limit(env, app):
    for n in range(3):
        await _broken(env, f"Gryde {n}")
    async with app.state.sessionmaker() as s:
        assert await recipe_repair.remaining(s, env.household_id) == 3
    st = await recipe_repair.run(
        app.state.sessionmaker,
        env.household_id,
        recipe_repair.RepairStatus(),
        fetcher=_fetcher({f"https://ex.example/gryde-{n}": PAGE for n in range(3)}),
        delay_s=0,
        limit=2,
    )
    assert st.checked == 2 and st.remaining == 1


@pytest.mark.parametrize(
    "instructions,expected",
    [
        ([], True),
        ([""], True),
        (PLACEHOLDER_STEPS, True),
        (["Could not detect instructions", "Rør rundt."], False),
        (["Rør rundt."], False),
    ],
)
def test_instructions_missing(instructions, expected):
    r = Recipe(instructions=instructions)
    assert recipe_repair.instructions_missing(r) is expected


# ---------------------------------------------------------------- reading a page with no JSON-LD

PAGE_TEXT = """Mega chips
Ingredients
1kg Maris Piper Potatoes, peeled &amp; sliced fine
1 &frac12; cup vegan butter
5 cloves garlic
Method
Preheat the oven to 180 degrees C.
Fry the pieces for 3-4 minutes on each side.
"""


def test_page_text_drops_markup_and_decodes_entities():
    html = "<style>x{y:z}</style><p>1 &frac12; cup <b>butter</b></p><script>bad()</script>"
    text = ai_reader.page_text(html)
    assert "butter" in text and "bad()" not in text and "&frac12;" not in text


@pytest.mark.parametrize("line", ["5 cloves garlic", "Preheat the oven to 180 degrees C."])
def test_a_line_that_is_on_the_page_is_believed(line):
    assert ai_reader.on_page(line, ai_reader.tokens(ai_reader.page_text(PAGE_TEXT)))


@pytest.mark.parametrize(
    "line",
    [
        "2 tbsp olive oil",  # not on the page at all
        "Fry the pieces for 30 minutes on each side",  # a number the page does not have
    ],
)
def test_a_line_that_is_not_on_the_page_is_not(line):
    assert not ai_reader.on_page(line, ai_reader.tokens(ai_reader.page_text(PAGE_TEXT)))


def test_a_model_answer_that_is_not_from_the_page_is_dropped():
    page = ai_reader.tokens(ai_reader.page_text(PAGE_TEXT))
    made_up = {
        "ingredients": ["1 cup flour", "2 eggs", "200 g sugar"],
        "instructions": ["Mix everything and bake for 40 minutes."],
    }
    assert ai_reader.believe(made_up, page) is None
    good = {
        "ingredients": ["5 cloves garlic", "1 cup flour"],
        "instructions": ["Preheat the oven to 180 degrees C."],
    }
    out = ai_reader.believe(good, page)
    assert out == {
        "ingredients": ["5 cloves garlic"],
        "instructions": ["Preheat the oven to 180 degrees C."],
    }


async def test_repair_uses_the_reader_for_a_page_without_json_ld(env, app):
    r = await _broken(env, "Uden struktur")

    async def reader(page):
        return {
            "ingredients": ["2 dl mælk", "400 g kartofler"],
            "instructions": ["Skræl kartoflerne.", "Kog dem i mælken."],
        }

    calls = []

    async def reader_with_log(page):
        calls.append(page)
        return await reader(page)

    st = await recipe_repair.run(
        app.state.sessionmaker,
        env.household_id,
        recipe_repair.RepairStatus(),
        fetcher=_fetcher({r["source_url"]: "<html><body>en side uden schema</body></html>"}),
        delay_s=0,
        reader=reader_with_log,
    )
    assert calls and st.read_by_model == 1
    after = (await env.client.get(f"/api/recipes/{r['id']}", headers=env.member)).json()
    assert after["instructions"] == ["Skræl kartoflerne.", "Kog dem i mælken."]
    assert [i["name"] for i in after["ingredients"]] == ["mælk", "kartofler"]


async def test_the_reader_is_not_asked_when_the_page_has_a_recipe(env, app):
    r = await _broken(env, "Med struktur")
    asked = []

    async def reader(page):
        asked.append(page)
        return {"ingredients": ["x"], "instructions": ["y"]}

    await recipe_repair.run(
        app.state.sessionmaker,
        env.household_id,
        recipe_repair.RepairStatus(),
        fetcher=_fetcher({r["source_url"]: PAGE}),
        delay_s=0,
        reader=reader,
    )
    assert asked == []


def test_a_video_page_is_read_through_its_own_description():
    page = (
        "<html><head><title>Apple Pie Cupcakes - YouTube</title></head><body>"
        "<p>Apple Pie Cupcakes - YouTube Om Presse Ophavsret</p>"
        '<script>var x = {"shortDescription":"Ingredients\\n2 large apples, peeled and diced\\n'
        'Instructions\\nHeat oven to 350 degrees F.","isCrawlable":true}</script></body></html>'
    )
    text = ai_reader.text_to_read(page)
    assert "2 large apples, peeled and diced" in text
    assert "Heat oven to 350 degrees F." in text
    # a line that is only in the description still counts as being on the page
    assert ai_reader.on_page("2 large apples, peeled and diced", ai_reader.tokens(text))


def test_a_page_with_words_of_its_own_keeps_them_and_ignores_the_description():
    page = (
        '<html><head><meta name="description" content="A meta line about the site">'
        "</head><body><p>" + ("Real page text. " * 40) + "</p></body></html>"
    )
    text = ai_reader.text_to_read(page)
    assert "Real page text." in text
    assert "A meta line about the site" not in text


def test_a_short_page_falls_back_to_the_meta_description():
    page = '<html><head><meta property="og:description" content="2 eggs &amp; 100 g flour">'
    assert ai_reader.page_description(page) == "2 eggs & 100 g flour"


def test_a_long_page_is_cut_to_the_recipe_window():
    page = (
        "<p>"
        + ("nyhedsbrev og reklamer. " * 900)
        + "</p><h2>Ingredienser</h2><p>"
        + ("mel " * 200)
        + "</p>"
    )
    text = ai_reader.text_to_read(page)
    assert len(text) <= ai_reader.MAX_TEXT + 1
    assert "Ingredienser" in text and "mel" in text
    assert text.index("Ingredienser") < 300  # the window starts at the recipe, not the chatter


def test_a_page_that_only_looks_like_a_heading_is_not_cut():
    # "du skal bruge" is prose here, not a heading: the method before it has to be kept
    page = (
        "<p>"
        + ("trin et. " * 2000)
        + " Du skal bruge lidt muller til at rulle det ud. "
        + ("trin to. " * 2000)
        + "</p>"
    )
    text = ai_reader.text_to_read(page)
    assert text.startswith("trin et.")


def test_a_short_page_is_not_cut():
    page = "<h2>Ingredients</h2><p>2 eggs</p>"
    assert ai_reader.text_to_read(page).endswith("2 eggs")
