from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from .catalogue import ProductOut
from .common import ORM, Qty, Symbology, TxnType


class BatchOut(ORM):
    id: UUID
    product_id: UUID
    location_id: UUID
    quantity: Qty
    expires_at: date | None
    opened_at: date | None
    created_at: datetime
    updated_at: datetime


class BatchPatch(BaseModel):
    expires_at: date | None = None
    opened_at: date | None = None


class TransactionOut(BaseModel):
    id: UUID
    client_op_id: UUID
    product_id: UUID
    batch_id: UUID | None
    type: str
    quantity_delta: Qty
    location_id: UUID | None
    to_location_id: UUID | None
    reason: str | None
    undoes_id: UUID | None
    undone: bool
    user_id: UUID | None
    device_name: str | None
    occurred_at: datetime
    created_at: datetime


class InventoryItemOut(BaseModel):
    product: ProductOut
    total_quantity: Qty
    batches: list[BatchOut]
    next_expiry: date | None
    low_stock: bool


class InventoryDetailOut(InventoryItemOut):
    transactions: list[TransactionOut]


class SyncOp(BaseModel):
    client_op_id: UUID
    type: TxnType
    barcode: str | None = Field(default=None, min_length=1, max_length=200)
    symbology: Symbology | None = None
    product_id: UUID | None = None
    quantity: Qty | None = Field(default=None, ge=-(10**9), le=10**9)
    location_id: UUID | None = None
    to_location_id: UUID | None = None
    expires_at: date | None = None
    undoes_client_op_id: UUID | None = None
    occurred_at: datetime | None = None
    reason: str | None = Field(default=None, max_length=500)


class SyncOpsIn(BaseModel):
    device_id: str | None = Field(default=None, max_length=100)
    ops: list[SyncOp] = Field(max_length=500)


class OpResultOut(BaseModel):
    client_op_id: UUID
    status: Literal["applied", "duplicate", "rejected"]
    error: str | None = None
    error_code: str | None = None
    transaction_id: UUID | None = None
    product: ProductOut | None = None
    total_quantity: Qty | None = None


class SyncOpsOut(BaseModel):
    results: list[OpResultOut]
    server_time: datetime


class UndoIn(BaseModel):
    client_op_id: UUID


class TxnWithProduct(TransactionOut):
    product: ProductOut


class LocationCount(BaseModel):
    location: "LocationOut"
    item_count: int


class DashboardTotals(BaseModel):
    products_in_stock: int
    items: float


class DashboardOut(BaseModel):
    totals: DashboardTotals
    low_stock: list[InventoryItemOut]
    expiring_soon: list[InventoryItemOut]
    expired: list[InventoryItemOut]
    recently_added: list[TxnWithProduct]
    recently_consumed: list[TxnWithProduct]
    unknown_count: int
    shopping_open_count: int
    by_location: list[LocationCount]


from .catalogue import LocationOut  # noqa: E402

LocationCount.model_rebuild()
