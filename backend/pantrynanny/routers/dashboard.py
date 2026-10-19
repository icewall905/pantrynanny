from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..schemas.inventory import DashboardOut, LocationCount, TxnWithProduct
from ..security import Principal, get_principal
from ..services.dashboard import build_dashboard
from ..services.households import get_household_settings
from ..services.products import product_out
from ._common import item_out, txn_out

router = APIRouter(tags=["dashboard"])


@router.get("/dashboard", response_model=DashboardOut)
async def dashboard(
    request: Request,
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
):
    settings = await get_household_settings(session, principal.household_id)
    today = datetime.now(ZoneInfo(request.app.state.settings.timezone)).date()
    d = await build_dashboard(session, principal.household_id, settings, today)
    return DashboardOut(
        totals=d["totals"],
        low_stock=[item_out(v) for v in d["low_stock"]],
        expiring_soon=[item_out(v) for v in d["expiring_soon"]],
        expired=[item_out(v) for v in d["expired"]],
        recently_added=[
            TxnWithProduct(**txn_out(t).model_dump(), product=product_out(p))
            for t, p in d["recently_added"]
        ],
        recently_consumed=[
            TxnWithProduct(**txn_out(t).model_dump(), product=product_out(p))
            for t, p in d["recently_consumed"]
        ],
        unknown_count=d["unknown_count"],
        shopping_open_count=d["shopping_open_count"],
        by_location=[
            LocationCount(location=x["location"], item_count=x["item_count"])  # type: ignore[arg-type]
            for x in d["by_location"]
        ],
    )
