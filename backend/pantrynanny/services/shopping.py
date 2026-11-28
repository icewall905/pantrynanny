"""Shared shopping list."""

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..errors import AppError, conflict, not_found
from ..models import Product, ShoppingItem
from ..schemas.common import MAX_OP_QTY
from ..schemas.shopping import ShoppingCreate, ShoppingPatch
from .inventory import StockView, list_inventory
from .products import _assert_refs, get_product

MAX_ITEM_QTY = Decimal(MAX_OP_QTY)


def _open_item_stmt(household_id: uuid.UUID, product_id: uuid.UUID):
    return select(ShoppingItem).where(
        ShoppingItem.household_id == household_id,
        ShoppingItem.product_id == product_id,
        ShoppingItem.checked.is_(False),
        ShoppingItem.deleted_at.is_(None),
    )


async def list_items(session: AsyncSession, household_id: uuid.UUID) -> list[ShoppingItem]:
    stmt = (
        select(ShoppingItem)
        .where(ShoppingItem.household_id == household_id, ShoppingItem.deleted_at.is_(None))
        .order_by(
            ShoppingItem.checked,
            ShoppingItem.created_at,
            ShoppingItem.id,
        )
    )
    return list((await session.execute(stmt)).scalars().all())


async def get_item(
    session: AsyncSession, household_id: uuid.UUID, item_id: uuid.UUID, *, lock: bool = False
) -> ShoppingItem:
    stmt = select(ShoppingItem).where(
        ShoppingItem.id == item_id,
        ShoppingItem.household_id == household_id,
        ShoppingItem.deleted_at.is_(None),
    )
    if lock:
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    item = (await session.execute(stmt)).scalar_one_or_none()
    if item is None:
        raise not_found("Shopping item not found")
    return item


