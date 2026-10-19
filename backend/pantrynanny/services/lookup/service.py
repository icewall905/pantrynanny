"""Lookup orchestration: cache, provider chain, attempt log, applying data to products."""

import asyncio
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ...logging import get_logger
from ...models import Category, LookupAttempt, LookupCache, Product, ProviderSetting
from . import runtime
from .media import delete_image, download_image
from .providers import ProductData, ProviderConfig, ProviderResult, build_providers
from .ratelimit import bucket_for

log = get_logger("pantrynanny.lookup")

FOUND_TTL = timedelta(days=30)
NOT_FOUND_TTL = timedelta(days=7)
ERROR_BACKOFF_BASE_S = 60
ERROR_BACKOFF_CAP_S = 6 * 3600
REVIEW_BELOW = 0.6
UNITS = {"pcs", "pkg", "g", "kg", "ml", "cl", "dl", "l"}


@dataclass(slots=True)
class LookupOutcome:
    outcome: str  # found | not_found | error | skipped
    data: ProductData | None = None
    provider: str | None = None


def error_backoff_s(n_errors: int) -> int:
    return min(ERROR_BACKOFF_BASE_S * 2 ** max(n_errors - 1, 0), ERROR_BACKOFF_CAP_S)


async def load_overrides(session: AsyncSession) -> dict[str, ProviderConfig]:
    rows = (await session.execute(select(ProviderSetting))).scalars().all()
    return {
        r.name: ProviderConfig(r.name, enabled=r.enabled, priority=r.priority, api_key=r.api_key)
        for r in rows
    }


async def _log_attempt(
    session: AsyncSession,
    household_id: uuid.UUID | None,
    product_id: uuid.UUID | None,
    code: str,
    provider: str,
    status: str,
    *,
    http_status: int | None = None,
    duration_ms: int | None = None,
    error: str | None = None,
) -> None:
    session.add(
        LookupAttempt(
            household_id=household_id,
            product_id=product_id,
            code=code,
            provider=provider,
            status=status,
            http_status=http_status,
            duration_ms=duration_ms,
            error=error[:500] if error else None,
        )
    )


async def _store_cache(session: AsyncSession, code: str, provider: str, res: ProviderResult, prev):
    now = datetime.now(UTC)
    payload: dict[str, Any] | None
    retry_after = None
    if res.status == "found" and res.data is not None:
        payload = {"data": asdict(res.data), "raw": res.raw}
    elif res.status == "not_found":
        payload = {"raw": res.raw} if res.raw else None
    else:
        n = ((prev.payload or {}).get("errors", 0) if prev is not None else 0) + 1
        wait = max(error_backoff_s(n), int(res.retry_after_s or 0))
        retry_after = now + timedelta(seconds=wait)
        payload = {"errors": n, "error": res.error, "http_status": res.http_status}
    stmt = insert(LookupCache).values(
        code=code,
        provider=provider,
        status=res.status,
        payload=payload,
        fetched_at=now,
        retry_after=retry_after,
    )
    stmt = stmt.on_conflict_do_update(
        constraint="uq_lookup_cache_code_provider",
        set_={
            "status": stmt.excluded.status,
            "payload": stmt.excluded.payload,
            "fetched_at": stmt.excluded.fetched_at,
            "retry_after": stmt.excluded.retry_after,
        },
    )
    await session.execute(stmt)


