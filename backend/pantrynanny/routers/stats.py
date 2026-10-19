import uuid
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..security import Principal, get_principal
from ..services.forecast import forecasts
from ..services.stats import build_stats

router = APIRouter(tags=["stats"])


@router.get("/stats")
async def stats(
    request: Request,
    days: int = Query(default=30, ge=1, le=366),
    product_id: uuid.UUID | None = None,
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
):
    """``{top_added, top_consumed, daily:[{date, added, removed}], series?}``.

    ``series`` (end-of-day quantity per day) is only present with ``product_id``.
    """
    tz = ZoneInfo(request.app.state.settings.timezone)
    return await build_stats(session, principal.household_id, tz, days=days, product_id=product_id)


class RunOut(BaseModel):
    product_id: uuid.UUID
    name: str
    image_url: str | None
    total_quantity: float
    stock_unit: str
    per_day: float
    days_left: float
    events: int
    confidence: str


@router.get("/stats/runout", response_model=list[RunOut])
async def runout(
    days: float = Query(default=14, gt=0, le=365),
    product_id: uuid.UUID | None = None,
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
):
    """Products expected to run out within ``days`` at the household's usual pace.

    With ``product_id`` the horizon is ignored (a forecast for that product, if there is
    enough history)."""
    rows = await forecasts(
        session,
        principal.household_id,
        horizon_days=None if product_id else days,
        product_id=product_id,
    )
    return [
        RunOut(
            product_id=f.product.id,
            name=f.product.name,
            image_url=f"/api/media/{f.product.image_path}" if f.product.image_path else None,
            total_quantity=float(f.total),
            stock_unit=f.product.stock_unit,
            per_day=round(f.per_day, 3),
            days_left=round(f.days_left, 1),
            events=f.events,
            confidence=f.confidence,
        )
        for f in rows
    ]
