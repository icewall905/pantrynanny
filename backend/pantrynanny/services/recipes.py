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
from ..recipes.course import classify
from ..recipes.match import (
    Pantry,
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
    RecipeBrief,
    RecipeIn,
    RecipeOut,
)
from .households import get_household_settings
from .inventory import batches_for, build_view
from .shopping import add_need, shopping_amount

ZERO = Decimal(0)
# what some importers saved instead of the ingredient list
UNPARSED = {"could not detect ingredients"}


def minutes(r: Recipe) -> int | None:
    if r.prep_min is None and r.cook_min is None:
        return None
    return (r.prep_min or 0) + (r.cook_min or 0)


_COURSE_CACHE: dict[tuple[uuid.UUID, int], str | None] = {}


def course_of(r: Recipe) -> str | None:
    """The stored course, or (for recipes saved before courses existed) the classifier's guess."""
    if r.course:
        return r.course
    key = (r.id, r.version)
    if key not in _COURSE_CACHE:
        if len(_COURSE_CACHE) > 20_000:
            _COURSE_CACHE.clear()
        _COURSE_CACHE[key] = classify(r.title, list(r.tags or []), [i.name for i in r.ingredients])
    return _COURSE_CACHE[key]


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
        categories=list(r.categories or []),
        course=course_of(r),  # type: ignore[arg-type]
        minutes=minutes(r),
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


async def find_by_source(
    session: AsyncSession, household_id: uuid.UUID, urls: set[str]
) -> Recipe | None:
    """The oldest saved recipe imported from one of these addresses."""
    return (
        await session.execute(
            select(Recipe)
            .where(Recipe.household_id == household_id, Recipe.deleted_at.is_(None))
            .where(Recipe.source_url.in_([u for u in urls if u]))
            .order_by(Recipe.created_at, Recipe.id)
            .limit(1)
        )
    ).scalar_one_or_none()


async def list_recipes(
    session: AsyncSession,
    household_id: uuid.UUID,
    q: str | None = None,
    *,
    tags: list[str] | None = None,
    categories: list[str] | None = None,
) -> list[Recipe]:
    """Ordered by title, then id (stable for machine clients)."""
    stmt = select(Recipe).where(Recipe.household_id == household_id, Recipe.deleted_at.is_(None))
    if q:
        like = f"%{q.strip().lower()}%"
        stmt = stmt.where(
            or_(
                func.lower(Recipe.title).like(like),
                func.lower(func.array_to_string(Recipe.tags, " ")).like(like),
                func.lower(func.array_to_string(Recipe.categories, " ")).like(like),
            )
        )
    recipes = list((await session.execute(stmt.order_by(Recipe.title, Recipe.id))).scalars().all())
    if tags:  # every tag must be there (case-insensitive)
        want = {t.strip().lower() for t in tags if t.strip()}
        recipes = [r for r in recipes if want <= {t.lower() for t in r.tags or []}]
    if categories:  # any of them (case-insensitive)
        cats = {c.strip().lower() for c in categories if c.strip()}
        recipes = [r for r in recipes if cats & {c.lower() for c in r.categories or []}]
    return recipes


def filter_course(
    recipes: list[Recipe], courses: list[str] | None, exclude: list[str] | None
) -> list[Recipe]:
    if courses:
        recipes = [r for r in recipes if course_of(r) in courses]
    if exclude:
        recipes = [r for r in recipes if course_of(r) not in exclude]
    return recipes


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
    if r.course is None:
        r.course = classify(r.title, r.tags, [i.name for i in r.ingredients])
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
        if k in ("course", "categories") and k not in body.model_fields_set:
            continue  # clients that do not know about these keep the stored value
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


