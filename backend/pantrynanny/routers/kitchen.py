from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..schemas.inventory import InventoryItemOut
from ..security import Principal, get_principal
from ..services.kitchen import kitchen_tiles
from ._common import item_out

router = APIRouter(tags=["kitchen"])


class KitchenTile(InventoryItemOut):
    uses: int


@router.get("/kitchen/tiles", response_model=list[KitchenTile])
async def tiles(
    limit: int = Query(default=12, ge=1, le=48),
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
):
    rows = await kitchen_tiles(session, principal.household_id, limit=limit)
    return [KitchenTile(**item_out(v).model_dump(), uses=n) for v, n in rows]
