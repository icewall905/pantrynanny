"""Inventory: the transactional heart of PantryNanny.

All stock changes go through :func:`apply_op` (one operation = one DB transaction, serialised
per product with ``SELECT ... FOR UPDATE``). Quantities are never overwritten; every change is an
append-only ``StockTransaction`` plus per-batch ``StockTransactionLine`` rows so undo can reverse
exactly what happened.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import case, func, select, tuple_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import DataError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..errors import not_found
from ..logging import get_logger
from ..models import (
    Category,
    HouseholdSettings,
    Location,
    Product,
    ShoppingItem,
    StockBatch,
    StockTransaction,
    StockTransactionLine,
)
from ..schemas.common import MAX_OP_QTY as MAX_OP_QTY_INT
from ..schemas.inventory import SyncOp
from ..security import Principal
from .barcodes import normalize
from .households import get_household_settings
from .products import MAX_BARCODE_LEN, get_or_create_placeholder, get_product, search_score

log = get_logger()
ZERO = Decimal(0)
MAX_ATTEMPTS = 4
MAX_MERGE_HOPS = 5
MAX_OP_QTY = Decimal(MAX_OP_QTY_INT)
# Per-batch ceiling, comfortably below NUMERIC(12,3) so sums can never overflow the column.
MAX_BATCH_QTY = Decimal(100_000_000)


class OpRejected(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class RetryOp(Exception):
    """Raised when a concurrent change invalidated what the op resolved; the op is re-run."""


@dataclass(slots=True)
class OpResult:
    client_op_id: uuid.UUID
    status: str  # applied | duplicate | rejected
    error: str | None = None
    error_code: str | None = None
    transaction_id: uuid.UUID | None = None
    product: Product | None = None
    total_quantity: Decimal | None = None


# --------------------------------------------------------------------------- helpers


async def product_total(session: AsyncSession, product_id: uuid.UUID) -> Decimal:
    total = await session.scalar(
        select(func.coalesce(func.sum(StockBatch.quantity), 0)).where(
            StockBatch.product_id == product_id
        )
    )
    return Decimal(total or 0)


async def _find_txn(
    session: AsyncSession, household_id: uuid.UUID, client_op_id: uuid.UUID, *, lock: bool = False
) -> StockTransaction | None:
    stmt = select(StockTransaction).where(
        StockTransaction.household_id == household_id,
        StockTransaction.client_op_id == client_op_id,
    )
    if lock:
        stmt = stmt.with_for_update(of=StockTransaction).execution_options(populate_existing=True)
    return (await session.execute(stmt)).scalar_one_or_none()


async def _duplicate_result(session: AsyncSession, txn: StockTransaction) -> OpResult:
    product = await get_product(
        session, txn.household_id, txn.product_id, include_deleted=True, refresh=True
    )
    return OpResult(
        client_op_id=txn.client_op_id,
        status="duplicate",
        error=txn.op_error,
        error_code=txn.op_error,
        transaction_id=txn.id,
        product=product,
        total_quantity=await product_total(session, txn.product_id),
    )


async def _resolve_location(
    session: AsyncSession,
    household_id: uuid.UUID,
    requested: uuid.UUID | None,
    product: Product,
    *,
    fallback_if_deleted: bool = True,
) -> Location:
    """Pick the location for an op: requested -> product default -> household default.

    The chosen row is locked FOR SHARE so a concurrent location delete waits for this op.
    A requested location that was soft-deleted after the op was queued (offline device) falls
    back to the defaults instead of dropping the scan; unknown/foreign ids are rejected.
    """

    async def fetch(loc_id: uuid.UUID, *, deleted_ok: bool = False) -> Location | None:
        stmt = select(Location).where(Location.id == loc_id, Location.household_id == household_id)
        if not deleted_ok:
            stmt = stmt.where(Location.deleted_at.is_(None))
        stmt = stmt.with_for_update(read=True, of=Location)
        return (await session.execute(stmt)).scalar_one_or_none()

    if requested is not None:
        loc = await fetch(requested, deleted_ok=True)
        if loc is None:
            raise OpRejected("location_not_found", "Unknown location")
        if loc.deleted_at is None:
            return loc
        if not fallback_if_deleted:
            raise OpRejected("location_not_found", "Location has been deleted")
    if product.default_location_id:
        loc = await fetch(product.default_location_id)
        if loc:
            return loc
    stmt = (
        select(Location)
        .where(Location.household_id == household_id, Location.deleted_at.is_(None))
        .order_by(Location.is_default.desc(), Location.sort_order, Location.created_at)
        .limit(1)
        .with_for_update(read=True, of=Location)
    )
    loc = (await session.execute(stmt)).scalar_one_or_none()
    if loc is None:
        raise OpRejected("no_location", "Household has no locations")
    return loc


def _learn_location(product: Product, location_id: uuid.UUID | None) -> None:
    """Remember where this product lives, so the next scan without a location goes there."""
    if location_id is not None and product.default_location_id != location_id:
        product.default_location_id = location_id
        product.version += 1


async def _find_or_create_batch(
    session: AsyncSession,
    product: Product,
    location_id: uuid.UUID,
    expires_at: date | None,
    opened_at: date | None = None,
) -> StockBatch:
    stmt = (
        select(StockBatch)
        .where(
            StockBatch.product_id == product.id,
            StockBatch.location_id == location_id,
            StockBatch.expires_at.is_not_distinct_from(expires_at),
        )
        .order_by(StockBatch.created_at)
        .limit(1)
    )
    batch = (await session.execute(stmt)).scalar_one_or_none()
    if batch is None:
        batch = StockBatch(
            household_id=product.household_id,
            product_id=product.id,
            location_id=location_id,
            quantity=ZERO,
            expires_at=expires_at,
            opened_at=opened_at,
        )
        session.add(batch)
        await session.flush()
    return batch


async def _fifo_batches(
    session: AsyncSession,
    product: Product,
    prefer_location: uuid.UUID | None,
    *,
    only_location: uuid.UUID | None = None,
    exclude_location: uuid.UUID | None = None,
) -> list[StockBatch]:
    stmt = select(StockBatch).where(StockBatch.product_id == product.id, StockBatch.quantity > 0)
    if only_location:
        stmt = stmt.where(StockBatch.location_id == only_location)
    if exclude_location:
        stmt = stmt.where(StockBatch.location_id != exclude_location)
    order = []
    if prefer_location:
        order.append(case((StockBatch.location_id == prefer_location, 0), else_=1))
    order += [StockBatch.expires_at.asc().nulls_last(), StockBatch.created_at, StockBatch.id]
    stmt = stmt.order_by(*order).with_for_update().execution_options(populate_existing=True)
    return list((await session.execute(stmt)).scalars().all())


@dataclass(slots=True)
class _Effect:
    lines: list[tuple[StockBatch, Decimal]]
    clamped: bool = False


async def _add_stock(
    session: AsyncSession,
    product: Product,
    location_id: uuid.UUID,
    qty: Decimal,
    expires_at: date | None,
) -> _Effect:
    batch = await _find_or_create_batch(session, product, location_id, expires_at)
    if batch.quantity + qty > MAX_BATCH_QTY:
        raise OpRejected("invalid_quantity", "Resulting stock quantity is too large")
    batch.quantity = batch.quantity + qty
    return _Effect([(batch, qty)])


async def _remove_stock(
    session: AsyncSession,
    product: Product,
    location_id: uuid.UUID,
    qty: Decimal,
    allow_negative: bool,
) -> _Effect:
    lines: list[tuple[StockBatch, Decimal]] = []
    remaining = qty
    for batch in await _fifo_batches(session, product, location_id):
        if remaining <= 0:
            break
        take = min(batch.quantity, remaining)
        batch.quantity = batch.quantity - take
        lines.append((batch, -take))
        remaining -= take
    clamped = False
    if remaining > 0:
        if allow_negative:
            batch = await _find_or_create_batch(session, product, location_id, None)
            if batch.quantity - remaining < -MAX_BATCH_QTY:
                raise OpRejected("invalid_quantity", "Resulting stock quantity is too small")
            batch.quantity = batch.quantity - remaining
            lines.append((batch, -remaining))
        else:
            clamped = True
    return _Effect(lines, clamped)


async def _move_stock(
    session: AsyncSession,
    product: Product,
    source: uuid.UUID | None,
    dest: uuid.UUID,
    qty: Decimal,
) -> tuple[_Effect, Decimal]:
    lines: list[tuple[StockBatch, Decimal]] = []
    remaining = qty
    batches = await _fifo_batches(
        session, product, None, only_location=source, exclude_location=dest
    )
    for batch in batches:
        if remaining <= 0:
            break
        take = min(batch.quantity, remaining)
        batch.quantity = batch.quantity - take
        lines.append((batch, -take))
        target = await _find_or_create_batch(
            session, product, dest, batch.expires_at, batch.opened_at
        )
        if target.quantity + take > MAX_BATCH_QTY:
            raise OpRejected("invalid_quantity", "Resulting stock quantity is too large")
        target.quantity = target.quantity + take
        lines.append((target, take))
        remaining -= take
    return _Effect(lines, clamped=remaining > 0), qty - remaining


async def _locked_batch(session: AsyncSession, batch_id: uuid.UUID) -> StockBatch:
    return (
        await session.execute(
            select(StockBatch)
            .where(StockBatch.id == batch_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one()


async def _reverse(
    session: AsyncSession, original: StockTransaction, allow_negative: bool
) -> _Effect:
    """Apply the exact inverse of ``original``'s lines (clamped so batches never go negative)."""
    lines: list[tuple[StockBatch, Decimal]] = []
    clamped = False
    if original.type == "move":
        # Lines come in (source -t, destination +t) pairs.
        pairs = zip(original.lines[0::2], original.lines[1::2], strict=True)
        for src_line, dst_line in pairs:
            dst = await _locked_batch(session, dst_line.batch_id)
            src = await _locked_batch(session, src_line.batch_id)
            amount = dst_line.delta
            if not allow_negative and dst.quantity < amount:
                amount = max(dst.quantity, ZERO)
                clamped = True
            if amount == 0:
                continue
            dst.quantity = dst.quantity - amount
            src.quantity = src.quantity + amount
            lines += [(src, amount), (dst, -amount)]
        return _Effect(lines, clamped)
    for line in reversed(original.lines):
        batch = await _locked_batch(session, line.batch_id)
        delta = -line.delta
        if delta < 0 and not allow_negative and batch.quantity + delta < 0:
            delta = -max(batch.quantity, ZERO)
            clamped = True
        if delta == 0:
            continue
        batch.quantity = batch.quantity + delta
        lines.append((batch, delta))
    return _Effect(lines, clamped)


