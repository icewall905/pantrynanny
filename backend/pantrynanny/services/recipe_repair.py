"""Repair recipes whose import failed and left nothing usable behind.

Some importers save a sentence instead of the real list: Mealie writes "Could not detect
instructions" / "Could not detect ingredients" when its scraper gives up, and the Mealie import
copied those in. Such a recipe shows a title, a photo and one meaningless line.

Admin-triggered (Admin API or ``pantrynanny-admin repair-recipes``), never automatic. Pages go
through the same SSRF-safe fetcher and size/redirect limits as a manual import, one at a time with
a pause between requests. Only a recipe whose ingredient list or instructions are missing is read
again, and only those two fields are replaced: the title, the photo, the times, the tags and the
course the household can see stay exactly as they are. A page that still holds no recipe data
leaves the recipe untouched and is reported, so nothing is ever half-overwritten.
"""

import asyncio
import uuid
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, field, fields
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..errors import AppError
from ..logging import get_logger
from ..models import Recipe, RecipeIngredient
from ..recipes.fetch import fetch_page
from ..recipes.jsonld import RecipeDraft, extract
from ..recipes.parse import parse_line

log = get_logger("pantrynanny.recipe_repair")

Fetcher = Callable[[str], Awaitable[tuple[str, str]]]
# reads a page that has no schema.org data (the household's own model, see recipes/ai_reader.py)
Reader = Callable[[str], Awaitable[dict | None]]
DEFAULT_DELAY_S = 2.0
# what importers write when they give up: "Could not detect instructions"/"ingredients"
PLACEHOLDER = "could not detect"
MAX_STEPS = 80
MAX_INGREDIENTS = 100


def _placeholder(text: str) -> bool:
    return PLACEHOLDER in " ".join(str(text).lower().split())


def instructions_missing(r: Recipe) -> bool:
    """No step at all, or nothing but the importer's placeholder."""
    steps = [s for s in (r.instructions or []) if s and s.strip()]
    return not steps or all(_placeholder(s) for s in steps)


def ingredients_missing(r: Recipe) -> bool:
    """No ingredient at all, or a list that is nothing but the importer's placeholder."""
    rows = list(r.ingredients or [])
    return not rows or all(_placeholder(f"{i.name} {i.raw}") for i in rows)


def needs_repair(r: Recipe) -> bool:
    return instructions_missing(r) or ingredients_missing(r)


@dataclass
class RepairStatus:
    running: bool = False
    checked: int = 0
    instructions_filled: int = 0
    ingredients_filled: int = 0
    failed: int = 0
    read_by_model: int = 0
    remaining: int | None = None
    without_link: int = 0
    dry_run: bool = False
    started_at: datetime | None = None
    finished_at: datetime | None = None
    last_error: str | None = None
    # one row per recipe that was read again, so a run can be checked afterwards
    repaired: list[dict] = field(default_factory=list)
    problems: list[dict] = field(default_factory=list)
    _task: asyncio.Task | None = field(default=None, repr=False)

    def public(self) -> dict:
        return {f.name: getattr(self, f.name) for f in fields(self) if f.name != "_task"}


async def _broken(
    session: AsyncSession, household_id: uuid.UUID, only: Iterable[uuid.UUID] | None = None
) -> list[Recipe]:
    """The household's recipes that have no real ingredient list or no real instructions.

    A household has a few thousand recipes at most, and the test itself is the rule used when
    writing (``needs_repair``), so it is applied here rather than twice, once in SQL.
    """
    stmt = (
        select(Recipe)
        .where(Recipe.household_id == household_id, Recipe.deleted_at.is_(None))
        .order_by(Recipe.created_at, Recipe.id)
    )
    if only is not None:
        stmt = stmt.where(Recipe.id.in_(list(only)))
    rows = (await session.execute(stmt)).scalars().all()
    return [r for r in rows if needs_repair(r)]


async def remaining(session: AsyncSession, household_id: uuid.UUID) -> int:
    """How many recipes still have no real ingredient list or no real instructions."""
    return len(await _broken(session, household_id))


async def missing_links(session: AsyncSession, household_id: uuid.UUID) -> list[Recipe]:
    """Broken recipes with no page to read again: those need a link found some other way."""
    return [r for r in await _broken(session, household_id) if not r.source_url]


def _fill(r: Recipe, draft) -> tuple[bool, bool]:
    """Replace the placeholder steps and/or ingredient list. Nothing else is touched."""
    filled_steps = filled_ingredients = False
    steps = [s.strip()[:2000] for s in (draft.instructions or []) if s and s.strip()]
    if steps and instructions_missing(r):
        r.instructions = steps[:MAX_STEPS]
        filled_steps = True
    raws = [s for s in (draft.ingredients or []) if s and s.strip()]
    if raws and ingredients_missing(r):
        rows = []
        for position, raw in enumerate(raws[:MAX_INGREDIENTS]):
            p = parse_line(raw)
            rows.append(
                RecipeIngredient(
                    position=position,
                    raw=p.raw,
                    name=p.name,
                    quantity=p.quantity,
                    unit=p.unit,
                    note=p.note,
                    optional=p.optional,
                )
            )
        r.ingredients = rows
        filled_ingredients = True
    if filled_steps or filled_ingredients:
        r.version = (r.version or 0) + 1
        r.updated_at = datetime.now(UTC)
    return filled_steps, filled_ingredients


