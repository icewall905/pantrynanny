"""Data exports (CSV for Danish Excel, JSON for everything else).

CSV conventions (chosen for Excel with a Danish locale, which uses ``;`` as list separator and
``,`` as decimal mark): UTF-8 with BOM, ``;`` separator, CRLF line ends, RFC-4180 quoting, decimal
comma for numbers, ``YYYY-MM-DD`` dates and ``YYYY-MM-DD HH:MM:SS`` local (PN_TIMEZONE) date-times,
list values joined with ``, ``. Cells that would be read as formulas are prefixed with ``'``.
JSON keeps machine types: numbers, ISO-8601 timestamps with offset, arrays.
"""

import csv
import io
import json
import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..errors import not_found
from ..models import Category, Location, Product, ShoppingItem, StockTransaction
from .households import get_household_settings
from .inventory import list_inventory

RESOURCES = ("inventory", "shopping", "expiring", "products", "transactions")
BOM = "﻿"


async def _lookups(session: AsyncSession, household_id: uuid.UUID):
    locs = {
        r.id: r.name
        for r in (
            await session.execute(select(Location).where(Location.household_id == household_id))
        )
        .scalars()
        .all()
    }
    cats = {
        r.id: r.name
        for r in (
            await session.execute(select(Category).where(Category.household_id == household_id))
        )
        .scalars()
        .all()
    }
    return locs, cats


def _first_barcode(p: Product) -> str | None:
    return p.barcodes[0].raw if p.barcodes else None


async def _inventory_rows(
    session: AsyncSession,
    household_id: uuid.UUID,
    tz: ZoneInfo,
    *,
    only_expiring_before: date | None = None,
) -> list[dict]:
    locs, cats = await _lookups(session, household_id)
    rows: list[dict] = []
    for v in await list_inventory(session, household_id):
        p = v.product
        for b in v.batches:
            if b.quantity <= 0:
                continue
            if only_expiring_before and (
                b.expires_at is None or b.expires_at > only_expiring_before
            ):
                continue
            rows.append(
                {
                    "product_id": p.id,
                    "name": p.name,
                    "brand": p.brand,
                    "category": cats.get(p.category_id),
                    "location": locs.get(b.location_id),
                    "quantity": b.quantity,
                    "unit": p.stock_unit,
                    "package_size": p.package_size,
                    "package_unit": p.package_unit,
                    "expires_at": b.expires_at,
                    "opened_at": b.opened_at,
                    "barcode": _first_barcode(p),
                    "min_stock": p.min_stock,
                    "low_stock": v.low_stock,
                }
            )
    if only_expiring_before:
        rows.sort(key=lambda r: (r["expires_at"], r["name"].lower()))
    return rows


async def build_rows(
    session: AsyncSession,
    household_id: uuid.UUID,
    resource: str,
    tz: ZoneInfo,
    *,
    days: int | None = None,
) -> list[dict[str, Any]]:
    if resource == "inventory":
        return await _inventory_rows(session, household_id, tz)
    if resource == "expiring":
        s = await get_household_settings(session, household_id)
        today = datetime.now(tz).date()
        horizon = today + timedelta(days=days if days is not None else s.expiry_soon_days)
        return await _inventory_rows(session, household_id, tz, only_expiring_before=horizon)
    locs, cats = await _lookups(session, household_id)
    if resource == "shopping":
        items = (
            (
                await session.execute(
                    select(ShoppingItem)
                    .where(
                        ShoppingItem.household_id == household_id, ShoppingItem.deleted_at.is_(None)
                    )
                    .order_by(ShoppingItem.checked, ShoppingItem.created_at)
                )
            )
            .scalars()
            .all()
        )
        return [
            {
                "id": i.id,
                "name": i.name,
                "quantity": i.quantity,
                "unit": i.unit,
                "category": cats.get(i.category_id),
                "note": i.note,
                "checked": i.checked,
                "source": i.source,
                "product_id": i.product_id,
                "created_at": i.created_at,
            }
            for i in items
        ]
    if resource == "products":
        prods = (
            (
                await session.execute(
                    select(Product)
                    .where(Product.household_id == household_id, Product.deleted_at.is_(None))
                    .order_by(Product.name)
                )
            )
            .scalars()
            .all()
        )
        return [
            {
                "id": p.id,
                "name": p.name,
                "brand": p.brand,
                "category": cats.get(p.category_id),
                "barcodes": [b.raw for b in p.barcodes],
                "package_size": p.package_size,
                "package_unit": p.package_unit,
                "stock_unit": p.stock_unit,
                "min_stock": p.min_stock,
                "status": p.status,
                "source": p.source,
                "source_attribution": p.source_attribution,
                "allergens": list(p.allergens or []),
                "ingredients": p.ingredients,
                "countries": list(p.countries or []),
                "created_at": p.created_at,
                "updated_at": p.updated_at,
            }
            for p in prods
        ]
    if resource == "transactions":
        rows = (
            await session.execute(
                select(StockTransaction, Product.name)
                .join(Product, Product.id == StockTransaction.product_id)
                .where(StockTransaction.household_id == household_id)
                .order_by(StockTransaction.occurred_at.desc(), StockTransaction.created_at.desc())
            )
        ).all()
        return [
            {
                "id": t.id,
                "occurred_at": t.occurred_at,
                "type": t.type,
                "product_id": t.product_id,
                "product": name,
                "quantity_delta": t.quantity_delta,
                "location": locs.get(t.location_id),
                "to_location": locs.get(t.to_location_id),
                "reason": t.reason,
                "undone": t.undone,
                "device": t.device_name,
            }
            for t, name in rows
        ]
    raise not_found("Unknown export")


