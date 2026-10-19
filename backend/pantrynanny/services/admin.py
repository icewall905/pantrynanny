"""Catalogue administration: status counts, failed lookups, duplicates, lookup statistics."""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import LookupAttempt, Product, ProviderSetting
from .lookup import runtime
from .lookup.providers import PROVIDER_CLASSES, build_providers
from .lookup.service import load_overrides
from .products import product_out

STATUSES = ("known", "unknown", "needs_review")
ATTEMPT_STATUSES = (
    "found",
    "not_found",
    "error",
    "rate_limited",
    "cache_hit",
    "cache_negative",
    "cache_error",
)
STATS_WINDOW_DAYS = 30


async def lookup_stats(session: AsyncSession, household_id: uuid.UUID) -> dict:
    since = datetime.now(UTC) - timedelta(days=STATS_WINDOW_DAYS)
    rows = (
        await session.execute(
            select(LookupAttempt.status, func.count())
            .where(LookupAttempt.household_id == household_id, LookupAttempt.created_at >= since)
            .group_by(LookupAttempt.status)
        )
    ).all()
    c = {s: 0 for s in ATTEMPT_STATUSES}
    c.update({s: n for s, n in rows})
    total = sum(c.values())
    cached = c["cache_hit"] + c["cache_negative"]
    return {
        "window_days": STATS_WINDOW_DAYS,
        "attempts": total,
        "hits": c["found"] + c["cache_hit"],
        "misses": c["not_found"] + c["cache_negative"],
        "errors": c["error"] + c["rate_limited"] + c["cache_error"],
        "cache_hits": cached,
        "cache_hit_rate": round(cached / total, 3) if total else None,
    }


def _attempt_out(a: LookupAttempt) -> dict:
    return {
        "id": a.id,
        "barcode": a.code,
        "provider": a.provider,
        "status": a.status,
        "http_status": a.http_status,
        "duration_ms": a.duration_ms,
        "error": a.error,
        "product_id": a.product_id,
        "created_at": a.created_at,
    }


