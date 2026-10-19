"""Seed catalogue: file reader, idempotent importer and lookup helpers (global, no household)."""

import gzip
import json
from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import CatalogueSeed

DEFAULT_SEED_FILE = Path(__file__).resolve().parent.parent / "data" / "seed" / "off_dk.jsonl.gz"
SEED_SOURCE = "catalogue_seed"
BATCH = 2000  # 11 columns x 2000 rows stays far below the 32767 bind-parameter limit


def read_meta(path: Path) -> dict[str, Any]:
    with gzip.open(path, "rt", encoding="utf-8") as f:
        return json.loads(f.readline())["_meta"]


def iter_records(path: Path) -> Iterator[dict[str, Any]]:
    with gzip.open(path, "rt", encoding="utf-8") as f:
        f.readline()  # metadata header
        for line in f:
            if line.strip():
                yield json.loads(line)


def _row(rec: dict[str, Any], meta: dict[str, Any], now: datetime) -> dict[str, Any]:
    size = rec.get("package_size")
    return {
        "code": rec["code"],
        "name": rec["name"],
        "brand": rec.get("brand"),
        "package_size": Decimal(str(size)) if size else None,
        "package_unit": rec.get("package_unit") if size else None,
        "category_hint": rec.get("category_hint"),
        "allergens": rec.get("allergens") or [],
        "countries": rec.get("countries") or [],
        "source": SEED_SOURCE,
        "license": meta["license"],
        "dataset_version": meta["dataset_version"],
        "updated_at": now,
    }


async def seed_versions(session: AsyncSession) -> dict[str, int]:
    rows = await session.execute(
        select(CatalogueSeed.dataset_version, func.count()).group_by(CatalogueSeed.dataset_version)
    )
    return dict(rows.all())


async def import_seed(
    session: AsyncSession, path: Path = DEFAULT_SEED_FILE, *, if_changed: bool = False
) -> tuple[str, int]:
    """Upsert the file into ``catalogue_seed``. Returns ``(status, rows)``.

    status is ``unchanged`` (only with ``if_changed`` and an identical version/row count already
    loaded) or ``imported``. Rows of older dataset versions that are absent from the file are
    removed so the table mirrors the file exactly.
    """
    meta = read_meta(path)
    version = meta["dataset_version"]
    if if_changed:
        have = await seed_versions(session)
        if have == {version: int(meta["count"])}:
            return "unchanged", int(meta["count"])
    now = datetime.now(UTC)
    total = 0
    batch: list[dict[str, Any]] = []

    async def flush() -> None:
        nonlocal batch
        if not batch:
            return
        stmt = insert(CatalogueSeed)
        stmt = stmt.on_conflict_do_update(
            index_elements=["code"],
            set_={c: stmt.excluded[c] for c in batch[0] if c != "code"},
        )
        await session.execute(stmt, batch)
        batch = []

    for rec in iter_records(path):
        batch.append(_row(rec, meta, now))
        total += 1
        if len(batch) >= BATCH:
            await flush()
    await flush()
    await session.execute(
        delete(CatalogueSeed).where(
            CatalogueSeed.source == SEED_SOURCE, CatalogueSeed.dataset_version != version
        )
    )
    await session.commit()
    return "imported", total


async def seed_stats(session: AsyncSession) -> dict[str, Any]:
    versions = await seed_versions(session)
    return {"size": sum(versions.values()), "dataset_versions": sorted(versions)}
