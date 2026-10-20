"""Product catalogue: serialisation, search, creation, optimistic edits, barcodes, merge."""

import asyncio
import re
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    Select,
    and_,
    bindparam,
    case,
    delete,
    exists,
    func,
    literal,
    or_,
    select,
    text,
    update,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.sql.elements import ColumnElement

from ..errors import AppError, conflict, not_found
from ..logging import get_logger
from ..models import (
    Category,
    EnrichmentQueue,
    Location,
    Product,
    ProductAlias,
    ProductBarcode,
    ShoppingItem,
    StockBatch,
    StockTransaction,
)
from ..schemas.catalogue import BarcodeOut, ProductCreate, ProductOut, ProductPatch
from .barcodes import NormalizedBarcode, normalize, strip_barcode
from .lookup import (
    ProductData,
    enqueue_enrichment,
    lookup_external,
    new_product_from_data,
    seed_data,
)

log = get_logger()

MAX_BARCODE_LEN = 200
UNITS = {"pcs", "pkg", "g", "kg", "ml", "cl", "dl", "l"}
PATCH_COLUMNS = (
    "name",
    "brand",
    "category_id",
    "default_location_id",
    "package_size",
    "package_unit",
    "stock_unit",
    "min_stock",
    "ingredients",
    "allergens",
    "nutrition",
    "description",
    "countries",
)
NOT_NULLABLE = {"name", "stock_unit", "allergens", "countries"}


def normalize_input(raw: str, symbology: str | None = None) -> NormalizedBarcode:
    """normalize() for user-supplied codes: blank / oversized values are a 422, never a 500."""
    cleaned = strip_barcode(raw or "")
    if not cleaned:
        raise AppError(422, "invalid_barcode", "Barcode must not be blank")
    if len(cleaned) > MAX_BARCODE_LEN:
        raise AppError(422, "invalid_barcode", f"Barcode longer than {MAX_BARCODE_LEN} characters")
    return normalize(raw, symbology)


def product_out(p: Product) -> ProductOut:
    return ProductOut(
        id=p.id,
        version=p.version,
        name=p.name,
        brand=p.brand,
        category_id=p.category_id,
        default_location_id=p.default_location_id,
        image_url=f"/api/media/{p.image_path}" if p.image_path else None,
        package_size=p.package_size,
        package_unit=p.package_unit,
        stock_unit=p.stock_unit,
        min_stock=p.min_stock,
        ingredients=p.ingredients,
        allergens=list(p.allergens or []),
        nutrition=p.nutrition,
        description=p.description,
        countries=list(p.countries or []),
        barcodes=[BarcodeOut(code=b.code, raw=b.raw, symbology=b.symbology) for b in p.barcodes],
        aliases=[a.alias for a in p.aliases],
        status=p.status,
        source=p.source,
        source_attribution=p.source_attribution,
        lookup_confidence=p.lookup_confidence,
        locked_fields=list(p.locked_fields or []),
        favorite=bool(p.favorite),
        created_at=p.created_at,
        updated_at=p.updated_at,
        deleted_at=p.deleted_at,
    )


# --------------------------------------------------------------------------- loading


async def get_product(
    session: AsyncSession,
    household_id: uuid.UUID,
    product_id: uuid.UUID,
    *,
    for_update: bool = False,
    include_deleted: bool = False,
    refresh: bool = False,
) -> Product:
    stmt = select(Product).where(Product.id == product_id, Product.household_id == household_id)
    if not include_deleted:
        stmt = stmt.where(Product.deleted_at.is_(None))
    if for_update:
        stmt = stmt.with_for_update(of=Product)
    if refresh or for_update:
        stmt = stmt.execution_options(populate_existing=True)
    p = (await session.execute(stmt)).scalar_one_or_none()
    if p is None:
        raise not_found("Product not found")
    return p