async def failed_lookups(session: AsyncSession, household_id: uuid.UUID, limit: int = 50) -> list:
    """Most recent failure per barcode that still has no good product."""
    latest = (
        select(LookupAttempt)
        .where(
            LookupAttempt.household_id == household_id,
            LookupAttempt.status.in_(("not_found", "error")),
        )
        .ext(distinct_on(LookupAttempt.code))
        .order_by(LookupAttempt.code, LookupAttempt.created_at.desc())
        .subquery()
    )
    rows = (
        (
            await session.execute(
                select(LookupAttempt)
                .join(latest, LookupAttempt.id == latest.c.id)
                .order_by(LookupAttempt.created_at.desc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return [_attempt_out(a) for a in rows]


async def duplicate_candidates(
    session: AsyncSession, household_id: uuid.UUID, limit: int = 50
) -> list[dict]:
    await session.execute(text("SELECT set_config('pg_trgm.similarity_threshold', '0.8', true)"))
    rows = (
        await session.execute(
            text(
                """
                SELECT a.id AS a_id, b.id AS b_id,
                       similarity(pn_unaccent(lower(a.name)), pn_unaccent(lower(b.name))) AS sim,
                       pn_unaccent(lower(a.name)) = pn_unaccent(lower(b.name)) AS same
                FROM products a
                JOIN products b ON a.household_id = b.household_id AND a.id < b.id
                 AND pn_unaccent(lower(a.name)) % pn_unaccent(lower(b.name))
                 AND (
                      (a.brand IS NULL AND b.brand IS NULL)
                   OR lower(a.brand) = lower(b.brand)
                   OR similarity(pn_unaccent(lower(coalesce(a.brand, ''))),
                                 pn_unaccent(lower(coalesce(b.brand, '')))) > 0.8
                 )
                WHERE a.household_id = :hh AND a.deleted_at IS NULL AND b.deleted_at IS NULL
                  AND a.status <> 'unknown' AND b.status <> 'unknown'
                ORDER BY sim DESC, a.name
                LIMIT :lim
                """
            ),
            {"hh": household_id, "lim": limit},
        )
    ).all()
    ids = {r.a_id for r in rows} | {r.b_id for r in rows}
    products = {}
    if ids:
        products = {
            p.id: p
            for p in (await session.execute(select(Product).where(Product.id.in_(ids)))).scalars()
        }
    return [
        {
            "a": product_out(products[r.a_id]).model_dump(mode="json"),
            "b": product_out(products[r.b_id]).model_dump(mode="json"),
            "ids": [str(r.a_id), str(r.b_id)],
            "names": [products[r.a_id].name, products[r.b_id].name],
            "reason": "same_name" if r.same else "similar_name",
            "similarity": round(float(r.sim), 3),
        }
        for r in rows
    ]


async def catalogue(session: AsyncSession, household_id: uuid.UUID) -> dict:
    base = (Product.household_id == household_id, Product.deleted_at.is_(None))
    by_status = {s: 0 for s in STATUSES}
    by_status.update(
        dict(
            (
                await session.execute(
                    select(Product.status, func.count()).where(*base).group_by(Product.status)
                )
            ).all()
        )
    )
    by_source = dict(
        (
            await session.execute(
                select(Product.source, func.count())
                .where(*base)
                .group_by(Product.source)
                .order_by(func.count().desc())
            )
        ).all()
    )
    return {
        "by_status": by_status,
        "by_source": by_source,
        "failed_lookups": await failed_lookups(session, household_id),
        "duplicate_candidates": await duplicate_candidates(session, household_id),
        "lookup_stats": await lookup_stats(session, household_id),
    }


async def list_lookups(
    session: AsyncSession,
    household_id: uuid.UUID,
    *,
    status: str | None,
    limit: int,
    offset: int,
) -> list[dict]:
    stmt = select(LookupAttempt).where(LookupAttempt.household_id == household_id)
    if status:
        stmt = stmt.where(LookupAttempt.status == status)
    stmt = stmt.order_by(LookupAttempt.created_at.desc()).limit(limit).offset(offset)
    return [_attempt_out(a) for a in (await session.execute(stmt)).scalars()]


# --------------------------------------------------------------------------- providers


def mask_key(key: str | None) -> str | None:
    if not key:
        return None
    return "••••" + key[-4:] if len(key) >= 12 else "••••"


async def provider_infos(session: AsyncSession) -> list[dict]:
    settings = runtime.get_settings()
    overrides = await load_overrides(session)
    out = []
    for p in build_providers(settings, overrides):
        ov = overrides.get(p.name)
        db_key = ov.api_key if ov else None
        env_key = settings.eansearch_token if p.name == "eansearch" else None
        key = db_key or env_key
        out.append(
            {
                "id": p.name,
                "name": p.display_name,
                "enabled": p.enabled(),
                "priority": p.priority,
                "requires_key": p.requires_key,
                "has_key": bool(key),
                "api_key": mask_key(key),
                "key_source": "db" if db_key else ("env" if env_key else None),
                "license": p.license,
                "attribution": p.attribution,
                "rate_limit_per_min": p.rate_per_min(),
            }
        )
    return out


async def update_providers(session: AsyncSession, updates: list[dict]) -> None:
    classes = {c.name: c for c in PROVIDER_CLASSES}
    for u in updates:
        name = u["name"]
        cls = classes[name]
        row = await session.get(ProviderSetting, name)
        if row is None:
            row = ProviderSetting(name=name)
            session.add(row)
        if "enabled" in u and u["enabled"] is not None:
            row.enabled = u["enabled"]
        if "priority" in u and u["priority"] is not None:
            row.priority = u["priority"]
        if "api_key" in u and u["api_key"] is not None and cls.requires_key:
            row.api_key = u["api_key"].strip() or None
        row.updated_at = datetime.now(UTC)
    await session.flush()
