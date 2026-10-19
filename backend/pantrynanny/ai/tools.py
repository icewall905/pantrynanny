"""Read-only inventory tools exposed to the model.

Every tool is a validated Python function over the household-scoped database. The model never
supplies SQL and nothing here writes. Results are compact JSON, size-capped, and always wrapped
in delimiters that mark them as untrusted data.
"""

import json
import re
import unicodedata
import uuid
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Category, Location
from ..services import shopping as shopping_svc
from ..services.inventory import StockView, list_inventory

MAX_RESULT_CHARS = 6000
MAX_ITEMS = 40
OPEN = "<<<PANTRY_DATA"
CLOSE = "<<<END_PANTRY_DATA>>>"

_CTRL = re.compile(r"[\x00-\x1f\x7f]+")


def clean(value: Any, limit: int = 100) -> str:
    """Sanitise untrusted text: strip control chars, neutralise our delimiters, truncate."""
    s = _CTRL.sub(" ", str(value)).strip()
    s = s.replace("<<<", "< < <").replace(">>>", "> > >")
    return s[:limit]


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s.casefold())
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return s.replace("æ", "ae").replace("ø", "o").replace("å", "a")


def wrap_untrusted(tool: str, payload: str) -> str:
    return f'{OPEN} tool="{clean(tool, 40)}" trust="untrusted">>>\n{payload}\n{CLOSE}'


@dataclass(slots=True)
class ToolContext:
    session: AsyncSession
    household_id: uuid.UUID
    today: date


# --------------------------------------------------------------------------- argument schemas


class _Args(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)


class SearchInventoryArgs(_Args):
    query: str = Field(min_length=1, max_length=100, description="Product name, brand or category")


class ListByLocationArgs(_Args):
    location: str = Field(min_length=1, max_length=60, description="Location name, e.g. Køleskab")


class ExpiringArgs(_Args):
    days: int = Field(default=3, ge=0, le=60, description="Look-ahead window in days (0-60)")


class ProductDetailsArgs(_Args):
    product_id: str | None = Field(default=None, max_length=40, description="Product UUID")
    name: str | None = Field(default=None, max_length=100, description="Product name")

    @model_validator(mode="after")
    def _one(self):
        if not self.product_id and not self.name:
            raise ValueError("product_id or name is required")
        return self


class NoArgs(_Args):
    pass


# --------------------------------------------------------------------------- data helpers


async def _names(ctx: ToolContext) -> tuple[dict[uuid.UUID, str], dict[uuid.UUID, str]]:
    locs = (
        await ctx.session.execute(
            select(Location).where(
                Location.household_id == ctx.household_id, Location.deleted_at.is_(None)
            )
        )
    ).scalars()
    cats = (
        await ctx.session.execute(
            select(Category).where(
                Category.household_id == ctx.household_id, Category.deleted_at.is_(None)
            )
        )
    ).scalars()
    return {x.id: x.name for x in locs}, {c.id: c.name for c in cats}


def _qty(x: Any) -> float:
    return round(float(x), 3)


def _item(v: StockView, locs: dict, cats: dict, today: date) -> dict[str, Any]:
    p = v.product
    by_loc: dict[str, float] = {}
    for b in v.batches:
        if b.quantity > 0:
            n = clean(locs.get(b.location_id, "?"), 40)
            by_loc[n] = round(by_loc.get(n, 0.0) + float(b.quantity), 3)
    out: dict[str, Any] = {
        "id": str(p.id),
        "name": clean(p.name),
        "quantity": _qty(v.total),
        "unit": clean(p.stock_unit, 8),
        "locations": by_loc,
    }
    if p.brand:
        out["brand"] = clean(p.brand, 60)
    if p.category_id in cats:
        out["category"] = clean(cats[p.category_id], 40)
    if v.next_expiry:
        out["next_expiry"] = v.next_expiry.isoformat()
        if v.next_expiry < today:
            out["expired"] = True
    if v.low_stock:
        out["low_stock"] = True
    return out


