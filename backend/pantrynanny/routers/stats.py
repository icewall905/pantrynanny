import uuid
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..security import Principal, get_principal
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
