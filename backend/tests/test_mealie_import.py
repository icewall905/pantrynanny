import io

import httpx
from PIL import Image

from pantrynanny.services import mealie_import as mi


def _png() -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (40, 30), (200, 80, 20)).save(out, "PNG")
    return out.getvalue()


SOUP = {
    "id": "00000000-0000-4000-8000-000000000001",
    "slug": "black-bean-soup",
    "name": "Black Bean Soup",
    "image": "nlTE",
    "recipeServings": 0.0,
    "recipeYieldQuantity": 4.0,
    "prepTimeSeconds": 900,
    "performTimeSeconds": 2700,
    "description": "Easy soup",
    "recipeCategory": [{"name": "Dinner"}, {"name": "Lunch"}],
    "tags": [{"name": "Winter Recipe"}],
    "orgURL": "https://www.loveandlemons.com/black-bean-soup-recipe/",
}
CAKE = {
    "id": "00000000-0000-4000-8000-000000000002",
    "slug": "french-apple-cake",
    "name": "French Apple Cake",
    "image": "dn8D",
    "totalTime": "1 hour 20 minutes",
    "recipeCategory": [{"name": "Dessert"}],
    "tags": [],
    "orgURL": None,
}
DETAIL = {
    "black-bean-soup": {
        "recipeIngredient": [
            {"display": "2 tablespoons extra virgin olive oil"},
            {"display": "1 yellow onion medium, diced"},
            {"display": ""},
        ],
        "recipeInstructions": [{"text": "Heat the oil."}, {"text": "  "}, {"text": "Simmer."}],
    },
    "french-apple-cake": {"recipeIngredient": [{"note": "4 apples"}], "recipeInstructions": []},
}


def _mealie(calls: list[str], *, image_ok=True):
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.headers["Authorization"] == "Bearer tok"
        calls.append(req.url.path)
        if req.url.path == "/api/recipes":
            assert req.url.params["perPage"] == str(mi.PER_PAGE)
            return httpx.Response(200, json={"items": [SOUP, CAKE], "total_pages": 1})
        if req.url.path.startswith("/api/recipes/"):
            slug = req.url.path.rsplit("/", 1)[1]
            return httpx.Response(
                200, json={**(SOUP if slug == SOUP["slug"] else CAKE), **DETAIL[slug]}
            )
        if req.url.path.startswith("/api/media/recipes/"):
            return httpx.Response(200, content=_png()) if image_ok else httpx.Response(404)
        return httpx.Response(404)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_times_and_recipe_shape():
    assert mi.times(SOUP) == (15, 45)
    assert mi.times(CAKE) == (None, 80)
    assert mi.times({"prepTime": "15 min", "cookTime": "2 timer"}) == (15, 120)
    body = mi.recipe_in({**SOUP, **DETAIL["black-bean-soup"]})
    assert body.servings == 4 and body.categories == ["Dinner", "Lunch"]
    assert body.course == "lunch" and body.source_name == "loveandlemons.com"
    assert [i.raw for i in body.ingredients] == [
        "2 tablespoons extra virgin olive oil",
        "1 yellow onion medium, diced",
    ]
    assert body.instructions == ["Heat the oil.", "Simmer."]


async def test_import_creates_then_rerun_updates_existing(env, app, tmp_path):
    c, h = env.client, env.member
    # an earlier import without photos or categories, matched by source URL / title
    await c.post(
        "/api/recipes",
        json={"title": "Black bean soup (mine)", "source_url": SOUP["orgURL"], "tags": ["Suppe"]},
        headers=h,
    )
    sm = app.state.sessionmaker
    calls: list[str] = []
    async with _mealie(calls) as client:
        st = await mi.run(
            sm,
            env.household_id,
            mi.MealieClient("http://mealie.test/", "tok", client),
            upload_dir=str(tmp_path),
        )
    assert (st.seen, st.created, st.updated, st.images, st.failed) == (2, 1, 1, 2, 0)
    assert "/api/recipes/black-bean-soup" not in calls  # existing: no detail fetch needed

    rows = {
        r["recipe"]["title"]: r["recipe"] for r in (await c.get("/api/recipes", headers=h)).json()
    }
    soup, cake = rows["Black bean soup (mine)"], rows["French Apple Cake"]
    assert soup["categories"] == ["Dinner", "Lunch"]
    assert soup["tags"] == ["Suppe", "Winter Recipe"]
    assert (soup["prep_min"], soup["cook_min"]) == (15, 45)
    assert soup["image_url"].startswith("/api/media/") and soup["image_url"].endswith(".webp")
    assert (tmp_path / soup["image_url"].rsplit("/", 1)[1]).is_file()
    assert cake["categories"] == ["Dessert"] and cake["course"] == "dessert"
    assert [i["raw"] for i in cake["ingredients"]] == ["4 apples"]

    # category filter and search
    r = await c.get("/api/recipes?category=dessert", headers=h)
    assert [x["recipe"]["title"] for x in r.json()] == ["French Apple Cake"]
    r = await c.get("/api/recipes?q=lunch", headers=h)
    assert [x["recipe"]["title"] for x in r.json()] == ["Black bean soup (mine)"]

    # re-run: nothing duplicated, photos kept
    calls.clear()
    async with _mealie(calls) as client:
        st = await mi.run(
            sm,
            env.household_id,
            mi.MealieClient("http://mealie.test", "tok", client),
            upload_dir=str(tmp_path),
        )
    assert (st.created, st.updated, st.unchanged, st.images) == (0, 0, 2, 0)
    assert not any(p.startswith("/api/media/") for p in calls)
    assert len((await c.get("/api/recipes", headers=h)).json()) == 2

    # editing in an older client (no categories sent) keeps them; local image URL is accepted
    full = (await c.get(f"/api/recipes/{soup['id']}", headers=h)).json()
    body = {k: full[k] for k in ("title", "servings", "tags", "image_url", "source_url")}
    r = await c.put(f"/api/recipes/{soup['id']}", json=body, headers=h)
    assert r.status_code == 200, r.text
    assert (
        r.json()["categories"] == ["Dinner", "Lunch"] and r.json()["image_url"] == soup["image_url"]
    )


async def test_no_create_and_missing_photo(env, app, tmp_path):
    calls: list[str] = []
    async with _mealie(calls, image_ok=False) as client:
        st = await mi.run(
            app.state.sessionmaker,
            env.household_id,
            mi.MealieClient("http://mealie.test", "tok", client),
            create=False,
            upload_dir=str(tmp_path),
        )
    assert (st.skipped, st.created, st.images) == (2, 0, 0)
    async with _mealie(calls, image_ok=False) as client:
        st = await mi.run(
            app.state.sessionmaker,
            env.household_id,
            mi.MealieClient("http://mealie.test", "tok", client),
            upload_dir=str(tmp_path),
        )
    assert (st.created, st.images, st.image_failed, st.failed) == (2, 0, 2, 0)