async def _maybe_add_low_stock(
    session: AsyncSession,
    settings: HouseholdSettings,
    product: Product,
    total: Decimal,
) -> None:
    if (
        not settings.auto_shopping_low_stock
        or product.min_stock is None
        or total >= product.min_stock
    ):
        return
    stmt = (
        insert(ShoppingItem)
        .values(
            household_id=product.household_id,
            product_id=product.id,
            name=product.name,
            quantity=max(product.min_stock - total, Decimal(1)),
            unit=product.stock_unit,
            category_id=product.category_id,
            source="low_stock",
        )
        .on_conflict_do_nothing()
    )
    await session.execute(stmt)


# --------------------------------------------------------------------------- apply_op


async def _resolve_product(
    session: AsyncSession, principal: Principal, op: SyncOp
) -> tuple[Product, StockTransaction | None]:
    """Return the (row-locked) target product and, for undo, the original transaction."""
    hh = principal.household_id
    original: StockTransaction | None = None
    if op.type == "undo":
        if op.undoes_client_op_id is None:
            raise OpRejected("missing_target", "undoes_client_op_id is required for undo")
        original = await _find_txn(session, hh, op.undoes_client_op_id)
        if original is None:
            raise OpRejected("not_found", "Original operation not found")
        pid = original.product_id
    nb = None
    if op.barcode and len(op.barcode) > MAX_BARCODE_LEN:
        raise OpRejected("invalid_barcode", "Barcode too long")
    if op.barcode:
        try:
            nb = normalize(op.barcode, op.symbology)
        except ValueError:
            nb = None
    if op.type == "undo":
        pass
    elif op.product_id is not None:
        pid = op.product_id
    elif nb is not None:
        found, _ = await get_or_create_placeholder(session, hh, nb)
        pid = found.id
    else:
        raise OpRejected("missing_target", "Operation needs product_id or a non-blank barcode")

    hops = 0
    tried_barcode = op.product_id is None
    while True:
        stmt = (
            select(Product)
            .where(Product.id == pid, Product.household_id == hh)
            .with_for_update(of=Product)
            .execution_options(populate_existing=True)
        )
        product = (await session.execute(stmt)).scalar_one_or_none()
        if product is None:
            raise OpRejected("product_not_found", "Unknown product")
        if product.deleted_at is None or op.type == "undo":
            break
        # Deleted product: an offline device may still reference a placeholder that was merged.
        if product.merged_into_id is not None and hops < MAX_MERGE_HOPS:
            pid = product.merged_into_id
            hops += 1
        elif nb is not None and not tried_barcode:
            tried_barcode = True
            found, _ = await get_or_create_placeholder(session, hh, nb)
            pid = found.id
        elif op.product_id is None and op.type != "undo":
            raise RetryOp  # barcode-resolved product was deleted before we locked it; re-resolve
        else:
            raise OpRejected("product_not_found", "Product has been deleted")
    return product, original


