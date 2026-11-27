import uuid
from datetime import date, datetime
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..errors import AppError
from ..recipes.course import classify
from ..recipes.fetch import fetch_page
from ..recipes.jsonld import extract
from ..recipes.parse import parse_line
from ..schemas.recipes import (
    Availability,
    Course,
    ImportIn,
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
from ._common import parse_if_match

router = APIRouter(tags=["recipes"])


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


@router.post("/recipes/import", response_model=RecipeDraftOut)
async def import_url(
    body: ImportIn,
    request: Request,
    principal: Principal = Depends(get_principal),
):
    """Read a recipe from a public web page (schema.org JSON-LD). Returns a draft to review;
    nothing is stored until the user saves it."""
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


@router.post("/recipes", response_model=RecipeOut, status_code=201)
async def create(
    body: RecipeIn,
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
):
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
    if_match: str | None = Header(default=None),
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
):
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
