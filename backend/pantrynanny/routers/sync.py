from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..db import get_session, get_sessionmaker
from ..schemas.admin import SettingsOut
from ..schemas.catalogue import CategoryOut, LocationOut, ProductOut
from ..schemas.common import Qty
from ..schemas.inventory import BatchOut, SyncOpsIn, SyncOpsOut
from ..security import Principal, get_principal
from ..services import sync as svc
from ..services.households import get_household_settings
from ..services.inventory import process_op
from ..services.products import product_out
from .inventory import op_result_out

router = APIRouter(tags=["sync"])


class InventoryEntry(BaseModel):
    product_id: str
    total_quantity: Qty
    batches: list[BatchOut]


class SnapshotOut(BaseModel):
    cursor: str
    products: list[ProductOut]
    inventory: list[InventoryEntry]
    locations: list[LocationOut]
    categories: list[CategoryOut]
    settings: SettingsOut


class ChangesOut(BaseModel):
    cursor: str
    products: list[ProductOut]
    inventory: list[InventoryEntry]
    locations: list[LocationOut]
    categories: list[CategoryOut]
    full_resync_required: bool


def _entries(ch: svc.Changes) -> list[InventoryEntry]:
    return [
        InventoryEntry(
            product_id=str(v.product.id),
            total_quantity=sum((b.quantity for b in v.batches), start=0),  # type: ignore[arg-type]
            batches=v.batches,  # type: ignore[arg-type]
        )
        for v in ch.inventory
    ]


@router.post("/sync/ops", response_model=SyncOpsOut)
async def post_ops(
    body: SyncOpsIn,
    principal: Principal = Depends(get_principal),
    sm: async_sessionmaker[AsyncSession] = Depends(get_sessionmaker),
):
    results = []
    for op in body.ops:  # applied in array order, each in its own transaction
        results.append(op_result_out(await process_op(sm, principal, op, body.device_id)))
    return SyncOpsOut(results=results, server_time=datetime.now(UTC))


@router.get("/sync/snapshot", response_model=SnapshotOut)
async def get_snapshot(
    principal: Principal = Depends(get_principal), session: AsyncSession = Depends(get_session)
):
    ch = await svc.snapshot(session, principal.household_id)
    settings = await get_household_settings(session, principal.household_id)
    return SnapshotOut(
        cursor=ch.cursor,
        products=[product_out(p) for p in ch.products],
        inventory=_entries(ch),
        locations=ch.locations,  # type: ignore[arg-type]
        categories=ch.categories,  # type: ignore[arg-type]
        settings=settings,  # type: ignore[arg-type]
    )


@router.get("/sync/changes", response_model=ChangesOut)
async def get_changes(
    since: str = Query(max_length=40),
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
):
    ch = await svc.changes_since(session, principal.household_id, since)
    return ChangesOut(
        cursor=ch.cursor,
        products=[product_out(p) for p in ch.products],
        inventory=_entries(ch),
        locations=ch.locations,  # type: ignore[arg-type]
        categories=ch.categories,  # type: ignore[arg-type]
        full_resync_required=ch.full_resync_required,
    )