def _items_result(items: list[dict], extra: dict | None = None) -> dict[str, Any]:
    res: dict[str, Any] = {"count": len(items), **(extra or {}), "items": items[:MAX_ITEMS]}
    if len(items) > MAX_ITEMS:
        res["truncated"] = True
    return res


# --------------------------------------------------------------------------- tools


async def search_inventory(ctx: ToolContext, a: SearchInventoryArgs) -> dict:
    locs, cats = await _names(ctx)
    views = await list_inventory(ctx.session, ctx.household_id, q=a.query, include_empty=True)
    in_stock = [v for v in views if v.total > 0]
    items = [_item(v, locs, cats, ctx.today) for v in (in_stock or views)]
    return _items_result(items, {"query": clean(a.query), "in_stock": bool(in_stock)})


async def list_inventory_by_location(ctx: ToolContext, a: ListByLocationArgs) -> dict:
    locs, cats = await _names(ctx)
    want = norm(a.location)
    match = [i for i, n in locs.items() if norm(n) == want] or [
        i for i, n in locs.items() if want in norm(n) or norm(n) in want
    ]
    if not match:
        return {
            "error": "unknown location",
            "available_locations": [clean(n, 40) for n in locs.values()],
        }
    views = await list_inventory(ctx.session, ctx.household_id, location_id=match[0])
    return _items_result(
        [_item(v, locs, cats, ctx.today) for v in views], {"location": clean(locs[match[0]], 40)}
    )


async def list_expiring_products(ctx: ToolContext, a: ExpiringArgs) -> dict:
    locs, cats = await _names(ctx)
    limit = ctx.today + timedelta(days=a.days)
    rows: list[tuple[date, dict]] = []
    for v in await list_inventory(ctx.session, ctx.household_id, sort="expiry"):
        hits = [b for b in v.batches if b.quantity > 0 and b.expires_at and b.expires_at <= limit]
        if not hits:
            continue
        first = min(b.expires_at for b in hits)
        rows.append(
            (
                first,
                {
                    "id": str(v.product.id),
                    "name": clean(v.product.name),
                    "unit": clean(v.product.stock_unit, 8),
                    "batches": [
                        {
                            "quantity": _qty(b.quantity),
                            "expires": b.expires_at.isoformat(),
                            "days_left": (b.expires_at - ctx.today).days,
                            "location": clean(locs.get(b.location_id, "?"), 40),
                        }
                        for b in hits
                    ],
                },
            )
        )
    rows.sort(key=lambda r: r[0])
    return _items_result(
        [r[1] for r in rows], {"window_days": a.days, "today": ctx.today.isoformat()}
    )


async def get_product_details(ctx: ToolContext, a: ProductDetailsArgs) -> dict:
    locs, cats = await _names(ctx)
    views = await list_inventory(ctx.session, ctx.household_id, include_empty=True)
    found: StockView | None = None
    if a.product_id:
        try:
            pid = uuid.UUID(a.product_id)
        except ValueError:
            return {"error": "invalid product_id"}
        found = next((v for v in views if v.product.id == pid), None)
    elif a.name:
        want = norm(a.name)
        found = next((v for v in views if norm(v.product.name) == want), None) or next(
            (v for v in views if want in norm(v.product.name)), None
        )
    if found is None:
        return {"error": "product not found"}
    p = found.product
    d = _item(found, locs, cats, ctx.today)
    if p.package_size:
        d["package"] = f"{_qty(p.package_size)} {clean(p.package_unit or '', 8)}".strip()
    if p.min_stock is not None:
        d["min_stock"] = _qty(p.min_stock)
    if p.allergens:
        d["allergens"] = [clean(x, 30) for x in p.allergens[:15]]
    if p.ingredients:
        d["ingredients"] = clean(p.ingredients, 300)
    if p.description:
        d["description"] = clean(p.description, 300)
    d["batches"] = [
        {
            "quantity": _qty(b.quantity),
            "expires": b.expires_at.isoformat() if b.expires_at else None,
            "location": clean(locs.get(b.location_id, "?"), 40),
        }
        for b in found.batches
        if b.quantity > 0
    ][:15]
    return d


