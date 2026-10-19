import uuid

from fastapi import APIRouter, Depends, Response
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..schemas.inventory import InventoryItemOut
from ..schemas.shopping import ShoppingCreate, ShoppingItemOut, ShoppingPatch
from ..security import Principal, get_principal
from ..services import shopping as svc
from ._common import if_match_optional, item_out

router = APIRouter(tags=["shopping"])


@router.get("/shopping", response_model=list[ShoppingItemOut])
async def list_shopping(
    principal: Principal = Depends(get_principal), session: AsyncSession = Depends(get_session)
):
    return await svc.list_items(session, principal.household_id)


# Static paths first so they are not captured by /shopping/{item_id}.
@router.get("/shopping/suggestions", response_model=list[InventoryItemOut])
async def shopping_suggestions(
    principal: Principal = Depends(get_principal), session: AsyncSession = Depends(get_session)
):
    return [item_out(v) for v in await svc.suggestions(session, principal.household_id)]


@router.post("/shopping/clear-checked")
async def clear_checked(
    principal: Principal = Depends(get_principal), session: AsyncSession = Depends(get_session)
):
    removed = await svc.clear_checked(session, principal.household_id)
    await session.commit()
    return {"removed": removed}


@router.post("/shopping", response_model=ShoppingItemOut, status_code=201)
async def add_shopping(
    body: ShoppingCreate,
    response: Response,
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
):
    item, created = await svc.add_item(session, principal.household_id, body)
    await session.commit()
    if not created:
        response.status_code = 200  # merged into an existing open item
    return item


@router.patch("/shopping/{item_id}", response_model=ShoppingItemOut)
async def patch_shopping(
    item_id: uuid.UUID,
    body: ShoppingPatch,
    version: int | None = Depends(if_match_optional),
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
):
    item = await svc.patch_item(session, principal.household_id, item_id, body, version)
    await session.commit()
    return item


@router.delete("/shopping/{item_id}", status_code=204)
async def delete_shopping(
    item_id: uuid.UUID,
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
):
    await svc.delete_item(session, principal.household_id, item_id)
    await session.commit()
    return Response(status_code=204)
