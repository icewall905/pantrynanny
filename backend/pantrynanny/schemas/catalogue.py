from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from .common import ORM, ProductStatus, Qty, Symbology, Unit


class LocationOut(ORM):
    id: UUID
    name: str
    icon: str | None
    sort_order: int
    is_default: bool
    deleted_at: datetime | None


class LocationIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    icon: str | None = Field(default=None, max_length=40)
    sort_order: int = 0
    is_default: bool = False


class LocationPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    icon: str | None = Field(default=None, max_length=40)
    sort_order: int | None = None
    is_default: bool | None = None


class CategoryOut(ORM):
    id: UUID
    name: str
    icon: str | None
    color: str | None
    sort_order: int
    deleted_at: datetime | None


class CategoryIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    icon: str | None = Field(default=None, max_length=40)
    color: str | None = Field(default=None, max_length=20)
    sort_order: int = 0


class CategoryPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    icon: str | None = Field(default=None, max_length=40)
    color: str | None = Field(default=None, max_length=20)
    sort_order: int | None = None


class BarcodeOut(ORM):
    code: str
    raw: str
    symbology: str | None


class ProductOut(BaseModel):
    id: UUID
    version: int
    name: str
    brand: str | None
    category_id: UUID | None
    default_location_id: UUID | None
    image_url: str | None
    package_size: Qty | None
    package_unit: str | None
    stock_unit: str
    min_stock: Qty | None
    ingredients: str | None
    allergens: list[str]
    nutrition: dict[str, Any] | None
    description: str | None
    countries: list[str]
    barcodes: list[BarcodeOut]
    aliases: list[str]
    status: str
    source: str
    source_attribution: str | None
    lookup_confidence: float | None
    locked_fields: list[str]
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None


class ProductFields(BaseModel):
    """Editable product metadata (shared by create and patch)."""

    name: str = Field(min_length=1, max_length=200)
    brand: str | None = Field(default=None, max_length=120)
    category_id: UUID | None = None
    default_location_id: UUID | None = None
    package_size: Qty | None = Field(default=None, ge=0, lt=10**9)
    package_unit: Unit | None = None
    stock_unit: Unit = "pcs"
    min_stock: Qty | None = Field(default=None, ge=0, lt=10**9)
    ingredients: str | None = Field(default=None, max_length=8000)
    allergens: list[str] = Field(default_factory=list, max_length=50)
    nutrition: dict[str, Any] | None = None
    description: str | None = Field(default=None, max_length=4000)
    countries: list[str] = Field(default_factory=list, max_length=50)
    aliases: list[str] = Field(default_factory=list, max_length=50)
    status: ProductStatus = "known"


class ProductCreate(ProductFields):
    barcodes: list[str] = Field(default_factory=list, max_length=20)
    symbology: Symbology | None = None


class ProductPatch(BaseModel):
    """All fields optional; only fields present in the body are changed (and then locked)."""

    name: str | None = Field(default=None, min_length=1, max_length=200)
    brand: str | None = Field(default=None, max_length=120)
    category_id: UUID | None = None
    default_location_id: UUID | None = None
    package_size: Qty | None = Field(default=None, ge=0, lt=10**9)
    package_unit: Unit | None = None
    stock_unit: Unit | None = None
    min_stock: Qty | None = Field(default=None, ge=0, lt=10**9)
    ingredients: str | None = Field(default=None, max_length=8000)
    allergens: list[str] | None = Field(default=None, max_length=50)
    nutrition: dict[str, Any] | None = None
    description: str | None = Field(default=None, max_length=4000)
    countries: list[str] | None = Field(default=None, max_length=50)
    aliases: list[str] | None = Field(default=None, max_length=50)
    status: ProductStatus | None = None


class BarcodeAddIn(BaseModel):
    raw: str = Field(min_length=1, max_length=200)
    symbology: Symbology | None = None


class MergeIn(BaseModel):
    into_id: UUID


class ByBarcodeOut(BaseModel):
    status: str  # found | created_placeholder | not_found
    product: ProductOut | None
    source: str | None
    barcode: BarcodeOut
    valid: bool
