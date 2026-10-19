from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from .common import MAX_OP_QTY, ORM, Qty, Unit


class ShoppingItemOut(ORM):
    id: UUID
    version: int
    product_id: UUID | None
    name: str
    quantity: Qty
    unit: str | None
    category_id: UUID | None
    note: str | None
    checked: bool
    checked_at: datetime | None
    source: str
    created_at: datetime
    updated_at: datetime


class ShoppingCreate(BaseModel):
    product_id: UUID | None = None
    name: str | None = Field(default=None, min_length=1, max_length=200)
    quantity: Qty = Field(default=1, gt=0, le=MAX_OP_QTY, decimal_places=3)
    unit: Unit | None = None
    category_id: UUID | None = None
    note: str | None = Field(default=None, max_length=500)


class ShoppingPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    quantity: Qty | None = Field(default=None, gt=0, le=MAX_OP_QTY, decimal_places=3)
    unit: Unit | None = None
    category_id: UUID | None = None
    note: str | None = Field(default=None, max_length=500)
    checked: bool | None = None
