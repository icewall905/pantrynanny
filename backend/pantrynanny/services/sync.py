"""Pull side of synchronisation: snapshot and incremental changes via ``change_seq``."""

import uuid
from dataclasses import dataclass, field

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Category, Location, Product, StockBatch
from .inventory import StockView, batches_for, build_view

# change_seq values are drawn when a row is written, but rows become visible at commit. A
# transaction that drew a lower number may commit after a reader already advanced past it, so
# `changes` re-reads a small window below the client's cursor. Clients upsert, so replays are
# harmless.
SAFETY_WINDOW = 200


@dataclass(slots=True)
class Changes:
    cursor: str
    products: list[Product] = field(default_factory=list)
    inventory: list[StockView] = field(default_factory=list)
    locations: list[Location] = field(default_factory=list)
    categories: list[Category] = field(default_factory=list)
    full_resync_required: bool = False


async def current_cursor(session: AsyncSession) -> int:
    row = (await session.execute(text("SELECT last_value, is_called FROM change_seq_seq"))).one()
    return int(row.last_value) if row.is_called else 0


async def snapshot(session: AsyncSession, household_id: uuid.UUID) -> Changes:
    cursor = await current_cursor(session)
    products = list(
        (
            await session.execute(
                select(Product)
                .where(Product.household_id == household_id, Product.deleted_at.is_(None))
                .order_by(Product.name)
            )
        )
        .scalars()
        .all()
    )
    batches = await batches_for(session, household_id, [p.id for p in products])
    inventory = [build_view(p, batches[p.id]) for p in products if batches[p.id]]
    locations = list(
        (
            await session.execute(
                select(Location)
                .where(Location.household_id == household_id, Location.deleted_at.is_(None))
                .order_by(Location.sort_order, Location.name)
            )
        )
        .scalars()
        .all()
    )
    categories = list(
        (
            await session.execute(
                select(Category)
                .where(Category.household_id == household_id, Category.deleted_at.is_(None))
                .order_by(Category.sort_order, Category.name)
            )
        )
        .scalars()
        .all()
    )
    return Changes(str(cursor), products, inventory, locations, categories)


async def changes_since(session: AsyncSession, household_id: uuid.UUID, since: str) -> Changes:
    cursor = await current_cursor(session)
    try:
        since_n = int(since)
    except ValueError:
        return Changes(str(cursor), full_resync_required=True)
    if since_n < 0 or since_n > cursor:
        # Cursor from the future: the database was restored/reset. Client must start over.
        return Changes(str(cursor), full_resync_required=True)
    floor = max(0, since_n - SAFETY_WINDOW)

    products = list(
        (
            await session.execute(
                select(Product)
                .where(Product.household_id == household_id, Product.change_seq > floor)
                .order_by(Product.change_seq)
            )
        )
        .scalars()
        .all()
    )
    changed_pids = set(
        (
            await session.execute(
                select(StockBatch.product_id).where(
                    StockBatch.household_id == household_id, StockBatch.change_seq > floor
                )
            )
        )
        .scalars()
        .all()
    )
    inventory_products = {p.id: p for p in products}
    missing = changed_pids - inventory_products.keys()
    if missing:
        extra = (await session.execute(select(Product).where(Product.id.in_(missing)))).scalars()
        inventory_products.update({p.id: p for p in extra})
    batches = await batches_for(session, household_id, list(changed_pids))
    inventory = [build_view(inventory_products[pid], batches[pid]) for pid in changed_pids]
    locations = list(
        (
            await session.execute(
                select(Location).where(
                    Location.household_id == household_id, Location.change_seq > floor
                )
            )
        )
        .scalars()
        .all()
    )
    categories = list(
        (
            await session.execute(
                select(Category).where(
                    Category.household_id == household_id, Category.change_seq > floor
                )
            )
        )
        .scalars()
        .all()
    )
    return Changes(str(cursor), products, inventory, locations, categories)
