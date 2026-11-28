"""Replacements: ingredients recipes ask for that the house never has under that name, and the
household's answers to them. "Same thing" becomes a product alias (the line then counts as
"have"); "stand-in" becomes an ingredient substitute (the line shows "swap")."""

import uuid
from collections import Counter
from typing import Literal

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..errors import AppError, not_found
from ..models import IngredientSubstitute, Product, ProductAlias
from ..recipes.match import Pantry, best_match, ingredient_key
from . import recipes as rsvc

Kind = Literal["same", "swap"]


class Miss(BaseModel):
    ingredient: str  # the key ("hvidløg")
    example: str  # how a recipe wrote it ("garlic cloves")
    recipes: int  # how many recipes ask for it


class SubstituteOut(BaseModel):
    id: uuid.UUID
    ingredient: str
    product_id: uuid.UUID
    product_name: str
    source: str


class ApproveIn(BaseModel):
    ingredient: str
    product_id: uuid.UUID
    kind: Kind
    source: Literal["manual", "ai"] = "manual"


async def misses(session: AsyncSession, household_id: uuid.UUID, limit: int = 200) -> list[Miss]:
    """Required ingredient lines no product matches by name (missing, not swap/staple), most
    recipes first. A line matched to a product that is merely out of stock is not a miss."""
    pantry = await rsvc.pantry(session, household_id)
    counts: Counter[str] = Counter()
    examples: dict[str, str] = {}
    for r in await rsvc.list_recipes(session, household_id):
        seen: set[str] = set()
        for ing in r.ingredients:
            if ing.optional or ing.product_id is not None or pantry.is_staple(ing.name):
                continue
            if best_match(ing.name, pantry) is not None or pantry.substitute(ing.name):
                continue
            key = ingredient_key(ing.name)
            if key and key not in seen:
                seen.add(key)
                counts[key] += 1
                examples.setdefault(key, ing.name)
    return [
        Miss(ingredient=k, example=examples[k], recipes=n) for k, n in counts.most_common(limit)
    ]


async def in_stock(session: AsyncSession, household_id: uuid.UUID) -> Pantry:
    return await rsvc.pantry(session, household_id)


async def list_substitutes(session: AsyncSession, household_id: uuid.UUID) -> list[SubstituteOut]:
    rows = (
        await session.execute(
            select(IngredientSubstitute, Product.name)
            .join(Product, Product.id == IngredientSubstitute.product_id)
            .where(IngredientSubstitute.household_id == household_id)
            .order_by(IngredientSubstitute.ingredient, Product.name)
        )
    ).all()
    return [
        SubstituteOut(
            id=s.id,
            ingredient=s.ingredient,
            product_id=s.product_id,
            product_name=name,
            source=s.source,
        )
        for s, name in rows
    ]


async def approve(session: AsyncSession, household_id: uuid.UUID, body: ApproveIn) -> str:
    """Record one answer. Returns "alias", "substitute" or "already"."""
    product = (
        await session.execute(
            select(Product).where(
                Product.id == body.product_id,
                Product.household_id == household_id,
                Product.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if product is None:
        raise not_found("Product not found")
    name = " ".join(body.ingredient.split())[:200]
    key = ingredient_key(name)
    if not key:
        raise AppError(422, "invalid_ingredient", "Ingredient name is empty")
    if body.kind == "same":
        exists = (
            await session.execute(
                select(ProductAlias.id).where(
                    ProductAlias.product_id == product.id, ProductAlias.alias == name
                )
            )
        ).first()
        if exists:
            return "already"
        session.add(ProductAlias(household_id=household_id, product_id=product.id, alias=name))
        return "alias"
    exists = (
        await session.execute(
            select(IngredientSubstitute.id).where(
                IngredientSubstitute.household_id == household_id,
                IngredientSubstitute.ingredient == key,
                IngredientSubstitute.product_id == product.id,
            )
        )
    ).first()
    if exists:
        return "already"
    session.add(
        IngredientSubstitute(
            household_id=household_id, ingredient=key, product_id=product.id, source=body.source
        )
    )
    return "substitute"


async def delete_substitute(session: AsyncSession, household_id: uuid.UUID, sid: uuid.UUID) -> None:
    s = (
        await session.execute(
            select(IngredientSubstitute).where(
                IngredientSubstitute.id == sid, IngredientSubstitute.household_id == household_id
            )
        )
    ).scalar_one_or_none()
    if s is None:
        raise not_found("Substitute not found")
    await session.delete(s)