async def pantry(session: AsyncSession, household_id: uuid.UUID) -> Pantry:
    """The household's products with stock, plus its staples list."""
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
    settings = await get_household_settings(session, household_id)
    return Pantry(out, staples=settings.staples)


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
    staple = products.is_staple if isinstance(products, Pantry) else is_staple
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
        if p is None and staple(ing.name):
            # only when the household does not keep it as a product: a stocked-out product
            # is reported as missing like any other
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
    pairs: list[tuple[Recipe, Availability]],
    *,
    max_minutes: int | None = None,
    max_missing: int | None = None,
    min_ingredients: int | None = None,
    courses: list[str] | None = None,
    exclude_courses: list[str] | None = None,
) -> list[tuple[Recipe, Availability]]:
    """Order recipes for "what can we cook now".

    Filters: total time, required ingredients still missing, at least `min_ingredients`
    required (non-staple, non-optional) ingredients, and course. A recipe with nothing to check
    (every line a staple or optional) is never "cookable".

    Sort, most important first (with `max_missing=None` every recipe is kept; one with
    nothing to check goes last):
    1. fewest missing ingredients ("cookable now" first, then one shopping item, ...);
    2. smoothed coverage have / (required + 2). The +2 is a prior of two unknown ingredients,
       so a short list has to earn its place: 2 of 2 scores 0.50, 5 of 5 scores 0.71 and 8 of 9
       scores 0.73. A two-line "chocolate-dipped apricots" no longer beats a real dish just
       for being short, while among dishes of similar size more of it in the house still wins;
    3. more expiring food used up; 4. more ingredients in the house (a fuller dish);
    5. quicker; 6. title, then id, so the order is stable.
    """
    out = []
    for r, a in pairs:
        total = minutes(r)
        if max_minutes is not None and total and total > max_minutes:
            continue
        if max_missing is not None and (a.missing > max_missing or not a.required):
            continue  # nothing to check is not "cookable" (e.g. every line marked optional)
        if any(i.name.strip().lower() in UNPARSED for i in r.ingredients):
            continue  # an import that failed to read the ingredient list
        if min_ingredients is not None and a.required < min_ingredients:
            continue
        if courses and course_of(r) not in courses:
            continue
        if exclude_courses and course_of(r) in exclude_courses:
            continue
        out.append((r, a))
    out.sort(
        key=lambda x: (
            not x[1].required,
            x[1].missing,
            -round(x[1].have / (x[1].required + 2), 6),
            -len(x[1].uses_expiring),
            -x[1].have,
            minutes(x[0]) or 0,
            x[0].title.lower(),
            str(x[0].id),
        )
    )
    return out


def brief(r: Recipe, a: Availability) -> RecipeBrief:
    names = {"missing": [], "low": [], "staple": []}  # type: dict[str, list[str]]
    for it in a.items:
        if it.status in names:
            names[it.status].append(it.ingredient.name)
    return RecipeBrief(
        id=r.id,
        title=r.title,
        course=course_of(r),  # type: ignore[arg-type]
        tags=list(r.tags or []),
        categories=list(r.categories or []),
        servings=a.servings,
        prep_min=r.prep_min,
        cook_min=r.cook_min,
        minutes=minutes(r),
        source_url=r.source_url,
        coverage=a.coverage,
        have=a.have,
        required=a.required,
        missing=a.missing,
        missing_names=names["missing"],
        low_names=names["low"],
        staple_names=names["staple"],
        uses_expiring=a.uses_expiring,
    )


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
        if it.status == "staple":
            skipped.append(ing.name)
            continue
        if it.product:
            # whole packages: 0.2 l of a 1 l carton still means buying one carton
            qty = max(Decimal(1), (it.need or Decimal(1)).to_integral_value(ROUND_UP))
            _, how = await add_need(
                session,
                household_id,
                name=it.product.name,
                product_id=it.product.id,
                amount=(qty, it.product.stock_unit),
                note=r.title[:500],
            )
        else:
            # the recipe's own amount (for the requested servings), merged with what is listed
            qty = (
                ing.quantity * Decimal(a.servings) / Decimal(r.servings or 1)
                if ing.quantity is not None
                else None
            )
            _, how = await add_need(
                session,
                household_id,
                name=ing.name,
                amount=shopping_amount(qty, ing.unit),
                note=r.title[:500],
            )
        if how == "already":
            skipped.append(it.product.name if it.product else ing.name)
        else:
            added.append(it.product.name if it.product else ing.name)
    return added, skipped
