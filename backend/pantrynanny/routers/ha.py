"""Read-only summary for Home Assistant (``rest`` sensor)."""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..errors import forbidden
from ..models import Household
from ..security import Principal, get_principal
from ..services.dashboard import build_dashboard
from ..services.households import get_household_settings

router = APIRouter(tags=["home-assistant"])
MAX_NAMES = 25


@router.get("/ha/summary")
async def ha_summary(
    request: Request,
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
):
    """Counts and short lists; authenticate with ``Authorization: Bearer <device token>``."""
    if principal.via != "bearer":
        raise forbidden("Use a bearer token", "bearer_required")
    tz = ZoneInfo(request.app.state.settings.timezone)
    today = datetime.now(tz).date()
    settings = await get_household_settings(session, principal.household_id)
    d = await build_dashboard(session, principal.household_id, settings, today)
    hh = await session.scalar(select(Household.name).where(Household.id == principal.household_id))

    def expiring(v):
        return {
            "name": v.product.name,
            "expires_at": v.next_expiry.isoformat() if v.next_expiry else None,
            "days_left": (v.next_expiry - today).days if v.next_expiry else None,
            "quantity": float(v.total),
        }

    return {
        "household": hh,
        "generated_at": datetime.now(UTC).isoformat(),
        "products_in_stock": d["totals"]["products_in_stock"],
        "items_total": d["totals"]["items"],
        "low_stock_count": len(d["low_stock"]),
        "low_stock": [v.product.name for v in d["low_stock"]][:MAX_NAMES],
        "expiring_soon_count": len(d["expiring_soon"]),
        "expiring_soon": [expiring(v) for v in d["expiring_soon"]][:MAX_NAMES],
        "expired_count": len(d["expired"]),
        "expired": [expiring(v) for v in d["expired"]][:MAX_NAMES],
        "shopping_open_count": d["shopping_open_count"],
        "unknown_count": d["unknown_count"],
    }
