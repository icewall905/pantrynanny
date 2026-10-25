import asyncio

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..db import get_session, get_sessionmaker
from ..recipes.fetch import fetch_page
from ..security import Principal, require_admin
from ..services import recipe_backfill as svc

router = APIRouter(prefix="/admin", tags=["admin"])


class BackfillIn(BaseModel):
    limit: int | None = Field(default=None, ge=1, le=5000)  # recipes in this run (None = all)
    delay_s: float = Field(default=svc.DEFAULT_DELAY_S, ge=0.5, le=60)


def _status(request: Request, principal: Principal) -> svc.BackfillStatus:
    runs = request.app.state.__dict__.setdefault("recipe_backfill", {})
    return runs.setdefault(principal.household_id, svc.BackfillStatus())


@router.get("/recipes/backfill")
async def backfill_status(
    request: Request,
    principal: Principal = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    """Progress of the "re-read recipe pages" job and how many recipes still lack data."""
    st = _status(request, principal)
    if not st.running:
        st.remaining = await svc.remaining(session, principal.household_id)
    return st.public()


@router.post("/recipes/backfill", status_code=202)
async def start_backfill(
    body: BackfillIn,
    request: Request,
    principal: Principal = Depends(require_admin),
    sm: async_sessionmaker[AsyncSession] = Depends(get_sessionmaker),
):
    """Re-read the source page of recipes without cooking time or course (one page at a time,
    `delay_s` apart, through the safe fetcher). Resumable; a second start while running is a
    no-op."""
    st = _status(request, principal)
    if not st.running:
        fresh = svc.BackfillStatus()
        request.app.state.recipe_backfill[principal.household_id] = fresh
        fetcher = getattr(request.app.state, "recipe_fetcher", None) or fetch_page
        fresh.running = True
        fresh._task = asyncio.create_task(
            svc.run(
                sm,
                principal.household_id,
                fresh,
                fetcher=fetcher,
                delay_s=body.delay_s,
                limit=body.limit,
            )
        )
        st = fresh
    return st.public()