# --------------------------------------------------------------------------- rendering


def _json_default(o: Any):
    if isinstance(o, Decimal):
        return float(o)
    if isinstance(o, datetime | date):
        return o.isoformat()
    if isinstance(o, uuid.UUID):
        return str(o)
    raise TypeError(type(o))


def to_json(rows: list[dict]) -> str:
    return json.dumps(rows, default=_json_default, ensure_ascii=False, indent=2) + "\n"


def _cell(v: Any, tz: ZoneInfo) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, Decimal | float | int):
        text = format(v.normalize(), "f") if isinstance(v, Decimal) else str(v)
        return text.replace(".", ",")
    if isinstance(v, datetime):
        return v.astimezone(tz).strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(v, date):
        return v.isoformat()
    s = ", ".join(str(x) for x in v) if isinstance(v, list) else str(v)
    if s.lstrip()[:1] in ("=", "+", "-", "@", "\t", "\r"):
        s = "'" + s  # neutralise spreadsheet formula injection
    return s


def to_csv(rows: list[dict], tz: ZoneInfo, columns: list[str] | None = None) -> str:
    cols = columns or (list(rows[0].keys()) if rows else [])
    buf = io.StringIO(newline="")
    w = csv.writer(buf, delimiter=";", quoting=csv.QUOTE_MINIMAL, lineterminator="\r\n")
    w.writerow(cols)
    for r in rows:
        w.writerow([_cell(r.get(c), tz) for c in cols])
    return BOM + buf.getvalue()


COLUMNS = {
    "inventory": [
        "product_id",
        "name",
        "brand",
        "category",
        "location",
        "quantity",
        "unit",
        "package_size",
        "package_unit",
        "expires_at",
        "opened_at",
        "barcode",
        "min_stock",
        "low_stock",
    ],
    "expiring": [
        "product_id",
        "name",
        "brand",
        "category",
        "location",
        "quantity",
        "unit",
        "package_size",
        "package_unit",
        "expires_at",
        "opened_at",
        "barcode",
        "min_stock",
        "low_stock",
    ],
    "shopping": [
        "id",
        "name",
        "quantity",
        "unit",
        "category",
        "note",
        "checked",
        "source",
        "product_id",
        "created_at",
    ],
    "products": [
        "id",
        "name",
        "brand",
        "category",
        "barcodes",
        "package_size",
        "package_unit",
        "stock_unit",
        "min_stock",
        "status",
        "source",
        "source_attribution",
        "allergens",
        "ingredients",
        "countries",
        "created_at",
        "updated_at",
    ],
    "transactions": [
        "id",
        "occurred_at",
        "type",
        "product_id",
        "product",
        "quantity_delta",
        "location",
        "to_location",
        "reason",
        "undone",
        "device",
    ],
}
