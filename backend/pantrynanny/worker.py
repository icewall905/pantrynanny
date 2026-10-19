"""Background enrichment worker: ``python -m pantrynanny.worker``.

* Drains ``enrichment_queue`` (``FOR UPDATE SKIP LOCKED``, so several workers and the API can run
  side by side), with exponential backoff per item.
* Once a day refreshes stale external data of known products (never touches locked fields).
* SIGTERM/SIGINT finish the current item and exit.
"""

import asyncio
import contextlib
import signal
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .config import get_settings
from .db import make_engine, make_sessionmaker
from .logging import configure_logging, get_logger
from .models import EnrichmentQueue, LookupCache, Product, ProductBarcode
from .services.lookup import runtime
from .services.lookup.service import (
    FOUND_TTL,
    LookupOutcome,
    enrich_product,
    lookup_detailed,
    refresh_product,
)

log = get_logger("pantrynanny.worker")

BATCH = 5
POLL_S = 5.0
STALE_RUNNING = timedelta(minutes=10)
NOT_FOUND_BASE_S, NOT_FOUND_CAP_S, NOT_FOUND_MAX = 3600, 7 * 86400, 6
ERROR_BASE_S, ERROR_CAP_S, ERROR_MAX = 120, 6 * 3600, 12
MAINTENANCE_EVERY = timedelta(days=1)
REFRESH_PER_CYCLE = 40
RATE_WAIT_S = 90.0


def backoff_s(attempts: int, base: int, cap: int) -> int:
    return min(base * 2 ** max(attempts - 1, 0), cap)


async def claim(sm: async_sessionmaker[AsyncSession], limit: int = BATCH) -> list[EnrichmentQueue]:
    now = datetime.now(UTC)
    async with sm() as s, s.begin():
        # items left 'running' by a crashed worker become due again
        await s.execute(
            update(EnrichmentQueue)
            .where(
                EnrichmentQueue.status == "running",
                EnrichmentQueue.updated_at < now - STALE_RUNNING,
            )
            .values(status="pending")
        )
        rows = (
            (
                await s.execute(
                    select(EnrichmentQueue)
                    .where(
                        EnrichmentQueue.status == "pending", EnrichmentQueue.next_attempt_at <= now
                    )
                    .order_by(EnrichmentQueue.next_attempt_at)
                    .limit(limit)
                    .with_for_update(skip_locked=True)
                )
            )
            .scalars()
            .all()
        )
        for r in rows:
            r.status = "running"
            r.updated_at = now
        return list(rows)


async def _finish(
    sm: async_sessionmaker[AsyncSession], item_id: uuid.UUID, outcome: LookupOutcome, attempts: int
) -> None:
    now = datetime.now(UTC)
    values: dict = {"attempts": attempts, "updated_at": now}
    if outcome.outcome == "found":
        values.update(status="done", last_error=None)
    elif outcome.outcome == "not_found":
        if attempts >= NOT_FOUND_MAX:
            values.update(status="failed", last_error="not found by any provider")
        else:
            wait = backoff_s(attempts, NOT_FOUND_BASE_S, NOT_FOUND_CAP_S)
            values.update(
                status="pending",
                next_attempt_at=now + timedelta(seconds=wait),
                last_error="not found",
            )
    else:  # error | skipped (no provider enabled)
        if attempts >= ERROR_MAX:
            values.update(status="failed", last_error=f"gave up after {attempts} attempts")
        else:
            wait = backoff_s(attempts, ERROR_BASE_S, ERROR_CAP_S)
            values.update(
                status="pending",
                next_attempt_at=now + timedelta(seconds=wait),
                last_error=outcome.outcome,
            )
    async with sm() as s, s.begin():
        await s.execute(
            update(EnrichmentQueue).where(EnrichmentQueue.id == item_id).values(**values)
        )


