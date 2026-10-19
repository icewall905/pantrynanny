"""Consumption/usage statistics derived from the append-only transaction log."""

import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import Date, cast, func, literal, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Product, StockTransaction

T = StockTransaction


def _since(days: int, tz: ZoneInfo) -> tuple[date, datetime]:
    today = datetime.now(tz).date()
    start = today - timedelta(days=days - 1)
    return start, datetime.combine(start, datetime.min.time(), tzinfo=tz)


async def _top(
    session: AsyncSession, household_id: uuid.UUID, ttype: str, since: datetime, limit: int
) -> list[dict]:
    rows = (
        await session.execute(
            select(
                T.product_id,
                Product.name,
                func.sum(func.abs(T.quantity_delta)).label("q"),
                func.count().label("n"),
            )
            .join(Product, Product.id == T.product_id)
            .where(
                T.household_id == household_id,
                T.type == ttype,
                T.undone.is_(False),
                T.occurred_at >= since,
            )
            .group_by(T.product_id, Product.name)
            .order_by(func.sum(func.abs(T.quantity_delta)).desc(), Product.name)
            .limit(limit)
        )
    ).all()
    return [
        {"product_id": r.product_id, "name": r.name, "quantity": float(r.q), "count": r.n}
        for r in rows
    ]


async def build_stats(
    session: AsyncSession,
    household_id: uuid.UUID,
    tz: ZoneInfo,
    *,
    days: int,
    product_id: uuid.UUID | None = None,
    limit: int = 10,
) -> dict:
    start, since = _since(days, tz)
    day = cast(func.timezone(str(tz), T.occurred_at), Date)
    rows = (
        await session.execute(
            select(
                day.label("d"),
                func.coalesce(
                    func.sum(func.abs(T.quantity_delta)).filter(T.type == "add"), literal(0)
                ).label("added"),
                func.coalesce(
                    func.sum(func.abs(T.quantity_delta)).filter(T.type == "remove"), literal(0)
                ).label("removed"),
            )
            .where(
                T.household_id == household_id,
                T.type.in_(("add", "remove")),
                T.undone.is_(False),
                T.occurred_at >= since,
            )
            .group_by(day)
        )
    ).all()
    by_day = {r.d: (float(r.added), float(r.removed)) for r in rows}
    daily = []
    for i in range(days):
        d = start + timedelta(days=i)
        a, r = by_day.get(d, (0.0, 0.0))
        daily.append({"date": d.isoformat(), "added": a, "removed": r})
    out = {
        "days": days,
        "top_added": await _top(session, household_id, "add", since, limit),
        "top_consumed": await _top(session, household_id, "remove", since, limit),
        "daily": daily,
    }
    if product_id is not None:
        base = (
            await session.scalar(
                select(func.coalesce(func.sum(T.quantity_delta), 0)).where(
                    T.household_id == household_id,
                    T.product_id == product_id,
                    T.type.in_(("add", "remove", "adjust", "undo")),
                    T.occurred_at < since,
                )
            )
        ) or Decimal(0)
        deltas = (
            await session.execute(
                select(day.label("d"), func.sum(T.quantity_delta).label("s"))
                .where(
                    T.household_id == household_id,
                    T.product_id == product_id,
                    T.type.in_(("add", "remove", "adjust", "undo")),
                    T.occurred_at >= since,
                )
                .group_by(day)
            )
        ).all()
        dmap = {r.d: r.s for r in deltas}
        running = Decimal(base)
        series = []
        for i in range(days):
            d = start + timedelta(days=i)
            running += dmap.get(d, Decimal(0))
            series.append({"date": d.isoformat(), "quantity": float(running)})
        out["product_id"] = product_id
        out["series"] = series
    return out


__all__ = ["build_stats"]
