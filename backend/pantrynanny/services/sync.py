"""Pull side of synchronisation: snapshot and incremental changes via ``change_seq``."""

import uuid
from dataclasses import dataclass, field

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Category, Location, Product, StockBatch
from .inventory import StockView, batches_for, build_view

# Cursor design. change_seq values are drawn when a row is written but become visible only at
# commit, so "everything above the highest seq I saw" can skip a slow writer. Instead each row is
# stamped (trigger) with the id of the writing transaction, and the cursor is the oldest
# transaction id that was still in progress when the previous pull took its snapshot
# (pg_snapshot_xmin). Every transaction below that id had finished, so all of its rows were
# visible to that pull; the next pull returns all rows with change_xid >= cursor. Rows may be
# delivered more than once (clients upsert) but never skipped.


@dataclass(slots=True)
class Changes:
    cursor: str
    products: list[Product] = field(default_factory=list)
    inventory: list[StockView] = field(default_factory=list)
    locations: list[Location] = field(default_factory=list)
    categories: list[Category] = field(default_factory=list)
    full_resync_required: bool = False


CURSOR_PREFIX = "x1"


def format_cursor(db_oid: int, xmin: int) -> str:
    return f"{CURSOR_PREFIX}.{db_oid}.{xmin}"


def parse_cursor(value: str, db_oid: int) -> int | None:
    """xmin from a v1 cursor issued by *this* database, else None (=> full resync).

    The database OID changes on DROP/CREATE DATABASE (restore.sh), and legacy numeric cursors
    (pre-xid change_seq values) have no prefix, so both force clients to start over.
    """
    parts = value.split(".")
    if len(parts) != 3 or parts[0] != CURSOR_PREFIX:
        return None
    if not (
        parts[1].isascii() and parts[1].isdigit() and parts[2].isascii() and parts[2].isdigit()
    ):
        return None
    if int(parts[1]) != db_oid:
        return None
    return int(parts[2])


async def current_cursor(session: AsyncSession) -> tuple[int, int, int]:
    """(db_oid, xmin, xmax) of a fresh snapshot: xmin is the cursor, xmax the next unused xid."""
    row = (
        await session.execute(
            text(
                "SELECT (SELECT oid::text::bigint FROM pg_database "
                "WHERE datname = current_database()) AS db, "
                "pg_snapshot_xmin(pg_current_snapshot())::text::bigint AS lo, "
                "pg_snapshot_xmax(pg_current_snapshot())::text::bigint AS hi"
            )
        )
    ).one()
    return int(row.db), int(row.lo), int(row.hi)


async def snapshot(session: AsyncSession, household_id: uuid.UUID) -> Changes:
    db_oid, xmin, _ = await current_cursor(session)
    cursor = format_cursor(db_oid, xmin)
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
    return Changes(cursor, products, inventory, locations, categories)


async def changes_since(session: AsyncSession, household_id: uuid.UUID, since: str) -> Changes:
    db_oid, xmin, xmax = await current_cursor(session)
    cursor = format_cursor(db_oid, xmin)
    since_n = parse_cursor(since, db_oid)
    if since_n is None or since_n > xmax:
        # Foreign/legacy cursor, restored or recreated database, or one from the future.
        return Changes(cursor, full_resync_required=True)
    floor = since_n

    products = list(
        (
            await session.execute(
                select(Product)
                .where(Product.household_id == household_id, Product.change_xid >= floor)
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
                    StockBatch.household_id == household_id, StockBatch.change_xid >= floor
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
                    Location.household_id == household_id, Location.change_xid >= floor
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
                    Category.household_id == household_id, Category.change_xid >= floor
                )
            )
        )
        .scalars()
        .all()
    )
    return Changes(cursor, products, inventory, locations, categories)
