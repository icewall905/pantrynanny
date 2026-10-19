import uuid
from datetime import date, datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..errors import AppError
from ..recipes.fetch import fetch_page
from ..recipes.jsonld import extract
from ..recipes.parse import parse_line
from ..schemas.recipes import (
    Availability,
    ImportIn,
    ParsedLine,
    ParseIn,
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


@router.get("/recipes", response_model=list[RecipeSummary])
async def list_recipes(
    request: Request,
    q: str | None = Query(default=None, max_length=200),
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
):
    recipes = await svc.list_recipes(session, principal.household_id, q)
    products = await svc.pantry(session, principal.household_id)
    soon, today = await _soon_days(session, principal.household_id), _today(request)
    return [
        RecipeSummary(
            recipe=svc.recipe_out(r),
            availability=svc.availability(r, products, today=today, soon_days=soon),
        )
        for r in recipes
    ]


@router.get("/recipes/suggest", response_model=list[RecipeSummary])
async def what_can_we_cook(
    request: Request,
    max_minutes: int | None = Query(default=None, ge=1, le=10_000),
    servings: int | None = Query(default=None, ge=1, le=100),
    limit: int = Query(default=20, ge=1, le=100),
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
):
    """Saved recipes ranked by what is in the house right now (deterministic, no AI)."""
    recipes = await svc.list_recipes(session, principal.household_id)
    products = await svc.pantry(session, principal.household_id)
    soon, today = await _soon_days(session, principal.household_id), _today(request)
    pairs = [
        (r, svc.availability(r, products, servings=servings, today=today, soon_days=soon))
        for r in recipes
    ]
    return [
        RecipeSummary(recipe=svc.recipe_out(r), availability=a)
        for r, a in svc.rank(pairs, max_minutes=max_minutes)[:limit]
    ]


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
    return RecipeDraftOut(**draft.__dict__, source_url=final_url)


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