async def apply_op(
    session: AsyncSession,
    principal: Principal,
    op: SyncOp,
    device_id: str | None = None,
) -> OpResult:
    """Apply one operation inside the caller's (fresh) transaction. Does not commit."""
    hh = principal.household_id
    existing = await _find_txn(session, hh, op.client_op_id)
    if existing:
        return await _duplicate_result(session, existing)

    qty = op.quantity
    if qty is not None and (
        not qty.is_finite() or abs(qty) > MAX_OP_QTY or qty.as_tuple().exponent < -3
    ):
        raise OpRejected(
            "invalid_quantity", f"quantity must be within +/-{MAX_OP_QTY} with at most 3 decimals"
        )
    if op.type in ("add", "remove", "move"):
        if qty is None or qty <= 0:
            raise OpRejected("invalid_quantity", "quantity must be greater than zero")
    elif op.type == "adjust" and (qty is None or qty == 0):
        raise OpRejected("invalid_quantity", "adjust needs a non-zero signed quantity")
    if op.type == "move" and op.to_location_id is None:
        raise OpRejected("missing_target", "move needs to_location_id")

    product, original = await _resolve_product(session, principal, op)
    existing = await _find_txn(session, hh, op.client_op_id)
    if existing:
        return await _duplicate_result(session, existing)

    settings = await get_household_settings(session, hh)
    allow_neg = settings.allow_negative_stock
    effect: _Effect
    delta: Decimal
    location_id: uuid.UUID | None
    to_location_id: uuid.UUID | None = None
    undoes_id: uuid.UUID | None = None

    if op.type == "undo":
        assert original is not None
        original = await _find_txn(session, hh, original.client_op_id, lock=True)
        assert original is not None
        if original.type == "undo":
            raise OpRejected("cannot_undo_undo", "An undo cannot be undone")
        if original.undone:
            raise OpRejected("already_undone", "Operation was already undone")
        effect = await _reverse(session, original, allow_neg)
        if original.type == "move":
            delta = sum((d for _, d in effect.lines if d > 0), ZERO)  # amount actually moved back
        else:
            delta = sum((d for _, d in effect.lines), ZERO)  # actual (possibly clamped) effect
        location_id = original.to_location_id if original.type == "move" else original.location_id
        to_location_id = original.location_id if original.type == "move" else None
        undoes_id = original.id
        original.undone = True
        if original.type == "move" and product.default_location_id == original.to_location_id:
            _learn_location(product, original.location_id)  # the move is taken back
    elif op.type == "move":
        assert qty is not None and op.to_location_id is not None
        dest = await _resolve_location(
            session, hh, op.to_location_id, product, fallback_if_deleted=False
        )
        src_id: uuid.UUID | None = None
        if op.location_id is not None:
            src_id = (await _resolve_location(session, hh, op.location_id, product)).id
            if src_id == dest.id:
                raise OpRejected("invalid_move", "Source and destination are the same")
        effect, delta = await _move_stock(session, product, src_id, dest.id, qty)
        first_src = next((b.location_id for b, d in effect.lines if d < 0), src_id)
        location_id, to_location_id = first_src, dest.id
        if delta > 0:
            _learn_location(product, dest.id)  # moved it: that is where it belongs now
    else:
        loc = await _resolve_location(session, hh, op.location_id, product)
        location_id = loc.id
        if op.type == "add" and op.location_id == loc.id and product.default_location_id is None:
            _learn_location(product, loc.id)  # first time it was put somewhere on purpose
        assert qty is not None
        signed = qty if op.type == "add" else (-qty if op.type == "remove" else qty)
        if signed > 0:
            effect = await _add_stock(session, product, loc.id, signed, op.expires_at)
            delta = signed
        else:
            effect = await _remove_stock(session, product, loc.id, -signed, allow_neg)
            delta = sum((d for _, d in effect.lines), ZERO)

    occurred = op.occurred_at or datetime.now(UTC)
    if occurred.tzinfo is None:
        occurred = occurred.replace(tzinfo=UTC)
    txn = StockTransaction(
        household_id=hh,
        client_op_id=op.client_op_id,
        type=op.type,
        quantity_delta=delta,
        product_id=product.id,
        batch_id=effect.lines[0][0].id if effect.lines else None,
        location_id=location_id,
        to_location_id=to_location_id,
        undoes_id=undoes_id,
        user_id=principal.user_id,
        session_id=principal.session_id,
        device_name=principal.device_name,
        device_id=device_id,
        reason=op.reason,
        op_error="clamped" if effect.clamped else None,
        occurred_at=occurred,
        lines=[],
    )
    session.add(txn)
    await session.flush()
    for seq, (batch, d) in enumerate(effect.lines):
        session.add(
            StockTransactionLine(transaction_id=txn.id, batch_id=batch.id, seq=seq, delta=d)
        )
    await session.flush()

    total = await product_total(session, product.id)
    net_change = sum((d for _, d in effect.lines), ZERO)
    if net_change < 0:
        await _maybe_add_low_stock(session, settings, product, total)
    return OpResult(
        client_op_id=op.client_op_id,
        status="applied",
        error="clamped" if effect.clamped else None,
        error_code="clamped" if effect.clamped else None,
        transaction_id=txn.id,
        product=product,
        total_quantity=total,
    )