async def get_low_stock_items(ctx: ToolContext, a: NoArgs) -> dict:
    locs, cats = await _names(ctx)
    views = await list_inventory(ctx.session, ctx.household_id, include_empty=True)
    items = []
    for v in views:
        if v.low_stock:
            d = _item(v, locs, cats, ctx.today)
            d["min_stock"] = _qty(v.product.min_stock or 0)
            items.append(d)
    return _items_result(items)


async def get_shopping_list(ctx: ToolContext, a: NoArgs) -> dict:
    rows = await shopping_svc.list_items(ctx.session, ctx.household_id)
    items = [
        {
            "name": clean(r.name),
            "quantity": _qty(r.quantity),
            **({"unit": clean(r.unit, 8)} if r.unit else {}),
            **({"note": clean(r.note, 80)} if r.note else {}),
        }
        for r in rows
        if not r.checked
    ]
    return _items_result(items)


@dataclass(frozen=True, slots=True)
class Tool:
    name: str
    description: str
    args: type[_Args]
    fn: Any


TOOLS: dict[str, Tool] = {
    t.name: t
    for t in (
        Tool(
            "search_inventory",
            "Search the household inventory by product name, brand or category.",
            SearchInventoryArgs,
            search_inventory,
        ),
        Tool(
            "list_inventory_by_location",
            "List everything in stock in one storage location (e.g. fridge, freezer, pantry).",
            ListByLocationArgs,
            list_inventory_by_location,
        ),
        Tool(
            "list_expiring_products",
            "List products with batches that expire within N days (also already expired).",
            ExpiringArgs,
            list_expiring_products,
        ),
        Tool(
            "get_product_details",
            "Get details and stock batches for one product, by id or name.",
            ProductDetailsArgs,
            get_product_details,
        ),
        Tool(
            "get_low_stock_items",
            "List products below their minimum stock level.",
            NoArgs,
            get_low_stock_items,
        ),
        Tool(
            "get_shopping_list",
            "Show the open (unchecked) items on the shopping list.",
            NoArgs,
            get_shopping_list,
        ),
    )
}


def _strip_titles(node: Any) -> Any:
    if isinstance(node, dict):
        return {k: _strip_titles(v) for k, v in node.items() if k != "title"}
    if isinstance(node, list):
        return [_strip_titles(x) for x in node]
    return node


def tool_schemas() -> list[dict[str, Any]]:
    out = []
    for t in TOOLS.values():
        params = _strip_titles(t.args.model_json_schema())
        params.setdefault("properties", {})
        out.append(
            {
                "type": "function",
                "function": {"name": t.name, "description": t.description, "parameters": params},
            }
        )
    return out


def _cap(payload: dict) -> str:
    text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str)
    items = payload.get("items")
    while len(text) > MAX_RESULT_CHARS and isinstance(items, list) and items:
        items = items[: max(1, len(items) // 2)] if len(items) > 1 else []
        payload = {**payload, "items": items, "truncated": True}
        text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str)
    return text[:MAX_RESULT_CHARS]


async def run_tool(ctx: ToolContext, name: str, raw_arguments: Any) -> str:
    """Execute a tool call from the model; always returns wrapped, size-capped text."""
    tool = TOOLS.get(name)
    if tool is None:
        return wrap_untrusted(name, json.dumps({"error": "unknown tool"}))
    try:
        if isinstance(raw_arguments, str):
            raw_arguments = json.loads(raw_arguments) if raw_arguments.strip() else {}
        if not isinstance(raw_arguments, dict):
            raise ValueError("arguments must be an object")
        args = tool.args.model_validate(raw_arguments)
    except (ValueError, ValidationError) as e:
        msg = (
            "; ".join(x["msg"] for x in e.errors()[:3])
            if isinstance(e, ValidationError)
            else str(e)
        )
        return wrap_untrusted(name, json.dumps({"error": f"invalid arguments: {clean(msg, 200)}"}))
    result = await tool.fn(ctx, args)
    return wrap_untrusted(name, _cap(result))
