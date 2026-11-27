import uuid
from datetime import date, datetime
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..errors import AppError
from ..logging import get_logger
from ..recipes.course import classify
from ..recipes.fetch import fetch_image, fetch_page
from ..recipes.jsonld import extract
from ..recipes.parse import parse_line
from ..schemas.recipes import (
    Availability,
    Course,
    ImportIn,
    ImportSavedOut,
    ParsedLine,
    ParseIn,
    RecipeBrief,
    RecipeDraftOut,
    RecipeIn,
    RecipeOut,
    RecipeSummary,
    ShoppingFromIn,
    ShoppingFromOut,
)
from ..security import Principal, get_principal
from ..services import recipes as svc
from ..services.households import get_household_settings
from ..services.lookup.media import InvalidImage, store_image
from ._common import parse_if_match

router = APIRouter(tags=["recipes"])


log = get_logger(__name__)


async def _local_photo(request: Request, body: RecipeIn) -> RecipeIn:
    """Copy a photo from another website into our own storage. The app only shows its own
    images (Content-Security-Policy), and a copy keeps working if the site moves it."""
    url = body.image_url
    if not url or not url.startswith(("http://", "https://")):
        return body
    cfg = request.app.state.settings
    fetcher = getattr(request.app.state, "image_fetcher", None) or fetch_image
    try:
        name = await store_image(await fetcher(url, cfg.image_download_max_bytes), cfg.upload_dir)
    except (AppError, InvalidImage) as exc:
        log.info("recipe_photo_unavailable", error=type(exc).__name__)
        return body.model_copy(update={"image_url": None})  # a link the app cannot show anyway
    return body.model_copy(update={"image_url": f"/api/media/{name}"})


def _today(request: Request) -> date:
    return datetime.now(ZoneInfo(request.app.state.settings.timezone)).date()


async def _soon_days(session: AsyncSession, household_id: uuid.UUID) -> int:
    return (await get_household_settings(session, household_id)).expiry_soon_days


Include = Literal["full", "summary"]


def _filters(
    course: list[Course] | None = Query(default=None, description="Only these courses"),
    exclude_course: list[Course] | None = Query(default=None, description="Leave these out"),
    tag: list[str] | None = Query(default=None, max_length=20, description="Has every tag"),
    category: list[str] | None = Query(default=None, max_length=20, description="In any of these"),
    min_ingredients: int | None = Query(
        default=None, ge=0, le=100, description="At least this many required, non-staple lines"
    ),
) -> dict:
    return {
        "courses": course,
        "exclude_courses": exclude_course,
        "tags": tag,
        "categories": category,
        "min_ingredients": min_ingredients,
    }


def _rows(pairs, include: str) -> list:
    if include == "summary":
        return [svc.brief(r, a) for r, a in pairs]
    return [RecipeSummary(recipe=svc.recipe_out(r), availability=a) for r, a in pairs]


@router.get("/recipes", response_model=list[RecipeSummary] | list[RecipeBrief])
async def list_recipes(
    request: Request,
    q: str | None = Query(default=None, max_length=200),
    include: Include = "full",
    filters: dict = Depends(_filters),
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
):
    """All saved recipes (by title) with what is in the house. `include=summary` returns one
    flat row per recipe without instructions or ingredient objects."""
    recipes = await svc.list_recipes(
        session, principal.household_id, q, tags=filters["tags"], categories=filters["categories"]
    )
    recipes = svc.filter_course(recipes, filters["courses"], filters["exclude_courses"])
    products = await svc.pantry(session, principal.household_id)
    soon, today = await _soon_days(session, principal.household_id), _today(request)
    pairs = [(r, svc.availability(r, products, today=today, soon_days=soon)) for r in recipes]
    if filters["min_ingredients"] is not None:
        pairs = [(r, a) for r, a in pairs if a.required >= filters["min_ingredients"]]
    return _rows(pairs, include)


@router.get("/recipes/suggest", response_model=list[RecipeSummary] | list[RecipeBrief])
async def what_can_we_cook(
    request: Request,
    max_minutes: int | None = Query(default=None, ge=1, le=10_000),
    servings: int | None = Query(default=None, ge=1, le=100),
    max_missing: int = Query(default=1, ge=0, le=100),
    show_all: bool = Query(default=False, description="Every recipe, ignoring max_missing"),
    limit: int | None = Query(default=None, ge=1, le=10_000, description="Default: all"),
    q: str | None = Query(default=None, max_length=200, description="Title or tag contains"),
    include: Include = "full",
    filters: dict = Depends(_filters),
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
):
    """Saved recipes ranked by what is in the house right now (deterministic, no AI). Only
    recipes missing at most `max_missing` required ingredients (default: one shopping trip
    item) are suggested; see services.recipes.rank for the order. Returns every match unless
    `limit` is given (clients page the list themselves). `show_all` keeps every recipe in the
    same order (most of it in the house first)."""
    recipes = await svc.list_recipes(
        session, principal.household_id, q, tags=filters["tags"], categories=filters["categories"]
    )
    recipes = svc.filter_course(recipes, filters["courses"], filters["exclude_courses"])
    products = await svc.pantry(session, principal.household_id)
    soon, today = await _soon_days(session, principal.household_id), _today(request)
    pairs = [
        (r, svc.availability(r, products, servings=servings, today=today, soon_days=soon))
        for r in recipes
    ]
    ranked = svc.rank(
        pairs,
        max_minutes=max_minutes,
        max_missing=None if show_all else max_missing,
        min_ingredients=filters["min_ingredients"],
    )
    return _rows(ranked if limit is None else ranked[:limit], include)


