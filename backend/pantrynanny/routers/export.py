import re
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..errors import not_found
from ..security import Principal, get_principal
from ..services import exports as svc

router = APIRouter(tags=["export"])

_NAME = re.compile(r"^(inventory|shopping|expiring|products|transactions)\.(csv|json)$")


@router.get("/export/{name}")
async def export(
    name: str,
    request: Request,
    days: int | None = Query(default=None, ge=0, le=365, description="expiring: horizon in days"),
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
):
    m = _NAME.match(name)
    if not m:
        raise not_found("Unknown export")
    resource, fmt = m.groups()
    tz = ZoneInfo(request.app.state.settings.timezone)
    rows = await svc.build_rows(session, principal.household_id, resource, tz, days=days)
    stamp = datetime.now(tz).date().isoformat()
    filename = f"pantrynanny-{resource}-{stamp}.{fmt}"
    if fmt == "csv":
        body = svc.to_csv(rows, tz, svc.COLUMNS[resource]).encode("utf-8")
        ctype = "text/csv; charset=utf-8"
    else:
        body = svc.to_json(rows).encode("utf-8")
        ctype = "application/json"
    return Response(
        body,
        media_type=ctype,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
        },
    )