async def process_op(
    sm: async_sessionmaker[AsyncSession],
    principal: Principal,
    op: SyncOp,
    device_id: str | None = None,
) -> OpResult:
    """Run :func:`apply_op` in its own transaction, handling idempotent races and rejections."""
    for _ in range(MAX_ATTEMPTS):
        try:
            async with sm() as session, session.begin():
                return await apply_op(session, principal, op, device_id)
        except OpRejected as exc:
            return OpResult(op.client_op_id, "rejected", exc.message, exc.code)
        except (DataError, ArithmeticError, ValueError):
            # Anything the DB/decimal layer refuses: reject this one op, never fail the batch.
            # (Quantity range/precision problems are caught earlier as `invalid_quantity`.)
            return OpResult(op.client_op_id, "rejected", "Invalid operation", "invalid_op")
        except (IntegrityError, RetryOp):
            # Either a concurrent identical op won the unique(client_op_id) race, or a barcode
            # placeholder was created concurrently. Re-run: the dedupe check will catch the former.
            continue
    return OpResult(op.client_op_id, "rejected", "Operation conflicted repeatedly", "conflict")


# --------------------------------------------------------------------------- queries


@dataclass(slots=True)
class StockView:
    product: Product
    total: Decimal  # over the (possibly location-filtered) batches
    batches: list[StockBatch]
    next_expiry: date | None
    low_stock: bool