@router.post("/recipes/parse", response_model=list[ParsedLine])
async def parse(body: ParseIn, principal: Principal = Depends(get_principal)):
    """Preview how ingredient lines are understood (used while typing a recipe)."""
    out = []
    for line in body.lines:
        if line.strip():
            p = parse_line(line)
            out.append(ParsedLine(**p.__dict__))
    return out


async def _draft(body: ImportIn, request: Request) -> RecipeDraftOut:
    draft, final_url = (extract(body.html), body.url.strip()) if body.html else (None, "")
    if draft is None:  # nothing usable sent along: read the page on the server
        fetcher = getattr(request.app.state, "recipe_fetcher", None) or fetch_page
        final_url, page = await fetcher(body.url.strip())
        draft = extract(page)
    if draft is None:
        raise AppError(
            422,
            "no_recipe_found",
            "No recipe data was found on that page. You can still type or paste it in.",
        )
    course = classify(draft.title, draft.tags, [parse_line(x).name for x in draft.ingredients])
    return RecipeDraftOut(**draft.__dict__, source_url=final_url, course=course)


@router.post("/recipes/import", response_model=RecipeDraftOut)
async def import_url(
    body: ImportIn,
    request: Request,
    principal: Principal = Depends(get_principal),
):
    """Read a recipe from a public web page (schema.org JSON-LD). Returns a draft to review;
    nothing is stored until the user saves it."""
    return await _draft(body, request)


def _recipe_in(d: RecipeDraftOut) -> RecipeIn:
    fields = dict(
        title=d.title[:200],
        description=(d.description or None) and d.description[:2000],
        servings=min(max(d.servings or 4, 1), 100),
        prep_min=d.prep_min,
        cook_min=d.cook_min,
        instructions=d.instructions[:80],
        tags=d.tags[:20],
        course=d.course,
        source_url=d.source_url,
        source_name=d.source_name,
        image_url=d.image_url,
        ingredients=[{"raw": x} for x in d.ingredients[:100]],
    )
    try:
        return RecipeIn(**fields)
    except ValidationError:  # an odd photo address should not lose the recipe
        return RecipeIn(**{**fields, "image_url": None})


@router.post("/recipes/import/save", response_model=ImportSavedOut)
async def import_and_save(
    body: ImportIn,
    request: Request,
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
):
    """Import and save in one step (browser extension). A page that is already saved is not
    saved again: that recipe comes back with `created: false`."""
    draft = await _draft(body, request)
    existing = await svc.find_by_source(
        session, principal.household_id, {body.url.strip(), draft.source_url}
    )
    if existing is not None:
        return ImportSavedOut(recipe=svc.recipe_out(existing), created=False)
    body_in = await _local_photo(request, _recipe_in(draft))
    r = await svc.create_recipe(session, principal.household_id, body_in, principal.user_id)
    await session.commit()
    return ImportSavedOut(recipe=svc.recipe_out(r), created=True)


@router.post("/recipes", response_model=RecipeOut, status_code=201)
async def create(
    body: RecipeIn,
    request: Request,
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
):
    body = await _local_photo(request, body)
    r = await svc.create_recipe(session, principal.household_id, body, principal.user_id)
    await session.commit()
    return svc.recipe_out(r)


@router.get("/recipes/{rid}", response_model=RecipeOut)
async def get(
    rid: uuid.UUID,
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
):
    return svc.recipe_out(await svc.get_recipe(session, principal.household_id, rid))


@router.put("/recipes/{rid}", response_model=RecipeOut)
async def update(
    rid: uuid.UUID,
    body: RecipeIn,
    request: Request,
    if_match: str | None = Header(default=None),
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
):
    body = await _local_photo(request, body)
    r = await svc.update_recipe(
        session, principal.household_id, rid, body, parse_if_match(if_match)
    )
    await session.commit()
    return svc.recipe_out(r)


@router.delete("/recipes/{rid}", status_code=204)
async def delete(
    rid: uuid.UUID,
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
):
    await svc.delete_recipe(session, principal.household_id, rid)
    await session.commit()
    return Response(status_code=204)


@router.get("/recipes/{rid}/availability", response_model=Availability)
async def recipe_availability(
    rid: uuid.UUID,
    request: Request,
    servings: int | None = Query(default=None, ge=1, le=100),
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
):
    """Per ingredient: in stock / low / missing, and how much to deduct when cooking (in the
    product's stock unit). Read-only."""
    r = await svc.get_recipe(session, principal.household_id, rid)
    products = await svc.pantry(session, principal.household_id)
    return svc.availability(
        r,
        products,
        servings=servings,
        today=_today(request),
        soon_days=await _soon_days(session, principal.household_id),
    )


@router.post("/recipes/{rid}/shopping", response_model=ShoppingFromOut)
async def missing_to_shopping(
    rid: uuid.UUID,
    body: ShoppingFromIn,
    request: Request,
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
):
    r = await svc.get_recipe(session, principal.household_id, rid)
    products = await svc.pantry(session, principal.household_id)
    a = svc.availability(r, products, servings=body.servings, today=_today(request))
    added, skipped = await svc.add_missing_to_shopping(
        session, principal.household_id, r, a, body.ingredient_ids
    )
    await session.commit()
    return ShoppingFromOut(added=added, skipped=skipped)