async def add_item(
    session: AsyncSession, household_id: uuid.UUID, body: ShoppingCreate
) -> tuple[ShoppingItem, bool]:
    """Create an item, or merge quantity into the existing open item for the same product."""
    product: Product | None = None
    await _assert_refs(session, household_id, body.category_id, None)
    if body.product_id:
        product = await get_product(session, household_id, body.product_id)
    elif not body.name:
        raise AppError(422, "validation_error", "name or product_id is required")

    async def merge() -> ShoppingItem | None:
        assert product is not None
        existing = (
            await session.execute(
                _open_item_stmt(household_id, product.id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()
        if existing is None:
            return None
        existing.quantity = min(existing.quantity + body.quantity, MAX_ITEM_QTY)
        existing.version += 1
        existing.updated_at = datetime.now(UTC)
        if body.note:
            existing.note = body.note
        await session.flush()
        return existing

    if product is not None:
        merged = await merge()
        if merged:
            return merged, False
    item = ShoppingItem(
        household_id=household_id,
        product_id=product.id if product else None,
        name=(body.name or (product.name if product else "")).strip(),
        quantity=body.quantity,
        unit=body.unit or (product.stock_unit if product else None),
        category_id=body.category_id or (product.category_id if product else None),
        note=body.note,
        store=(body.store or "").strip() or None,
        source="manual",
    )
    try:
        async with session.begin_nested():
            session.add(item)
            await session.flush()
    except IntegrityError:
        merged = await merge()
        if merged is None:
            raise
        return merged, False
    return item, True


async def patch_item(
    session: AsyncSession,
    household_id: uuid.UUID,
    item_id: uuid.UUID,
    body: ShoppingPatch,
    if_match: int | None,
) -> ShoppingItem:
    item = await get_item(session, household_id, item_id, lock=True)
    sent = body.model_fields_set
    only_check = sent <= {"checked"}
    if if_match is None and not only_check:
        raise AppError(428, "if_match_required", "If-Match header is required")
    if if_match is not None and if_match != item.version:
        from ..schemas.shopping import ShoppingItemOut

        raise conflict(
            "version_conflict",
            "Item was modified by someone else",
            item=ShoppingItemOut.model_validate(item).model_dump(mode="json"),
        )
    if "name" in sent and body.name is None:
        raise AppError(422, "validation_error", "name cannot be null")
    if "category_id" in sent:
        await _assert_refs(session, household_id, body.category_id, None)
    product_id, my_quantity = item.product_id, item.quantity
    try:
        # Mutate inside the savepoint: begin_nested() flushes pending state first, so a
        # constraint violation caused by these changes must be raised within the block.
        async with session.begin_nested():
            for field in ("name", "quantity", "unit", "category_id", "note", "store"):
                if field in sent:
                    setattr(item, field, getattr(body, field))
            if "store" in sent:
                item.store = (body.store or "").strip() or None
            if "checked" in sent and body.checked is not None and body.checked != item.checked:
                item.checked = body.checked
                item.checked_at = datetime.now(UTC) if body.checked else None
            item.version += 1
            item.updated_at = datetime.now(UTC)
            await session.flush()
    except IntegrityError:
        # Un-checking collided with another open item for the same product: fold into it.
        if product_id is None:
            raise
        other = (
            await session.execute(
                _open_item_stmt(household_id, product_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).scalar_one()
        other.quantity = min(other.quantity + (my_quantity or Decimal(0)), MAX_ITEM_QTY)
        other.version += 1
        other.updated_at = datetime.now(UTC)
        mine = await get_item(session, household_id, item_id, lock=True)
        mine.deleted_at = datetime.now(UTC)
        await session.flush()
        return other
    return item


async def delete_item(session: AsyncSession, household_id: uuid.UUID, item_id: uuid.UUID) -> None:
    item = await get_item(session, household_id, item_id, lock=True)
    item.deleted_at = datetime.now(UTC)
    item.updated_at = item.deleted_at
    item.version += 1


async def clear_checked(session: AsyncSession, household_id: uuid.UUID) -> int:
    res = await session.execute(
        update(ShoppingItem)
        .where(
            ShoppingItem.household_id == household_id,
            ShoppingItem.checked.is_(True),
            ShoppingItem.deleted_at.is_(None),
        )
        .values(deleted_at=datetime.now(UTC), updated_at=datetime.now(UTC))
    )
    return res.rowcount or 0


async def clear_all(session: AsyncSession, household_id: uuid.UUID) -> int:
    """Reset the list: every item, checked or not (soft delete, so other devices sync it)."""
    now = datetime.now(UTC)
    res = await session.execute(
        update(ShoppingItem)
        .where(ShoppingItem.household_id == household_id, ShoppingItem.deleted_at.is_(None))
        .values(deleted_at=now, updated_at=now)
    )
    return res.rowcount or 0


async def suggestions(session: AsyncSession, household_id: uuid.UUID) -> list[StockView]:
    open_ids = set(
        (
            await session.execute(
                select(ShoppingItem.product_id).where(
                    ShoppingItem.household_id == household_id,
                    ShoppingItem.checked.is_(False),
                    ShoppingItem.deleted_at.is_(None),
                    ShoppingItem.product_id.is_not(None),
                )
            )
        )
        .scalars()
        .all()
    )
    views = await list_inventory(session, household_id, include_empty=True)
    return [v for v in views if v.low_stock and v.product.id not in open_ids]


async def has_open_named(session: AsyncSession, household_id: uuid.UUID, name: str) -> bool:
    """An unchecked free-text item with this name is already on the list (case-insensitive)."""
    row = (
        await session.execute(
            select(ShoppingItem.id)
            .where(
                ShoppingItem.household_id == household_id,
                ShoppingItem.checked.is_(False),
                ShoppingItem.deleted_at.is_(None),
                func.lower(ShoppingItem.name) == name.strip().lower(),
            )
            .limit(1)
        )
    ).first()
    return row is not None


# ---- recipe / meal-plan needs ------------------------------------------------------------------

# shopping units by family, with the factor to the family's base unit (g / ml / count)
_SHOP_UNITS: dict[str, tuple[str, Decimal]] = {
    "g": ("mass", Decimal(1)),
    "kg": ("mass", Decimal(1000)),
    "ml": ("volume", Decimal(1)),
    "cl": ("volume", Decimal(10)),
    "dl": ("volume", Decimal(100)),
    "l": ("volume", Decimal(1000)),
    "pcs": ("count", Decimal(1)),
    "pkg": ("pkg", Decimal(1)),
}
# recipe units that are counted things on a shopping list ("2 fed hvidløg" -> 2)
_COUNTED = {"pcs", "clove", "can", "slice", "bunch", "sprig", "handful"}


def shopping_amount(
    quantity: Decimal | None, unit: str | None
) -> tuple[Decimal, str | None] | None:
    """A recipe amount as (quantity, shopping unit): 3 spsk -> 45 ml, 1200 g -> 1.2 kg,
    2 fed -> 2 pcs. None when there is no sensible amount (no number, "a pinch")."""
    from ..recipes.parse import to_base

    if quantity is None or quantity <= 0:
        return None
    if unit is None or unit in _COUNTED:
        return quantity.quantize(Decimal(1), rounding="ROUND_UP"), "pcs"
    if unit == "pkg":
        return quantity.quantize(Decimal(1), rounding="ROUND_UP"), "pkg"
    base = to_base(quantity, unit)
    if base is None:
        return None
    fam, amount = base
    if fam == "mass":
        return (_tidy(amount / 1000), "kg") if amount >= 1000 else (_tidy(amount), "g")
    if fam == "volume":
        if amount >= 1000:
            return _tidy(amount / 1000), "l"
        if amount >= 100:
            return _tidy(amount / 100), "dl"
        return _tidy(amount), "ml"
    return None


def _tidy(d: Decimal) -> Decimal:
    q = d.quantize(Decimal("0.1"), rounding="ROUND_UP")
    return q.quantize(Decimal(1)) if q == q.to_integral_value() else q


def _convert(quantity: Decimal, unit: str | None, to: str | None) -> Decimal | None:
    """`quantity unit` in `to` units, or None when they do not mix (g vs ml)."""
    a, b = _SHOP_UNITS.get(unit or "pcs"), _SHOP_UNITS.get(to or "pcs")
    if a is None or b is None or a[0] != b[0]:
        return None
    return quantity * a[1] / b[1]


def _add_note(old: str | None, new: str | None) -> str | None:
    if not new:
        return old
    parts = [p.strip() for p in (old or "").split(",") if p.strip()]
    if new.strip().lower() not in {p.lower() for p in parts}:
        parts.append(new.strip())
    return ", ".join(parts)[:500] or None


def _fmt(q: Decimal, unit: str | None) -> str:
    s = format(q.normalize(), "f")
    return f"{s} {unit}" if unit and unit != "pcs" else s


async def add_need(
    session: AsyncSession,
    household_id: uuid.UUID,
    *,
    name: str,
    product_id: uuid.UUID | None = None,
    amount: tuple[Decimal, str | None] | None = None,
    note: str | None = None,
) -> tuple[ShoppingItem, str]:
    """Put something a recipe needs on the list, consolidating with what is already there.

    An open item for the same product, else with the same name (case-insensitive), gets the
    amount added (converted when the units mix, e.g. 2 dl onto 300 ml = 500 ml). When they do not
    mix (200 g onto "1 pcs"), the existing quantity stays and the extra amount is noted. The
    recipe title is added to the note; when every recipe in `note` is already noted on the item,
    nothing changes (asking twice does not double it). Returns (item, "created" | "merged" |
    "already")."""
    name = name.strip()[:200]
    conds = [func.lower(ShoppingItem.name) == name.lower()]
    product = await get_product(session, household_id, product_id) if product_id else None
    if product is not None:
        conds = [
            ShoppingItem.product_id == product.id,
            func.lower(ShoppingItem.name) == product.name.strip().lower(),
        ]
    existing = None
    for cond in conds:  # the product's own item first, then a same-named one
        existing = (
            await session.execute(
                select(ShoppingItem)
                .where(
                    ShoppingItem.household_id == household_id,
                    ShoppingItem.checked.is_(False),
                    ShoppingItem.deleted_at.is_(None),
                    cond,
                    *(
                        [
                            (ShoppingItem.product_id.is_(None))
                            | (ShoppingItem.product_id == product.id)
                        ]
                        if product is not None
                        else []
                    ),
                )
                .order_by(ShoppingItem.created_at, ShoppingItem.id)
                .limit(1)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()
        if existing is not None:
            break
    if existing is None:
        qty, unit = amount or (Decimal(1), None)
        body = ShoppingCreate(
            product_id=product.id if product else None,
            name=None if product else name,
            quantity=min(qty, MAX_ITEM_QTY),
            unit=unit,  # type: ignore[arg-type]
            note=(note or None) and note[:500],
        )
        item, created = await add_item(session, household_id, body)
        return item, "created" if created else "merged"
    noted = {p.strip().lower() for p in (existing.note or "").split(",")}
    titles = [p.strip().lower() for p in (note or "").split(",") if p.strip()]
    if titles and all(t in noted for t in titles):
        return existing, "already"
    if amount is not None:
        qty, unit = amount
        extra = _convert(qty, unit, existing.unit)
        if extra is not None:
            existing.quantity = min(
                existing.quantity + extra.quantize(Decimal("0.001")), MAX_ITEM_QTY
            )
        else:
            existing.note = _add_note(existing.note, f"+{_fmt(qty, unit)}")
    if product is not None and existing.product_id is None:
        existing.product_id = product.id  # a typed "sukker" becomes the sugar product's item
    existing.note = _add_note(existing.note, note)
    existing.version += 1
    existing.updated_at = datetime.now(UTC)
    await session.flush()
    return existing, "merged"


def sum_amounts(
    amounts: list[tuple[Decimal, str | None] | None],
) -> list[tuple[Decimal, str | None] | None]:
    """Add up amounts that mix (100 g + 1 kg = 1.1 kg); a missing amount counts once as `None`."""
    out: list[tuple[Decimal, str | None] | None] = []
    for amt in amounts:
        if amt is None:
            if not out:
                out.append(None)
            continue
        for i, cur in enumerate(out):
            if cur is None:
                out[i] = amt
                break
            extra = _convert(amt[0], amt[1], cur[1])
            if extra is not None:
                out[i] = (cur[0] + extra, cur[1])
                break
        else:
            out.append(amt)
    return out or [None]