async def lookup_detailed(
    session: AsyncSession,
    household_id: uuid.UUID | None,
    code: str,
    *,
    product_id: uuid.UUID | None = None,
    force: bool = False,
    budget_s: float | None = None,
    max_rate_wait_s: float | None = None,
    stop: asyncio.Event | None = None,
) -> LookupOutcome:
    """Resolve ``code`` (normalised GTIN-14) through cache, then providers in priority order.

    ``force`` bypasses fresh cache entries (refresh); error backoff is still respected unless
    forced. ``budget_s`` bounds total time; ``max_rate_wait_s`` lets background callers wait for
    the rate limiter (the interactive path never waits for it).
    """
    settings = runtime.get_settings()
    if not code.isdigit():
        return LookupOutcome("not_found")
    budget = budget_s if budget_s is not None else settings.lookup_timeout_s
    deadline = time.monotonic() + budget
    overrides = await load_overrides(session)
    providers = [p for p in build_providers(settings, overrides) if p.enabled()]
    if not providers:
        return LookupOutcome("skipped")
    saw_error = False
    for p in providers:
        cached = (
            await session.execute(
                select(LookupCache).where(LookupCache.code == code, LookupCache.provider == p.name)
            )
        ).scalar_one_or_none()
        now = datetime.now(UTC)
        if cached is not None:
            if not force and cached.status == "found" and cached.fetched_at + FOUND_TTL > now:
                try:
                    data = ProductData(**(cached.payload or {})["data"])
                except (KeyError, TypeError):
                    data = None
                if data is not None:
                    await _log_attempt(
                        session, household_id, product_id, code, p.name, "cache_hit", duration_ms=0
                    )
                    await session.commit()
                    return LookupOutcome("found", data, p.name)
            elif (
                not force
                and cached.status == "not_found"
                and cached.fetched_at + NOT_FOUND_TTL > now
            ):
                await _log_attempt(
                    session, household_id, product_id, code, p.name, "cache_negative"
                )
                continue
            elif (
                cached.status == "error"
                and cached.retry_after
                and cached.retry_after > now
                and (not force or (cached.payload or {}).get("http_status") == 429)
            ):  # a forced refresh still honours a provider's 429 / Retry-After
                await _log_attempt(session, household_id, product_id, code, p.name, "cache_error")
                saw_error = True
                continue
        remaining = deadline - time.monotonic()
        if remaining <= 0.05:
            saw_error = True
            break
        bucket = bucket_for(p.name, p.rate_per_min())
        wait_allowed = min(max_rate_wait_s, remaining) if max_rate_wait_s else 0.0
        if not await bucket.acquire(wait_allowed, stop):
            if stop is not None and stop.is_set():
                return LookupOutcome("error")
            await _log_attempt(
                session, household_id, product_id, code, p.name, "rate_limited", error="local limit"
            )
            saw_error = True
            continue
        remaining = max(deadline - time.monotonic(), 1.0)
        t0 = time.monotonic()
        res = await p.fetch(code, timeout_s=remaining)
        ms = int((time.monotonic() - t0) * 1000)
        await _log_attempt(
            session,
            household_id,
            product_id,
            code,
            p.name,
            res.status,
            http_status=res.http_status,
            duration_ms=ms,
            error=res.error,
        )
        await _store_cache(session, code, p.name, res, cached)
        await session.commit()
        if res.status == "found" and res.data is not None:
            return LookupOutcome("found", res.data, p.name)
        if res.status == "error":
            saw_error = True
            log.warning("lookup_provider_error", provider=p.name, code=code, error=res.error)
    await session.commit()
    return LookupOutcome("error" if saw_error else "not_found")


async def lookup_external(
    session: AsyncSession,
    household_id: uuid.UUID,
    code: str,
    symbology: str | None = None,
    *,
    product_id: uuid.UUID | None = None,
    force: bool = False,
    budget_s: float | None = None,
) -> ProductData | None:
    """Synchronously resolve ``code`` via the local cache and the enabled providers."""
    out = await lookup_detailed(
        session, household_id, code, product_id=product_id, force=force, budget_s=budget_s
    )
    return out.data


# --------------------------------------------------------------------------- applying data


def _blank(v: Any) -> bool:
    return v is None or v == "" or v == [] or v == {}


async def _category_id(
    session: AsyncSession, household_id: uuid.UUID, hint: str | None
) -> uuid.UUID | None:
    if not hint:
        return None
    return await session.scalar(
        select(Category.id).where(
            Category.household_id == household_id,
            Category.name == hint,
            Category.deleted_at.is_(None),
        )
    )


def status_for(data: ProductData) -> str:
    return "known" if (data.confidence or 0) >= REVIEW_BELOW else "needs_review"


def _unit(data: ProductData) -> str | None:
    return data.package_unit if data.package_unit in UNITS else None


async def new_product_from_data(
    session: AsyncSession, household_id: uuid.UUID, data: ProductData
) -> Product:
    unit = _unit(data)
    return Product(
        household_id=household_id,
        name=data.name[:200],
        brand=data.brand,
        category_id=await _category_id(session, household_id, data.category_hint),
        package_size=Decimal(str(data.package_size)) if data.package_size and unit else None,
        package_unit=unit if data.package_size else None,
        ingredients=data.ingredients,
        allergens=list(data.allergens),
        nutrition=data.nutrition,
        countries=list(data.countries),
        description=data.description,
        status=status_for(data),
        source=data.source,
        source_attribution=data.source_attribution,
        lookup_confidence=data.confidence,
        barcodes=[],
        aliases=[],
        locked_fields=[],
    )


@dataclass(slots=True)
class ApplyResult:
    changed: bool = False
    image_used: bool = False