async def find_by_code(session: AsyncSession, household_id: uuid.UUID, code: str) -> Product | None:
    stmt = (
        select(Product)
        .join(ProductBarcode, ProductBarcode.product_id == Product.id)
        .where(
            ProductBarcode.household_id == household_id,
            ProductBarcode.code == code,
            Product.deleted_at.is_(None),
        )
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def _assert_refs(
    session: AsyncSession,
    household_id: uuid.UUID,
    category_id: uuid.UUID | None,
    location_id: uuid.UUID | None,
) -> None:
    if category_id is not None:
        ok = await session.scalar(
            select(Category.id).where(
                Category.id == category_id,
                Category.household_id == household_id,
                Category.deleted_at.is_(None),
            )
        )
        if ok is None:
            raise AppError(422, "category_not_found", "Unknown category")
    if location_id is not None:
        ok = await session.scalar(
            select(Location.id).where(
                Location.id == location_id,
                Location.household_id == household_id,
                Location.deleted_at.is_(None),
            )
        )
        if ok is None:
            raise AppError(422, "location_not_found", "Unknown location")


def _clean_aliases(aliases: list[str], name: str) -> list[str]:
    out: dict[str, str] = {}
    for a in aliases:
        a = a.strip()
        if a and a.lower() != name.lower():
            out.setdefault(a.lower(), a[:200])
    return list(out.values())


# --------------------------------------------------------------------------- search

_TOKEN_STRIP = re.compile(r"[%_\\]")


def _nx(expr: Any) -> ColumnElement:
    return func.pn_unaccent(func.lower(expr))


def _text_score(col: ColumnElement, tq: ColumnElement, weight: float) -> ColumnElement:
    """0 when no match; otherwise a relevance in (0, weight]."""
    sim = func.similarity(col, tq)
    wsim = func.word_similarity(tq, col)
    exact = case(
        (col == tq, 1.0),
        (col.like(func.concat(tq, "%")), 0.9),
        (col.like(func.concat("%", tq, "%")), 0.75),
        else_=0.0,
    )
    fuzzy = case((sim >= 0.3, sim), else_=0.0)
    wfuzzy = case((wsim >= 0.5, wsim * 0.8), else_=0.0)
    return func.greatest(exact, fuzzy, wfuzzy) * weight


def search_score(q: str) -> tuple[ColumnElement, ColumnElement] | None:
    """Return ``(score, matches)`` over Product + outer-joined Category, or None for empty q.

    Every whitespace separated token must match name, brand, an alias, the category name or a
    barcode (unaccented, case-insensitive substring or trigram similarity).
    """
    tokens = [t for t in (_TOKEN_STRIP.sub("", t) for t in q.split()) if t][:8]
    if not tokens:
        return None
    scores: list[ColumnElement] = []
    for i, tok in enumerate(tokens):
        tq = _nx(bindparam(f"tok{i}", tok))
        alias_score = (
            select(func.max(_text_score(_nx(ProductAlias.alias), tq, 0.85)))
            .where(ProductAlias.product_id == Product.id)
            .scalar_subquery()
        )
        parts = [
            _text_score(_nx(Product.name), tq, 1.0),
            _text_score(_nx(func.coalesce(Product.brand, "")), tq, 0.6),
            _text_score(_nx(func.coalesce(Category.name, "")), tq, 0.4),
            func.coalesce(alias_score, 0.0),
        ]
        if tok.isascii() and tok.isdigit() and len(tok) >= 3:
            code_hit = exists().where(
                ProductBarcode.product_id == Product.id,
                or_(
                    ProductBarcode.code.like(literal(tok) + "%"),
                    ProductBarcode.raw.like(literal(tok) + "%"),
                    ProductBarcode.code.like("%" + literal(tok)),
                ),
            )
            parts.append(case((code_hit, 1.0), else_=0.0))
        scores.append(func.greatest(*parts))
    total = scores[0]
    for s in scores[1:]:
        total = total + s
    avg = total / len(scores)
    matches = and_(*[s > 0 for s in scores])
    return avg, matches


async def list_products(
    session: AsyncSession,
    household_id: uuid.UUID,
    *,
    q: str | None,
    status: str | None,
    category_id: uuid.UUID | None,
    limit: int,
    offset: int,
) -> list[Product]:
    stmt: Select = (
        select(Product)
        .outerjoin(Category, Category.id == Product.category_id)
        .where(Product.household_id == household_id, Product.deleted_at.is_(None))
    )
    if status:
        stmt = stmt.where(Product.status == status)
    if category_id:
        stmt = stmt.where(Product.category_id == category_id)
    scored = search_score(q) if q else None
    if scored:
        score, matches = scored
        stmt = stmt.where(matches).order_by(
            score.desc(), func.lower(Product.name), Product.created_at, Product.id
        )
    else:
        stmt = stmt.order_by(func.lower(Product.name), Product.created_at, Product.id)
    stmt = stmt.limit(limit).offset(offset)
    return list((await session.execute(stmt)).scalars().all())


# --------------------------------------------------------------------------- creation


def _new_barcode(p: Product, nb: NormalizedBarcode) -> ProductBarcode:
    return ProductBarcode(
        household_id=p.household_id,
        code=nb.code,
        raw=nb.raw,
        symbology=nb.symbology,
    )


async def create_placeholder(
    session: AsyncSession, household_id: uuid.UUID, nb: NormalizedBarcode
) -> Product:
    """Insert an ``unknown`` placeholder for a never-seen barcode and queue enrichment."""
    p = Product(
        household_id=household_id,
        name=f"Ukendt vare {nb.raw}"[:200],
        status="unknown",
        source="placeholder",
        barcodes=[],
        aliases=[],
        allergens=[],
        countries=[],
        locked_fields=[],
    )
    p.barcodes.append(_new_barcode(p, nb))
    session.add(p)
    await session.flush()
    await enqueue_enrichment(session, p)
    return p


async def lock_code(session: AsyncSession, household_id: uuid.UUID, code: str) -> None:
    """Serialise creators of the same barcode in one household for this transaction.

    Two devices scanning the same new barcode at once would otherwise both insert it. The
    savepoints below still catch that, but the losing INSERT is logged by PostgreSQL as an
    ERROR, which buries real errors in the log."""
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"),
        {"k": f"pn-barcode:{household_id}:{code}"},
    )


