"""Kitchen screen: the products a household touches most, so taking one out is a single tap."""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Product, StockTransaction
from .inventory import StockView, batches_for, build_view

T = StockTransaction


async def kitchen_tiles(
    session: AsyncSession, household_id: uuid.UUID, *, limit: int = 12, days: int = 60
) -> list[tuple[StockView, int]]:
    """Favourites first, then the most frequently scanned/used products of the last ``days``.

    Returns (view, uses) pairs. Products that are out of stock stay on the list: a favourite
    with 0 left is exactly what the kitchen needs to see.
    """
    since = datetime.now(UTC) - timedelta(days=days)
    uses = dict(
        (
            await session.execute(
                select(T.product_id, func.count())
                .where(
                    T.household_id == household_id,
                    T.type.in_(("add", "remove")),
                    T.undone.is_(False),
                    T.occurred_at >= since,
                )
                .group_by(T.product_id)
            )
        ).all()
    )
    favs = (
        (
            await session.execute(
                select(Product.id).where(
                    Product.household_id == household_id,
                    Product.favorite.is_(True),
                    Product.deleted_at.is_(None),
                )
            )
        )
        .scalars()
        .all()
    )
    frequent = sorted(uses, key=lambda pid: -uses[pid])
    ids = list(dict.fromkeys([*favs, *frequent]))
    if not ids:
        return []
    products = {
        p.id: p
        for p in (
            await session.execute(
                select(Product).where(
                    Product.id.in_(ids),
                    Product.household_id == household_id,
                    Product.deleted_at.is_(None),
                    Product.status != "unknown",
                )
            )
        ).scalars()
    }
    ordered = [products[i] for i in ids if i in products]
    ordered.sort(key=lambda p: (not p.favorite, -uses.get(p.id, 0), p.name.lower()))
    ordered = ordered[: max(limit, len(favs))]
    batches = await batches_for(session, household_id, [p.id for p in ordered])
    return [(build_view(p, batches[p.id]), uses.get(p.id, 0)) for p in ordered]