async def apply_product_data(
    session: AsyncSession,
    p: Product,
    data: ProductData,
    *,
    image_filename: str | None = None,
) -> ApplyResult:
    """Merge provider ``data`` into ``p`` without ever touching household-owned fields.

    * Fields in ``locked_fields`` (edited by a person) are never changed.
    * A product whose ``source`` is ``user`` (created by hand) only has *empty* fields filled.
    * Placeholders and provider-sourced products get unlocked fields refreshed, but a provider
      never blanks a field it has no value for.
    Caller must hold the row lock (``get_product(..., for_update=True)``).
    """
    locked = set(p.locked_fields or [])
    user_owned = p.source == "user"
    res = ApplyResult()
    touched = False

    def ok(field: str, current: Any, new: Any) -> bool:
        if _blank(new) or field in locked:
            return False
        if user_owned and not _blank(current):
            return False
        return current != new

    if p.status == "unknown" or p.source == "placeholder":
        # the placeholder name is not worth protecting, even for fill-only semantics
        if "name" not in locked:
            p.name = data.name[:200]
            touched = True
    elif ok("name", p.name, data.name[:200]):
        p.name = data.name[:200]
        touched = True
    if ok("brand", p.brand, data.brand):
        p.brand, touched = data.brand, True
    cat = await _category_id(session, p.household_id, data.category_hint)
    if ok("category_id", p.category_id, cat):
        p.category_id, touched = cat, True
    unit = _unit(data)
    if (
        data.package_size
        and unit
        and "package_size" not in locked
        and "package_unit" not in locked
        and (not user_owned or p.package_size is None)
    ):
        new_size = Decimal(str(data.package_size))
        if p.package_size != new_size or p.package_unit != unit:
            p.package_size, p.package_unit, touched = new_size, unit, True
    for field, value in (
        ("ingredients", data.ingredients),
        ("allergens", list(data.allergens)),
        ("nutrition", data.nutrition),
        ("description", data.description),
        ("countries", list(data.countries)),
    ):
        if ok(field, getattr(p, field), value):
            setattr(p, field, value)
            touched = True
    if image_filename and "image" not in locked and not p.image_path:
        p.image_path = image_filename
        res.image_used = touched = True

    if touched:
        if user_owned:
            attr = p.source_attribution or ""
            if data.source_attribution and data.source_attribution not in attr:
                p.source_attribution = "; ".join(x for x in (attr, data.source_attribution) if x)
        else:
            p.source = data.source
            p.source_attribution = data.source_attribution
            p.lookup_confidence = data.confidence
        if p.status == "unknown":
            p.status = status_for(data)
        p.version += 1
        res.changed = True
        await session.flush()
    return res


async def enrich_product(
    sm: async_sessionmaker[AsyncSession],
    household_id: uuid.UUID,
    product_id: uuid.UUID,
    data: ProductData,
) -> bool:
    """Apply ``data`` to a stored product (downloads the image first, outside the row lock)."""
    from ..products import get_product  # local import: products imports this package

    filename = None
    async with sm() as s:
        p = await get_product(s, household_id, product_id)
        wants_image = bool(data.image_url) and not p.image_path and "image" not in (p.locked_fields)
    if wants_image:
        filename = await download_image(data.image_url)
    async with sm() as s:
        try:
            p = await get_product(s, household_id, product_id, for_update=True)
            res = await apply_product_data(s, p, data, image_filename=filename)
            await s.commit()
        except Exception:
            await s.rollback()
            delete_image(filename)
            raise
    if filename and not res.image_used:
        delete_image(filename)
    return res.changed


async def refresh_product(
    sm: async_sessionmaker[AsyncSession],
    household_id: uuid.UUID,
    product_id: uuid.UUID,
    *,
    budget_s: float = 10.0,
    max_rate_wait_s: float | None = None,
    stop: asyncio.Event | None = None,
) -> LookupOutcome:
    """Force a provider re-lookup for every real barcode of the product and apply the result."""
    from ..products import get_product

    async with sm() as s:
        p = await get_product(s, household_id, product_id)
        codes = [b.code for b in p.barcodes if not b.code.startswith(("local:", "instore:"))]
    result = LookupOutcome("not_found")
    for code in codes:
        async with sm() as s:
            out = await lookup_detailed(
                s,
                household_id,
                code,
                product_id=product_id,
                force=True,
                budget_s=budget_s,
                max_rate_wait_s=max_rate_wait_s,
                stop=stop,
            )
        if out.data is not None:
            await enrich_product(sm, household_id, product_id, out.data)
            return out
        if out.outcome == "error":
            result = out
    return result
