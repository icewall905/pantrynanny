"""Recipes: storage, pantry availability, "what can we cook" and shopping for missing items.

Nothing here changes stock. Cooking a recipe deducts ingredients through the normal stock ops
(client-generated, idempotent, undoable) after the user has confirmed the amounts.
"""

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_UP, Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..errors import AppError, conflict, not_found
from ..models import Product, ProductAlias, Recipe, RecipeIngredient
from ..recipes.match import (
    ProductCandidate,
    best_match,
    is_staple,
    needed_in_stock_units,
    stock_in_base,
)
from ..recipes.parse import parse_line, to_base
from ..schemas.recipes import (
    Availability,
    IngredientAvailability,
    IngredientOut,
    MatchedProduct,
    RecipeIn,
    RecipeOut,
)
from ..schemas.shopping import ShoppingCreate
from .inventory import batches_for, build_view
from .shopping import add_item, has_open_named

ZERO = Decimal(0)


def recipe_out(r: Recipe) -> RecipeOut:
    return RecipeOut(
        id=r.id,
        version=r.version,
        title=r.title,
        description=r.description,
        servings=r.servings,
        prep_min=r.prep_min,
        cook_min=r.cook_min,
        instructions=list(r.instructions or []),
        tags=list(r.tags or []),
        source_url=r.source_url,
        source_name=r.source_name,
        image_url=r.image_url,
        ingredients=[ingredient_out(i) for i in r.ingredients],
        created_at=r.created_at,
        updated_at=r.updated_at,
    )


def ingredient_out(i: RecipeIngredient) -> IngredientOut:
    return IngredientOut(
        id=i.id,
        position=i.position,
        raw=i.raw,
        name=i.name,
        quantity=i.quantity,
        unit=i.unit,
        note=i.note,
        optional=i.optional,
        product_id=i.product_id,
    )


