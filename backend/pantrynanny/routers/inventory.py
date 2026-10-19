import uuid
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..db import get_session, get_sessionmaker
from ..errors import AppError, not_found
from ..models import Product, StockTransaction, User
from ..schemas.inventory import (
    BatchOut,
    BatchPatch,
    InventoryDetailOut,
    InventoryItemOut,
    OpResultOut,
    SyncOp,
    TransactionOut,
    TxnWithProduct,
    UndoIn,
)
from ..security import Principal, get_principal
from ..services import inventory as svc
from ..services.products import get_product, product_out
from ._common import item_out, txn_out

router = APIRouter(tags=["inventory"])


def op_result_out(r: svc.OpResult) -> OpResultOut:
    return OpResultOut(
        client_op_id=r.client_op_id,
        status=r.status,  # type: ignore[arg-type]
        error=r.error,
        error_code=r.error_code,
        transaction_id=r.transaction_id,
        product=product_out(r.product) if r.product else None,
        total_quantity=r.total_quantity,
    )


@router.get("/inventory", response_model=list[InventoryItemOut])
async def list_inventory(
    location_id: uuid.UUID | None = None,
    category_id: uuid.UUID | None = None,
    q: str | None = Query(default=None, max_length=200),
    sort: Literal["name", "quantity", "expiry", "updated"] = "name",
    include_empty: bool = False,
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
):
    views = await svc.list_inventory(
        session,
        principal.household_id,
        location_id=location_id,
        category_id=category_id,
        q=q,
        sort=sort,
        include_empty=include_empty,
    )
    return [item_out(v) for v in views]


@router.get("/inventory/{product_id}", response_model=InventoryDetailOut)
async def inventory_detail(
    product_id: uuid.UUID,
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
):
    view = await svc.get_inventory_item(session, principal.household_id, product_id)
    txns = await svc.recent_transactions(
        session, principal.household_id, product_id=product_id, limit=50
    )
    base = item_out(view)
    return InventoryDetailOut(**base.model_dump(), transactions=[txn_out(t) for t in txns])


@router.patch("/batches/{batch_id}", response_model=BatchOut)
async def patch_batch(
    batch_id: uuid.UUID,
    body: BatchPatch,
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
):
    fields = {k: getattr(body, k) for k in body.model_fields_set}
    batch = await svc.update_batch_meta(session, principal.household_id, batch_id, fields)
    await session.commit()
    return batch


def _parse_before(value: str | None) -> tuple[datetime, uuid.UUID | None] | None:
    """``before`` is an ISO timestamp, or the composite ``<iso timestamp>|<uuid>`` cursor that
    ``X-Next-Before`` returns (created_at ties are broken by id)."""
    if not value:
        return None
    ts_part, _, id_part = value.partition("|")
    try:
        ts = datetime.fromisoformat(ts_part.replace(" ", "+"))
        tid = uuid.UUID(id_part) if id_part else None
    except ValueError as exc:
        raise AppError(422, "invalid_cursor", "before must be an ISO timestamp[|id]") from exc
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)
    return ts, tid


@router.get("/transactions", response_model=list[TransactionOut])
async def list_transactions(
    response: Response,
    product_id: uuid.UUID | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    before: str | None = Query(default=None, max_length=80),
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
):
    if product_id:
        await get_product(session, principal.household_id, product_id, include_deleted=True)
    rows = await svc.recent_transactions(
        session,
        principal.household_id,
        product_id=product_id,
        limit=limit,
        before=_parse_before(before),
    )
    if len(rows) == limit:  # full page: hand out the keyset cursor for the next one
        last = rows[-1]
        response.headers["X-Next-Before"] = f"{last.created_at.isoformat()}|{last.id}"
    return [txn_out(t) for t in rows]


class ActivityOut(TxnWithProduct):
    user_name: str | None


@router.get("/activity", response_model=list[ActivityOut])
async def activity(
    response: Response,
    limit: int = Query(default=50, ge=1, le=200),
    before: str | None = Query(default=None, max_length=80),
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
):
    """The household timeline: every stock change with product and who/which device did it."""
    rows = await svc.recent_transactions(
        session, principal.household_id, limit=limit, before=_parse_before(before)
    )
    if len(rows) == limit:
        last = rows[-1]
        response.headers["X-Next-Before"] = f"{last.created_at.isoformat()}|{last.id}"
    pids = {t.product_id for t in rows}
    uids = {t.user_id for t in rows if t.user_id}
    products = {
        p.id: p
        for p in (await session.execute(select(Product).where(Product.id.in_(pids)))).scalars()
    }
    users = (
        dict(
            (
                await session.execute(select(User.id, User.display_name).where(User.id.in_(uids)))
            ).all()
        )
        if uids
        else {}
    )
    return [
        ActivityOut(
            **txn_out(t).model_dump(),
            product=product_out(products[t.product_id]),
            user_name=users.get(t.user_id) if t.user_id else None,
        )
        for t in rows
        if t.product_id in products
    ]


@router.post("/transactions/{txn_id}/undo", response_model=OpResultOut)
async def undo_transaction(
    txn_id: uuid.UUID,
    body: UndoIn,
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
    sm: async_sessionmaker[AsyncSession] = Depends(get_sessionmaker),
):
    original = await session.get(StockTransaction, txn_id)
    if original is None or original.household_id != principal.household_id:
        raise not_found("Transaction not found")
    op = SyncOp(
        client_op_id=body.client_op_id,
        type="undo",
        undoes_client_op_id=original.client_op_id,
    )
    result = await svc.process_op(sm, principal, op)
    if result.status == "rejected":
        status = 409 if result.error_code in ("already_undone", "cannot_undo_undo") else 422
        raise AppError(status, result.error_code or "rejected", result.error or "Rejected")
    return op_result_out(result)
