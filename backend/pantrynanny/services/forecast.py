"""Run-out forecasts from the household's own consumption history.

Deliberately simple and explainable: average daily use over the observed period, with a
confidence that depends on how much history there is. No forecast is better than a wild one,
so products with too little history get none.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Product, StockTransaction
from .inventory import batches_for, build_view

T = StockTransaction
WINDOW_DAYS = 90
MIN_EVENTS = 3
MIN_SPAN_DAYS = 7


@dataclass
class Forecast:
    product: Product
    total: Decimal
    per_day: float
    days_left: float
    events: int
    span_days: float
    confidence: str  # "medium" | "high"


def confidence(events: int, span_days: float) -> str | None:
    if events >= 6 and span_days >= 21:
        return "high"
    if events >= MIN_EVENTS:
        return "medium"
    return None


def estimate(
    consumed: Decimal, events: int, first: datetime, now: datetime, total: Decimal
) -> tuple[float, float, float, str] | None:
    """(per_day, days_left, span_days, confidence) or None when there is not enough history."""
    span = max((now - first).total_seconds() / 86400, MIN_SPAN_DAYS)
    conf = confidence(events, span)
    if conf is None or consumed <= 0 or total <= 0:
        return None
    per_day = float(consumed) / span
    return per_day, float(total) / per_day, span, conf


async def forecasts(
    session: AsyncSession,
    household_id: uuid.UUID,
    *,
    horizon_days: float | None = 14,
    product_id: uuid.UUID | None = None,
    now: datetime | None = None,
) -> list[Forecast]:
    now = now or datetime.now(UTC)
    stmt = (
        select(
            T.product_id,
            func.sum(func.abs(T.quantity_delta)),
            func.count(),
            func.min(T.occurred_at),
        )
        .where(
            T.household_id == household_id,
            T.type == "remove",
            T.undone.is_(False),
            T.occurred_at >= now - timedelta(days=WINDOW_DAYS),
        )
        .group_by(T.product_id)
    )
    if product_id:
        stmt = stmt.where(T.product_id == product_id)
    rows = (await session.execute(stmt)).all()
    if not rows:
        return []
    ids = [r[0] for r in rows]
    products = {
        p.id: p
        for p in (
            await session.execute(
                select(Product).where(Product.id.in_(ids), Product.deleted_at.is_(None))
            )
        ).scalars()
    }
    batches = await batches_for(session, household_id, list(products))
    out = []
    for pid, consumed, events, first in rows:
        p = products.get(pid)
        if p is None:
            continue
        total = build_view(p, batches[pid]).total
        est = estimate(Decimal(consumed), events, first, now, total)
        if est is None:
            continue
        per_day, days_left, span, conf = est
        if horizon_days is not None and days_left > horizon_days:
            continue
        out.append(Forecast(p, total, per_day, days_left, events, span, conf))
    out.sort(key=lambda f: f.days_left)
    return out