def _would_fill(r: Recipe, draft) -> tuple[bool, bool]:
    """What ``_fill`` would change, without writing anything (dry run)."""
    steps = [s for s in (draft.instructions or []) if s and s.strip()]
    raws = [s for s in (draft.ingredients or []) if s and s.strip()]
    return (
        bool(steps) and instructions_missing(r),
        bool(raws) and ingredients_missing(r),
    )


def _record(
    status: RepairStatus, r: Recipe, url: str, draft, steps: bool, ingredients: bool
) -> None:
    status.instructions_filled += int(steps)
    status.ingredients_filled += int(ingredients)
    status.repaired.append(
        {
            "id": str(r.id),
            "title": r.title,
            "url": url,
            "instructions": len(draft.instructions or []) if steps else 0,
            "ingredients": len(draft.ingredients or []) if ingredients else 0,
            "filled": {"instructions": steps, "ingredients": ingredients},
        }
    )


async def run(
    sm: async_sessionmaker[AsyncSession],
    household_id: uuid.UUID,
    status: RepairStatus,
    *,
    fetcher: Fetcher = fetch_page,
    delay_s: float = DEFAULT_DELAY_S,
    limit: int | None = None,
    dry_run: bool = False,
    overrides: dict[uuid.UUID, str] | None = None,
    only: Iterable[uuid.UUID] | None = None,
    reader: Reader | None = None,
) -> RepairStatus:
    """Read the source page of every broken recipe again and fill in what is missing.

    ``overrides`` maps a recipe to a different page (a recipe whose own link is gone); ``only``
    restricts the run to those recipes. With ``dry_run`` nothing is written, so a run can be
    checked before it changes recipes. ``reader`` is a second chance for pages that carry no
    schema.org data: it is only asked when the structured read found nothing, and it is expected
    to verify what it returns against the page itself.
    """
    overrides = overrides or {}
    status.running, status.dry_run = True, dry_run
    status.started_at, status.finished_at = datetime.now(UTC), None
    try:
        async with sm() as s:
            todo = await _broken(s, household_id, only)
        status.without_link = sum(1 for r in todo if not r.source_url and r.id not in overrides)
        todo = [r for r in todo if r.source_url or r.id in overrides]
        if limit is not None:
            todo = todo[:limit]
        done = 0
        for candidate in todo:
            url = overrides.get(candidate.id) or candidate.source_url
            if done:
                await asyncio.sleep(delay_s)  # be polite to recipe sites
            done += 1
            draft, reason = None, None
            try:
                _, page = await fetcher(url)
                draft = extract(page)
                if reader is not None and (
                    draft is None or (not draft.instructions and not draft.ingredients)
                ):
                    found = await reader(page)
                    if found:
                        draft = RecipeDraft(
                            title=candidate.title,
                            ingredients=found.get("ingredients") or [],
                            instructions=found.get("instructions") or [],
                        )
                        status.read_by_model += 1
                if draft is None or (not draft.instructions and not draft.ingredients):
                    reason = "page has no recipe data"
            except AppError as exc:
                reason = f"{exc.code}: {exc.detail}"[:300]
            except Exception as exc:  # network trouble etc.: note it and move on
                reason = type(exc).__name__[:120]
            if reason is not None:
                status.failed += 1
                status.last_error = reason
                status.problems.append(
                    {
                        "id": str(candidate.id),
                        "title": candidate.title,
                        "url": url,
                        "reason": reason,
                    }
                )
                status.checked += 1
                continue
            if dry_run:
                async with sm() as s:
                    r = await s.get(Recipe, candidate.id)
                    if r is None or not needs_repair(r):
                        status.checked += 1
                        continue
                    _record(status, r, url, draft, *_would_fill(r, draft))
            else:
                async with sm() as s, s.begin():
                    r = await s.get(Recipe, candidate.id, with_for_update=True)
                    if r is None or not needs_repair(r):
                        status.checked += 1
                        continue
                    steps, ingredients = _fill(r, draft)
                    _record(status, r, url, draft, steps, ingredients)
            status.checked += 1
        async with sm() as s:
            status.remaining = await remaining(s, household_id)
    finally:
        status.running, status.finished_at = False, datetime.now(UTC)
    log.info(
        "recipe_repair_done",
        **{
            k: v
            for k, v in status.public().items()
            if k not in ("last_error", "repaired", "problems")
        },
    )
    return status
