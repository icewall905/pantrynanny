"""Meal plan. Planning a meal never changes stock: ingredients are only deducted when the user
cooks it and confirms the amounts (see the recipe "cook" flow)."""

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..errors import AppError, not_found
from ..models import MealPlanEntry, Recipe
from ..schemas.recipes import MealIn, MealOut, MealPatch, PlanShoppingIn, ShoppingFromOut
from ..schemas.shopping import ShoppingCreate
from ..security import Principal, get_principal
from ..services import recipes as rsvc
from ..services.shopping import add_item

router = APIRouter(tags=["meal-plan"])


def _out(e: MealPlanEntry, recipe: Recipe | None, missing: int | None) -> MealOut:
    return MealOut(
        id=e.id,
        day=e.day,
        slot=e.slot,
        recipe_id=e.recipe_id,
        recipe_title=recipe.title if recipe else None,
        title=e.title,
        servings=e.servings,
        note=e.note,
        cooked_at=e.cooked_at,
        missing=missing,
    )


async def _entries(
    session: AsyncSession, household_id: uuid.UUID, start: date, days: int
) -> list[MealPlanEntry]:
    return list(
        (
            await session.execute(
                select(MealPlanEntry)
                .where(
                    MealPlanEntry.household_id == household_id,
                    MealPlanEntry.day >= start,
                    MealPlanEntry.day < start + timedelta(days=days),
                )
                .order_by(MealPlanEntry.day, MealPlanEntry.slot, MealPlanEntry.created_at)
            )
        )
        .scalars()
        .all()
    )


async def _recipes(session: AsyncSession, household_id: uuid.UUID, ids: set) -> dict:
    ids = {i for i in ids if i}
    if not ids:
        return {}
    rows = (
        await session.execute(
            select(Recipe).where(Recipe.id.in_(ids), Recipe.household_id == household_id)
        )
    ).scalars()
    return {r.id: r for r in rows}


async def _get(session: AsyncSession, household_id: uuid.UUID, eid: uuid.UUID) -> MealPlanEntry:
    e = (
        await session.execute(
            select(MealPlanEntry).where(
                MealPlanEntry.id == eid, MealPlanEntry.household_id == household_id
            )
        )
    ).scalar_one_or_none()
    if e is None:
        raise not_found("Meal not found")
    return e


@router.get("/meal-plan", response_model=list[MealOut])
async def list_plan(
    start: date,
    days: int = Query(default=7, ge=1, le=62),
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
):
    entries = await _entries(session, principal.household_id, start, days)
    recipes = await _recipes(session, principal.household_id, {e.recipe_id for e in entries})
    products = await rsvc.pantry(session, principal.household_id) if recipes else []
    out = []
    for e in entries:
        r = recipes.get(e.recipe_id)
        missing = (
            rsvc.availability(r, products, servings=e.servings).missing
            if r and not r.deleted_at
            else None
        )
        out.append(_out(e, r, missing))
    return out


@router.post("/meal-plan", response_model=MealOut, status_code=201)
async def add_meal(
    body: MealIn,
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
):
    recipe = None
    if body.recipe_id:
        recipe = await rsvc.get_recipe(session, principal.household_id, body.recipe_id)
    elif not (body.title and body.title.strip()):
        raise AppError(422, "validation_error", "recipe_id or title is required")
    e = MealPlanEntry(household_id=principal.household_id, **body.model_dump())
    session.add(e)
    await session.commit()
    return _out(e, recipe, None)


@router.patch("/meal-plan/{eid}", response_model=MealOut)
async def patch_meal(
    eid: uuid.UUID,
    body: MealPatch,
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
):
    e = await _get(session, principal.household_id, eid)
    sent = body.model_fields_set
    for f in ("day", "slot", "servings", "note", "title"):
        if f in sent and (getattr(body, f) is not None or f in ("note", "servings", "title")):
            setattr(e, f, getattr(body, f))
    if "cooked" in sent and body.cooked is not None:
        e.cooked_at = datetime.now(UTC) if body.cooked else None
    e.updated_at = datetime.now(UTC)
    await session.commit()
    recipes = await _recipes(session, principal.household_id, {e.recipe_id})
    return _out(e, recipes.get(e.recipe_id), None)


@router.delete("/meal-plan/{eid}", status_code=204)
async def delete_meal(
    eid: uuid.UUID,
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
):
    e = await _get(session, principal.household_id, eid)
    await session.delete(e)
    await session.commit()
    return Response(status_code=204)


@router.post("/meal-plan/shopping", response_model=ShoppingFromOut)
async def plan_to_shopping(
    body: PlanShoppingIn,
    request: Request,
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
):
    """Put everything the planned (not yet cooked) recipes need but the house lacks on the list.
    Needs are summed per product across meals before comparing with stock."""
    hh = principal.household_id
    entries = [e for e in await _entries(session, hh, body.start, body.days) if not e.cooked_at]
    recipes = await _recipes(session, hh, {e.recipe_id for e in entries})
    products = await rsvc.pantry(session, hh)
    by_product: dict = {}
    by_name: dict[str, str] = {}
    for e in entries:
        r = recipes.get(e.recipe_id)
        if not r or r.deleted_at:
            continue
        a = rsvc.availability(r, products, servings=e.servings)
        for it in a.items:
            if it.status in ("staple", "optional") or it.ingredient.optional:
                continue
            if it.product:
                need = it.need if it.need is not None else Decimal(1)
                cur = by_product.setdefault(it.product.id, [it.product, Decimal(0), r.title])
                cur[1] += need
            elif it.status == "missing":
                by_name.setdefault(it.ingredient.name.lower(), it.ingredient.name)
    added: list[str] = []
    skipped: list[str] = []
    for pid, (p, need, title) in by_product.items():
        short = need - p.total_quantity
        if short <= 0:
            skipped.append(p.name)
            continue
        qty = max(Decimal(1), short.to_integral_value(rounding="ROUND_UP"))
        await add_item(session, hh, ShoppingCreate(product_id=pid, quantity=qty, note=title[:500]))
        added.append(p.name)
    for name in by_name.values():
        await add_item(session, hh, ShoppingCreate(name=name[:200], quantity=Decimal(1)))
        added.append(name)
    await session.commit()
    return ShoppingFromOut(added=added, skipped=skipped)