async def get_recipe(session: AsyncSession, household_id: uuid.UUID, rid: uuid.UUID) -> Recipe:
    r = (
        await session.execute(
            select(Recipe)
            .where(Recipe.id == rid, Recipe.household_id == household_id)
            .where(Recipe.deleted_at.is_(None))
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if r is None:
        raise not_found("Recipe not found")
    return r


async def list_recipes(
    session: AsyncSession, household_id: uuid.UUID, q: str | None = None
) -> list[Recipe]:
    stmt = select(Recipe).where(Recipe.household_id == household_id, Recipe.deleted_at.is_(None))
    if q:
        like = f"%{q.strip().lower()}%"
        stmt = stmt.where(
            or_(
                func.lower(Recipe.title).like(like),
                func.lower(func.array_to_string(Recipe.tags, " ")).like(like),
            )
        )
    return list((await session.execute(stmt.order_by(Recipe.title))).scalars().all())


async def _assert_products(session: AsyncSession, household_id: uuid.UUID, ids: set[uuid.UUID]):
    if not ids:
        return
    found = set(
        (
            await session.execute(
                select(Product.id).where(Product.id.in_(ids), Product.household_id == household_id)
            )
        )
        .scalars()
        .all()
    )
    if ids - found:
        raise AppError(422, "validation_error", "Unknown product in ingredient list")


def _ingredients(body: RecipeIn, household_id: uuid.UUID) -> list[RecipeIngredient]:
    out = []
    for pos, ing in enumerate(body.ingredients):
        p = parse_line(ing.raw)
        out.append(
            RecipeIngredient(
                position=pos,
                raw=p.raw,
                name=p.name,
                quantity=p.quantity,
                unit=p.unit,
                note=p.note,
                optional=p.optional if ing.optional is None else ing.optional,
                product_id=ing.product_id,
            )
        )
    return out


async def create_recipe(
    session: AsyncSession, household_id: uuid.UUID, body: RecipeIn, user_id: uuid.UUID | None
) -> Recipe:
    await _assert_products(
        session, household_id, {i.product_id for i in body.ingredients if i.product_id}
    )
    r = Recipe(
        household_id=household_id,
        created_by=user_id,
        **body.model_dump(exclude={"ingredients"}),
        ingredients=_ingredients(body, household_id),
    )
    session.add(r)
    await session.flush()
    return await get_recipe(session, household_id, r.id)


async def update_recipe(
    session: AsyncSession,
    household_id: uuid.UUID,
    rid: uuid.UUID,
    body: RecipeIn,
    if_match: int | None,
) -> Recipe:
    r = await get_recipe(session, household_id, rid)
    if if_match is not None and r.version != if_match:
        raise conflict("version_conflict", "Recipe was changed by someone else")
    await _assert_products(
        session, household_id, {i.product_id for i in body.ingredients if i.product_id}
    )
    for k, v in body.model_dump(exclude={"ingredients"}).items():
        setattr(r, k, v)
    r.ingredients = _ingredients(body, household_id)
    r.version += 1
    r.updated_at = datetime.now(UTC)
    await session.flush()
    return await get_recipe(session, household_id, rid)


async def delete_recipe(session: AsyncSession, household_id: uuid.UUID, rid: uuid.UUID) -> None:
    r = await get_recipe(session, household_id, rid)
    r.deleted_at = datetime.now(UTC)
    await session.flush()


# --------------------------------------------------------------------------- pantry matching


async def pantry(session: AsyncSession, household_id: uuid.UUID) -> list[ProductCandidate]:
    products = list(
        (
            await session.execute(
                select(Product).where(
                    Product.household_id == household_id,
                    Product.deleted_at.is_(None),
                    Product.status != "unknown",
                )
            )
        )
        .scalars()
        .all()
    )
    aliases: dict[uuid.UUID, list[str]] = {}
    for pid, alias in (
        await session.execute(
            select(ProductAlias.product_id, ProductAlias.alias).where(
                ProductAlias.household_id == household_id
            )
        )
    ).all():
        aliases.setdefault(pid, []).append(alias)
    batches = await batches_for(session, household_id, [p.id for p in products])
    out = []
    for p in products:
        v = build_view(p, batches[p.id])
        out.append(
            ProductCandidate(
                id=p.id,
                name=p.name,
                aliases=aliases.get(p.id, []),
                total=max(v.total, ZERO),
                stock_unit=p.stock_unit,
                package_size=p.package_size,
                package_unit=p.package_unit,
                next_expiry=v.next_expiry,
                image_url=f"/api/media/{p.image_path}" if p.image_path else None,
            )
        )
    return out


def availability(
    r: Recipe,
    products: list[ProductCandidate],
    *,
    servings: int | None = None,
    today: date | None = None,
    soon_days: int = 3,
) -> Availability:
    servings = servings or r.servings
    factor = Decimal(servings) / Decimal(r.servings or 1)
    by_id = {p.id: p for p in products}
    soon = (today or date.today()) + timedelta(days=soon_days)
    items: list[IngredientAvailability] = []
    have = missing = required = 0
    expiring: list[str] = []
    for ing in r.ingredients:
        linked = ing.product_id is not None and ing.product_id in by_id
        p = by_id[ing.product_id] if linked else best_match(ing.name, products)
        qty = ing.quantity * factor if ing.quantity is not None else None
        need = needed_in_stock_units(qty, ing.unit, p) if p else None
        enough: bool | None = None
        if p and p.total > 0:
            if need is not None:
                enough = p.total >= need
            elif qty is not None:
                have_base, need_base = stock_in_base(p), to_base(qty, ing.unit)
                if have_base and need_base and have_base[0] == need_base[0]:
                    enough = have_base[1] >= need_base[1]
        in_stock = bool(p and p.total > 0)
        is_soon = bool(in_stock and p and p.next_expiry and p.next_expiry <= soon)
        if is_staple(ing.name) and not linked:
            status = "staple"
        elif ing.optional:
            status = "have" if in_stock else "optional"
        else:
            required += 1
            if in_stock and enough is not False:
                status, have = "have", have + 1
            elif in_stock:
                status, have = "low", have + 1
            else:
                status, missing = "missing", missing + 1
        if is_soon and p:
            expiring.append(p.name)
        items.append(
            IngredientAvailability(
                ingredient=ingredient_out(ing),
                status=status,  # type: ignore[arg-type]
                product=MatchedProduct(
                    id=p.id,  # type: ignore[arg-type]
                    name=p.name,
                    total_quantity=p.total,
                    stock_unit=p.stock_unit,
                    image_url=p.image_url,
                    next_expiry=p.next_expiry,  # type: ignore[arg-type]
                )
                if p
                else None,
                linked=linked,
                need=need,
                enough=enough,
                expiring=is_soon,
            )
        )
    return Availability(
        recipe_id=r.id,
        servings=servings,
        have=have,
        missing=missing,
        required=required,
        coverage=round(have / required, 3) if required else 1.0,
        uses_expiring=list(dict.fromkeys(expiring)),
        items=items,
    )


def rank(
    pairs: list[tuple[Recipe, Availability]], *, max_minutes: int | None = None
) -> list[tuple[Recipe, Availability]]:
    """Cookable now first, then most of it in the house, then what uses up expiring food."""
    out = []
    for r, a in pairs:
        total = (r.prep_min or 0) + (r.cook_min or 0)
        if max_minutes is not None and total and total > max_minutes:
            continue
        out.append((r, a))
    out.sort(
        key=lambda x: (
            x[1].missing > 0,
            -x[1].coverage,
            -len(x[1].uses_expiring),
            x[1].missing,
            (x[0].prep_min or 0) + (x[0].cook_min or 0),
            x[0].title.lower(),
        )
    )
    return out


async def add_missing_to_shopping(
    session: AsyncSession,
    household_id: uuid.UUID,
    r: Recipe,
    a: Availability,
    ingredient_ids: list[uuid.UUID] | None,
) -> tuple[list[str], list[str]]:
    wanted = set(ingredient_ids) if ingredient_ids else None
    added: list[str] = []
    skipped: list[str] = []
    for it in a.items:
        ing = it.ingredient
        if wanted is not None:
            if ing.id not in wanted:
                continue
        elif it.status not in ("missing", "low"):
            continue
        if it.status == "staple" or (
            not it.product and await has_open_named(session, household_id, ing.name)
        ):
            skipped.append(ing.name)
            continue
        # whole packages: 0.2 l of a 1 l carton still means buying one carton
        qty = max(Decimal(1), (it.need or Decimal(1)).to_integral_value(ROUND_UP))
        body = (
            ShoppingCreate(product_id=it.product.id, quantity=qty)
            if it.product
            else ShoppingCreate(name=ing.name[:200], quantity=Decimal(1))
        )
        body.note = f"{r.title}"[:500]
        await add_item(session, household_id, body)
        added.append(it.product.name if it.product else ing.name)
    return added, skipped