async def get_or_create_placeholder(
    session: AsyncSession, household_id: uuid.UUID, nb: NormalizedBarcode
) -> tuple[Product, bool]:
    """Find the product for ``nb``, else create it from the local seed catalogue, else create a
    placeholder. Race-safe via a savepoint. The seed check is a primary-key read (no network), so
    scans arriving through ``/sync/ops`` (Android, offline queue) are recognised immediately too."""
    p = await find_by_code(session, household_id, nb.code)
    if p:
        return p, False
    await lock_code(session, household_id, nb.code)
    p = await find_by_code(session, household_id, nb.code)  # created while we waited
    if p:
        return p, False
    data = await seed_data(session, nb.code)
    try:
        async with session.begin_nested():
            if data is not None:
                p = await new_product_from_data(session, household_id, data)
                p.barcodes.append(_new_barcode(p, nb))
                session.add(p)
                await session.flush()
            else:
                p = await create_placeholder(session, household_id, nb)
        return p, True
    except IntegrityError:
        p = await find_by_code(session, household_id, nb.code)
        if p is None:
            raise
        return p, False


async def resolve_barcode(
    session: AsyncSession,
    sm: async_sessionmaker[AsyncSession],
    household_id: uuid.UUID,
    raw: str,
    symbology: str | None,
    *,
    lookup: bool,
    timeout_s: float,
) -> tuple[str, Product | None, str | None, NormalizedBarcode]:
    """Backs ``GET /products/by-barcode``. Never touches stock."""
    nb = normalize_input(raw, symbology)
    p = await find_by_code(session, household_id, nb.code)
    if p:
        return "found", p, p.source, nb
    if not lookup:
        return "not_found", None, None, nb

    data: ProductData | None = None
    try:
        # Own session so a timeout cancellation cannot leave the request session mid-statement.
        async with sm() as lookup_session:
            data = await asyncio.wait_for(
                lookup_external(lookup_session, household_id, nb.code, nb.symbology),
                timeout=timeout_s,
            )
    except TimeoutError:
        log.warning("lookup_timeout", code=nb.code)
    except Exception:
        log.exception("lookup_failed", code=nb.code)

    if data is not None:
        await lock_code(session, household_id, nb.code)
        p = await find_by_code(session, household_id, nb.code)  # created during the lookup?
        if p is not None:
            await session.commit()
            return (
                "found",
                await get_product(session, household_id, p.id, refresh=True),
                p.source,
                nb,
            )
        try:
            async with session.begin_nested():
                p = await new_product_from_data(session, household_id, data)
                p.barcodes.append(_new_barcode(p, nb))
                session.add(p)
                await session.flush()
                if data.image_url:  # the worker downloads the image outside the scan request
                    await enqueue_enrichment(session, p)
        except IntegrityError:
            p = await find_by_code(session, household_id, nb.code)
        if p is not None:
            await session.commit()
            return (
                "found",
                await get_product(session, household_id, p.id, refresh=True),
                (data.source),
                nb,
            )

    p, created = await get_or_create_placeholder(session, household_id, nb)
    await session.commit()
    p = await get_product(session, household_id, p.id, refresh=True)
    return ("created_placeholder" if created else "found"), p, p.source, nb