async def batches_for(
    session: AsyncSession, household_id: uuid.UUID, product_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[StockBatch]]:
    out: dict[uuid.UUID, list[StockBatch]] = {pid: [] for pid in product_ids}
    if not product_ids:
        return out
    rows = await session.execute(
        select(StockBatch)
        .where(
            StockBatch.household_id == household_id,
            StockBatch.product_id.in_(product_ids),
            StockBatch.quantity != 0,
        )
        .order_by(StockBatch.expires_at.asc().nulls_last(), StockBatch.created_at)
    )
    for b in rows.scalars():
        out[b.product_id].append(b)
    return out


def build_view(
    product: Product, batches: list[StockBatch], location_id: uuid.UUID | None = None
) -> StockView:
    overall = sum((b.quantity for b in batches), ZERO)
    shown = [b for b in batches if location_id is None or b.location_id == location_id]
    total = sum((b.quantity for b in shown), ZERO)
    expiries = [b.expires_at for b in shown if b.expires_at and b.quantity > 0]
    return StockView(
        product=product,
        total=total,
        batches=shown,
        next_expiry=min(expiries) if expiries else None,
        low_stock=product.min_stock is not None and overall < product.min_stock,
    )


async def list_inventory(
    session: AsyncSession,
    household_id: uuid.UUID,
    *,
    location_id: uuid.UUID | None = None,
    category_id: uuid.UUID | None = None,
    q: str | None = None,
    sort: str = "name",
    include_empty: bool = False,
) -> list[StockView]:
    stmt = (
        select(Product)
        .outerjoin(Category, Category.id == Product.category_id)
        .where(Product.household_id == household_id, Product.deleted_at.is_(None))
    )
    if category_id:
        stmt = stmt.where(Product.category_id == category_id)
    scored = search_score(q) if q else None
    if scored:
        stmt = stmt.where(scored[1])
    products = list((await session.execute(stmt)).scalars().all())
    batches = await batches_for(session, household_id, [p.id for p in products])
    views = [build_view(p, batches[p.id], location_id) for p in products]
    if not include_empty:
        views = [v for v in views if any(b.quantity > 0 for b in v.batches)]
    if sort == "quantity":
        views.sort(key=lambda v: (-v.total, v.product.name.lower()))
    elif sort == "expiry":
        views.sort(
            key=lambda v: (v.next_expiry is None, v.next_expiry or date.max, v.product.name.lower())
        )
    elif sort == "updated":
        views.sort(
            key=lambda v: max([v.product.updated_at, *[b.updated_at for b in v.batches]]),
            reverse=True,
        )
    else:
        views.sort(key=lambda v: v.product.name.lower())
    return views


