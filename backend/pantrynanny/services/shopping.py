"""Shared shopping list."""

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select, update
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
