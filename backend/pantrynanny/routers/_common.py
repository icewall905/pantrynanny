"""Helpers shared by routers."""

import re

from fastapi import Header

from ..errors import AppError
from ..models import StockTransaction
from ..schemas.inventory import InventoryItemOut, TransactionOut
from ..services.inventory import StockView
from ..services.products import product_out

_ETAG = re.compile(r'^\s*(?:W/)?"?(\d+)"?\s*$')


def parse_if_match(value: str | None) -> int | None:
    if value is None:
        return None
    m = _ETAG.match(value)
    if not m:
        raise AppError(400, "bad_if_match", "If-Match must be a version number")
    return int(m.group(1))


async def if_match_optional(if_match: str | None = Header(default=None)) -> int | None:
    return parse_if_match(if_match)


async def if_match_required(if_match: str | None = Header(default=None)) -> int:
    v = parse_if_match(if_match)
    if v is None:
        raise AppError(428, "if_match_required", "If-Match header is required")
    return v


def item_out(view: StockView) -> InventoryItemOut:
    return InventoryItemOut(
        product=product_out(view.product),
        total_quantity=view.total,
        batches=view.batches,  # type: ignore[arg-type]
        next_expiry=view.next_expiry,
        low_stock=view.low_stock,
    )


def txn_out(t: StockTransaction) -> TransactionOut:
    return TransactionOut(
        id=t.id,
        client_op_id=t.client_op_id,
        product_id=t.product_id,
        batch_id=t.batch_id,
        type=t.type,
        quantity_delta=t.quantity_delta,
        location_id=t.location_id,
        to_location_id=t.to_location_id,
        reason=t.reason,
        undoes_id=t.undoes_id,
        undone=t.undone,
        user_id=t.user_id,
        device_name=t.device_name,
        occurred_at=t.occurred_at,
        created_at=t.created_at,
    )