async def create_product(
    session: AsyncSession, household_id: uuid.UUID, body: ProductCreate
) -> Product:
    await _assert_refs(session, household_id, body.category_id, body.default_location_id)
    norm: dict[str, NormalizedBarcode] = {}
    for raw in body.barcodes:
        nb = normalize_input(raw, body.symbology if len(body.barcodes) == 1 else None)
        norm.setdefault(nb.code, nb)
    for nb in norm.values():
        existing = await find_by_code(session, household_id, nb.code)
        if existing:
            raise conflict(
                "barcode_exists",
                "Barcode already belongs to another product",
                product_id=str(existing.id),
            )
    p = Product(
        household_id=household_id,
        **body.model_dump(
            exclude={"barcodes", "symbology", "aliases", "status"},
        ),
        status=body.status,
        source="user",
        barcodes=[],
        aliases=[],
        locked_fields=[],
    )
    for nb in norm.values():
        p.barcodes.append(_new_barcode(p, nb))
    for alias in _clean_aliases(body.aliases, body.name):
        p.aliases.append(ProductAlias(household_id=household_id, alias=alias))
    session.add(p)
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise conflict("barcode_exists", "Barcode already belongs to another product") from exc
    return p


# --------------------------------------------------------------------------- edits


async def patch_product(
    session: AsyncSession,
    household_id: uuid.UUID,
    product_id: uuid.UUID,
    patch: ProductPatch,
    if_match: int,
) -> Product:
    p = await get_product(session, household_id, product_id, for_update=True)
    if p.version != if_match:
        raise conflict(
            "version_conflict",
            "Product was modified by someone else",
            product=product_out(p).model_dump(mode="json"),
        )
    sent = patch.model_fields_set
    for field in sent & NOT_NULLABLE:
        if getattr(patch, field) is None:
            raise AppError(422, "validation_error", f"{field} cannot be null")
    if "category_id" in sent or "default_location_id" in sent:
        await _assert_refs(
            session,
            household_id,
            patch.category_id if "category_id" in sent else None,
            patch.default_location_id if "default_location_id" in sent else None,
        )
    locked = set(p.locked_fields or [])
    changed: set[str] = set()
    for field in PATCH_COLUMNS:
        # The web client submits whole forms: only fields whose value really changed are
        # written and locked against provider refreshes.
        if field in sent and getattr(p, field) != getattr(patch, field):
            setattr(p, field, getattr(patch, field))
            locked.add(field)
            changed.add(field)
    if "aliases" in sent and patch.aliases is not None:
        wanted = _clean_aliases(patch.aliases, p.name)
        have = {a.alias.lower() for a in p.aliases}
        if have != {w.lower() for w in wanted}:
            keep = {a.alias.lower(): a for a in p.aliases}
            p.aliases = [a for a in p.aliases if a.alias.lower() in {w.lower() for w in wanted}]
            for w in wanted:
                if w.lower() not in keep:
                    p.aliases.append(ProductAlias(household_id=household_id, alias=w))
            changed.add("aliases")
    if "status" in sent and patch.status is not None and patch.status != p.status:
        p.status = patch.status
        changed.add("status")
    elif p.status == "unknown" and "name" in changed:
        p.status = "known"
        changed.add("status")
    if p.status == "known" and p.source == "placeholder":
        p.source = "user"
        changed.add("source")
    if not changed:
        return p  # no-op edit: no version bump, nothing locked
    p.locked_fields = sorted(locked)
    p.version += 1
    await session.flush()
    return await get_product(session, household_id, product_id, refresh=True)