async def process_item(sm: async_sessionmaker[AsyncSession], item: EnrichmentQueue) -> str:
    attempts = item.attempts + 1
    try:
        async with sm() as s:
            outcome = await lookup_detailed(
                s,
                item.household_id,
                item.code,
                product_id=item.product_id,
                budget_s=30.0,
                max_rate_wait_s=RATE_WAIT_S,
            )
        if outcome.data is not None:
            await enrich_product(sm, item.household_id, item.product_id, outcome.data)
    except Exception as exc:  # product deleted/merged, DB hiccup, ...
        log.exception("enrichment_failed", code=item.code, product_id=str(item.product_id))
        outcome = LookupOutcome("error")
        async with sm() as s, s.begin():
            await s.execute(
                update(EnrichmentQueue)
                .where(EnrichmentQueue.id == item.id)
                .values(last_error=f"{type(exc).__name__}: {exc}"[:300])
            )
    await _finish(sm, item.id, outcome, attempts)
    log.info(
        "enrichment_item",
        code=item.code,
        product_id=str(item.product_id),
        outcome=outcome.outcome,
        provider=outcome.provider,
        attempts=attempts,
    )
    return outcome.outcome


async def run_once(sm: async_sessionmaker[AsyncSession], limit: int = BATCH) -> int:
    """Process one batch of due queue items; returns how many were handled."""
    items = await claim(sm, limit)
    for item in items:
        await process_item(sm, item)
    return len(items)


async def refresh_stale(
    sm: async_sessionmaker[AsyncSession], limit: int = REFRESH_PER_CYCLE
) -> int:
    """Re-fetch provider data older than the cache TTL for known products (non-destructive)."""
    cutoff = datetime.now(UTC) - FOUND_TTL
    async with sm() as s:
        rows = (
            await s.execute(
                select(Product.household_id, Product.id)
                .join(ProductBarcode, ProductBarcode.product_id == Product.id)
                .join(
                    LookupCache,
                    (LookupCache.code == ProductBarcode.code)
                    & (LookupCache.provider == Product.source),
                )
                .where(
                    Product.deleted_at.is_(None),
                    Product.status != "unknown",
                    LookupCache.status == "found",
                    LookupCache.fetched_at < cutoff,
                )
                .group_by(Product.household_id, Product.id)
                .order_by(Product.id)
                .limit(limit)
            )
        ).all()
    done = 0
    for household_id, product_id in rows:
        try:
            out = await refresh_product(
                sm, household_id, product_id, budget_s=30.0, max_rate_wait_s=RATE_WAIT_S
            )
            done += 1
            log.info("stale_refresh", product_id=str(product_id), outcome=out.outcome)
        except Exception:
            log.exception("stale_refresh_failed", product_id=str(product_id))
    return done


async def maintenance(sm: async_sessionmaker[AsyncSession]) -> None:
    refreshed = await refresh_stale(sm)
    async with sm() as s, s.begin():
        await s.execute(
            delete(EnrichmentQueue).where(
                EnrichmentQueue.status == "done",
                EnrichmentQueue.updated_at < datetime.now(UTC) - timedelta(days=30),
            )
        )
        await s.execute(
            text("DELETE FROM lookup_attempts WHERE created_at < now() - interval '180 days'")
        )
    log.info("maintenance_done", refreshed=refreshed)


async def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_format)
    runtime.set_role("worker")
    engine = make_engine(settings)
    sm = make_sessionmaker(engine)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)
    log.info("worker_started")
    next_maintenance = datetime.now(UTC) + timedelta(minutes=2)
    try:
        while not stop.is_set():
            handled = 0
            try:
                handled = await run_once(sm)
                if datetime.now(UTC) >= next_maintenance:
                    await maintenance(sm)
                    next_maintenance = datetime.now(UTC) + MAINTENANCE_EVERY
            except Exception:
                log.exception("worker_cycle_failed")
            if handled == 0:
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(stop.wait(), timeout=POLL_S)
    finally:
        log.info("worker_stopping")
        await runtime.close_client()
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
