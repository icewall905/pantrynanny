"""Dashboard aggregates."""

import uuid
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import HouseholdSettings, Location, Product, ShoppingItem, StockBatch
from .inventory import StockView, list_inventory, recent_transactions

ZERO = Decimal(0)


def _restricted(view: StockView, keep) -> StockView | None:
    batches = [b for b in view.batches if keep(b)]
    if not batches:
        return None
    expiries = [b.expires_at for b in batches if b.expires_at]
    return StockView(
        product=view.product,
        total=sum((b.quantity for b in batches), ZERO),
        batches=batches,
        next_expiry=min(expiries) if expiries else None,
        low_stock=view.low_stock,
    )


async def build_dashboard(
    session: AsyncSession,
    household_id: uuid.UUID,
    settings: HouseholdSettings,
    today: date,
) -> dict:
    all_views = await list_inventory(session, household_id, include_empty=True)
    in_stock = [v for v in all_views if any(b.quantity > 0 for b in v.batches)]
    soon_limit = today + timedelta(days=settings.expiry_soon_days)

    def is_soon(b: StockBatch) -> bool:
        return b.quantity > 0 and b.expires_at is not None and today <= b.expires_at <= soon_limit

    def is_expired(b: StockBatch) -> bool:
        return b.quantity > 0 and b.expires_at is not None and b.expires_at < today

    expiring = [r for v in in_stock if (r := _restricted(v, is_soon))]
    expired = [r for v in in_stock if (r := _restricted(v, is_expired))]
    expiring.sort(key=lambda v: (v.next_expiry, v.product.name.lower()))
    expired.sort(key=lambda v: (v.next_expiry, v.product.name.lower()))

    added = await recent_transactions(session, household_id, limit=10, types=("add",))
    consumed = await recent_transactions(session, household_id, limit=10, types=("remove",))
    added = [t for t in added if not t.undone]
    consumed = [t for t in consumed if not t.undone]
    product_ids = {t.product_id for t in [*added, *consumed]}
    products: dict[uuid.UUID, Product] = {}
    if product_ids:
        rows = await session.execute(select(Product).where(Product.id.in_(product_ids)))
        products = {p.id: p for p in rows.scalars()}

    unknown_count = await session.scalar(
        select(func.count())
        .select_from(Product)
        .where(
            Product.household_id == household_id,
            Product.deleted_at.is_(None),
            Product.status.in_(("unknown", "needs_review")),
        )
    )
    shopping_open = await session.scalar(
        select(func.count())
        .select_from(ShoppingItem)
        .where(
            ShoppingItem.household_id == household_id,
            ShoppingItem.checked.is_(False),
            ShoppingItem.deleted_at.is_(None),
        )
    )
    locations = (
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
    by_location = []
    for loc in locations:
        pids = {b.product_id for v in in_stock for b in v.batches if b.location_id == loc.id}
        by_location.append({"location": loc, "item_count": len(pids)})

    return {
        "totals": {
            "products_in_stock": len(in_stock),
            "items": float(sum((v.total for v in in_stock), ZERO)),
        },
        "low_stock": [v for v in all_views if v.low_stock],
        "expiring_soon": expiring,
        "expired": expired,
        "recently_added": [(t, products[t.product_id]) for t in added if t.product_id in products],
        "recently_consumed": [
            (t, products[t.product_id]) for t in consumed if t.product_id in products
        ],
        "unknown_count": unknown_count or 0,
        "shopping_open_count": shopping_open or 0,
        "by_location": by_location,
    }