async def add_barcode(
    session: AsyncSession,
    household_id: uuid.UUID,
    product_id: uuid.UUID,
    raw: str,
    symbology: str | None,
) -> Product:
    p = await get_product(session, household_id, product_id, for_update=True)
    nb = normalize_input(raw, symbology)
    existing = await find_by_code(session, household_id, nb.code)
    if existing and existing.id == p.id:
        return p
    if existing:
        raise conflict(
            "barcode_exists",
            "Barcode already belongs to another product",
            product_id=str(existing.id),
        )
    session.add(
        ProductBarcode(
            household_id=household_id,
            product_id=p.id,
            code=nb.code,
            raw=nb.raw,
            symbology=nb.symbology,
        )
    )
    p.version += 1
    await session.flush()
    return await get_product(session, household_id, product_id, refresh=True)


async def remove_barcode(
    session: AsyncSession, household_id: uuid.UUID, product_id: uuid.UUID, code: str
) -> Product:
    p = await get_product(session, household_id, product_id, for_update=True)
    res = await session.execute(
        delete(ProductBarcode).where(
            ProductBarcode.product_id == p.id,
            ProductBarcode.household_id == household_id,
            ProductBarcode.code == code,
        )
    )
    if res.rowcount == 0:
        raise not_found("Barcode not found")
    p.version += 1
    await session.flush()
    return await get_product(session, household_id, product_id, refresh=True)


async def soft_delete_product(
    session: AsyncSession, household_id: uuid.UUID, product_id: uuid.UUID
) -> None:
    p = await get_product(session, household_id, product_id, for_update=True)
    await session.execute(delete(ProductBarcode).where(ProductBarcode.product_id == p.id))
    await session.execute(delete(EnrichmentQueue).where(EnrichmentQueue.product_id == p.id))
    await session.execute(
        update(Product)
        .where(Product.id == p.id)
        .values(deleted_at=datetime.now(UTC), version=Product.version + 1)
    )


async def merge_products(
    session: AsyncSession, household_id: uuid.UUID, source_id: uuid.UUID, into_id: uuid.UUID
) -> Product:
    if source_id == into_id:
        raise AppError(422, "invalid_merge", "Cannot merge a product into itself")
    first, second = sorted([source_id, into_id], key=str)
    await get_product(session, household_id, first, for_update=True)
    await get_product(session, household_id, second, for_update=True)
    src = await get_product(session, household_id, source_id, refresh=True)
    dst = await get_product(session, household_id, into_id, refresh=True)

    await session.execute(
        update(ProductBarcode).where(ProductBarcode.product_id == src.id).values(product_id=dst.id)
    )
    dst_aliases = {a.alias.lower() for a in dst.aliases} | {dst.name.lower()}
    for a in list(src.aliases):
        if a.alias.lower() not in dst_aliases:
            dst_aliases.add(a.alias.lower())
            await session.execute(
                update(ProductAlias).where(ProductAlias.id == a.id).values(product_id=dst.id)
            )
    if src.name.lower() not in dst_aliases and src.status != "unknown":
        session.add(ProductAlias(household_id=household_id, product_id=dst.id, alias=src.name))
    await session.execute(
        update(StockBatch).where(StockBatch.product_id == src.id).values(product_id=dst.id)
    )
    await session.execute(
        update(StockTransaction)
        .where(StockTransaction.product_id == src.id)
        .values(product_id=dst.id)
    )
    await session.execute(delete(EnrichmentQueue).where(EnrichmentQueue.product_id == src.id))

    # Shopping items: re-point, folding open duplicates into the target's open item.
    open_dst = await session.scalar(
        select(ShoppingItem).where(
            ShoppingItem.product_id == dst.id,
            ShoppingItem.checked.is_(False),
            ShoppingItem.deleted_at.is_(None),
        )
    )
    src_items = (
        (await session.execute(select(ShoppingItem).where(ShoppingItem.product_id == src.id)))
        .scalars()
        .all()
    )
    for item in src_items:
        is_open = not item.checked and item.deleted_at is None
        if is_open and open_dst is not None:
            open_dst.quantity += item.quantity
            item.deleted_at = datetime.now(UTC)
            item.product_id = None
        else:
            item.product_id = dst.id
            if is_open:
                open_dst = item
    await session.flush()

    await session.execute(
        update(Product)
        .where(Product.id == src.id)
        .values(deleted_at=datetime.now(UTC), merged_into_id=dst.id, version=Product.version + 1)
    )
    await session.execute(
        update(Product).where(Product.id == dst.id).values(version=Product.version + 1)
    )
    await session.flush()
    session.expire_all()
    return await get_product(session, household_id, into_id, refresh=True)