async def get_inventory_item(
    session: AsyncSession, household_id: uuid.UUID, product_id: uuid.UUID
) -> StockView:
    product = await get_product(session, household_id, product_id)
    batches = await batches_for(session, household_id, [product.id])
    return build_view(product, batches[product.id])


async def recent_transactions(
    session: AsyncSession,
    household_id: uuid.UUID,
    *,
    product_id: uuid.UUID | None = None,
    limit: int = 50,
    before: tuple[datetime, uuid.UUID | None] | None = None,
    types: tuple[str, ...] | None = None,
) -> list[StockTransaction]:
    stmt = select(StockTransaction).where(StockTransaction.household_id == household_id)
    if product_id:
        stmt = stmt.where(StockTransaction.product_id == product_id)
    if before:
        ts, tid = before
        if tid is None:
            stmt = stmt.where(StockTransaction.created_at < ts)
        else:  # composite keyset cursor: ties on created_at are broken by id
            stmt = stmt.where(
                tuple_(StockTransaction.created_at, StockTransaction.id) < tuple_(ts, tid)
            )
    if types:
        stmt = stmt.where(StockTransaction.type.in_(types))
    stmt = stmt.order_by(StockTransaction.created_at.desc(), StockTransaction.id.desc()).limit(
        limit
    )
    return list((await session.execute(stmt)).scalars().all())


async def update_batch_meta(
    session: AsyncSession,
    household_id: uuid.UUID,
    batch_id: uuid.UUID,
    fields: dict[str, date | None],
) -> StockBatch:
    batch = (
        await session.execute(
            select(StockBatch)
            .where(StockBatch.id == batch_id, StockBatch.household_id == household_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if batch is None:
        raise not_found("Batch not found")
    for key, value in fields.items():
        setattr(batch, key, value)
    await session.flush()
    await session.refresh(batch)
    return batch
