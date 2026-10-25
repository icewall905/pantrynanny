"""Fill in what older recipes lack (cooking time, course) by re-reading their source pages.

Admin-triggered (Admin API or ``pantrynanny-admin backfill-recipes``), never automatic. Pages go
through the same SSRF-safe fetcher and size/redirect limits as a manual import, one at a time
with a pause between requests. Resumable: every recipe that was tried gets
``source_checked_at``, so a stopped or restarted run carries on with the rest. Only empty fields
are filled; nothing the household typed is overwritten.
"""

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field, fields
from datetime import UTC, datetime

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..errors import AppError
from ..logging import get_logger
from ..models import Recipe
from ..recipes.course import classify, from_tags
from ..recipes.fetch import fetch_page
from ..recipes.jsonld import extract

log = get_logger("pantrynanny.recipe_backfill")

Fetcher = Callable[[str], Awaitable[tuple[str, str]]]
DEFAULT_DELAY_S = 2.0


@dataclass
class BackfillStatus:
    running: bool = False
    checked: int = 0
    times_filled: int = 0
    courses_filled: int = 0
    failed: int = 0
    remaining: int | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    last_error: str | None = None
    _task: asyncio.Task | None = field(default=None, repr=False)

    def public(self) -> dict:
        return {f.name: getattr(self, f.name) for f in fields(self) if f.name != "_task"}


def _needs_work():
    return (
        Recipe.deleted_at.is_(None),
        Recipe.source_url.is_not(None),
        Recipe.source_checked_at.is_(None),
        or_(
            Recipe.course.is_(None),
            (Recipe.prep_min.is_(None) & Recipe.cook_min.is_(None)),
        ),
    )


async def remaining(session: AsyncSession, household_id: uuid.UUID) -> int:
    return (
        await session.scalar(
            select(func.count())
            .select_from(Recipe)
            .where(Recipe.household_id == household_id, *_needs_work())
        )
        or 0
    )


async def run(
    sm: async_sessionmaker[AsyncSession],
    household_id: uuid.UUID,
    status: BackfillStatus,
    *,
    fetcher: Fetcher = fetch_page,
    delay_s: float = DEFAULT_DELAY_S,
    limit: int | None = None,
) -> BackfillStatus:
    status.running, status.started_at, status.finished_at = True, datetime.now(UTC), None
    try:
        done = 0
        while limit is None or done < limit:
            async with sm() as s:
                rid, url = (
                    await s.execute(
                        select(Recipe.id, Recipe.source_url)
                        .where(Recipe.household_id == household_id, *_needs_work())
                        .order_by(Recipe.created_at, Recipe.id)
                        .limit(1)
                    )
                ).first() or (None, None)
            if rid is None:
                break
            if done:
                await asyncio.sleep(delay_s)  # be polite to recipe sites
            draft = None
            try:
                _, page = await fetcher(url)
                draft = extract(page)
            except AppError as exc:
                status.failed += 1
                status.last_error = f"{exc.code}: {exc.detail}"[:300]
            except Exception as exc:  # network trouble etc.: note it and move on
                status.failed += 1
                status.last_error = f"{type(exc).__name__}"[:300]
            async with sm() as s, s.begin():
                r = await s.get(Recipe, rid, with_for_update=True)
                if r is not None:
                    _apply(r, draft, status)
                    r.source_checked_at = datetime.now(UTC)
            status.checked += 1
            done += 1
        async with sm() as s:
            status.remaining = await remaining(s, household_id)
    finally:
        status.running, status.finished_at = False, datetime.now(UTC)
    log.info(
        "recipe_backfill_done", **{k: v for k, v in status.public().items() if k != "last_error"}
    )
    return status


def _apply(r: Recipe, draft, status: BackfillStatus) -> None:
    found = draft is not None and (draft.prep_min is not None or draft.cook_min is not None)
    if found and r.prep_min is None and r.cook_min is None:
        r.prep_min, r.cook_min = draft.prep_min, draft.cook_min
        status.times_filled += 1
    page_tags = draft.tags if draft is not None else []
    if page_tags and not r.tags:
        r.tags = page_tags[:20]
    if r.course is None:
        course = from_tags(page_tags) or classify(
            r.title, list(r.tags or []) + page_tags, [i.name for i in r.ingredients]
        )
        if course:
            r.course = course
            status.courses_filled += 1


async def classify_all(session: AsyncSession, household_id: uuid.UUID) -> int:
    """Store the classifier's course for every recipe without one (no network)."""
    rows = (
        (
            await session.execute(
                select(Recipe).where(
                    Recipe.household_id == household_id,
                    Recipe.deleted_at.is_(None),
                    Recipe.course.is_(None),
                )
            )
        )
        .scalars()
        .all()
    )
    n = 0
    for r in rows:
        c = classify(r.title, list(r.tags or []), [i.name for i in r.ingredients])
        if c:
            r.course = c
            n += 1
    return n
