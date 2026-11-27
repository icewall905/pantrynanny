"""Import (or re-import) recipes from a Mealie server: tags, categories, times and photos.

Admin-triggered (``pantrynanny-admin import-mealie``), never automatic. Safe to run again:
each imported recipe remembers ``external_id = "mealie:<id>"``. A recipe that is already here
(same Mealie id, else same source URL, else same title) is not duplicated; it gets Mealie's
categories, any tags it lacks, missing times/course and, when it has none (or with
``replace_images``), a local copy of Mealie's photo. Photos are re-encoded to WebP and stored
under PN_UPLOAD_DIR like product photos, so they show even where Mealie is not reachable.
Ingredients and steps of recipes that are already here are never touched.

Mealie keeps copies of one recipe ("Soup" and "Soup (1)", same source URL) when a page was
imported twice. Only the first is brought in; the others count as ``duplicates``.
"""

import re
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from urllib.parse import urlparse

import httpx
from pydantic import ValidationError
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..logging import get_logger
from ..models import Recipe
from ..recipes.course import classify, from_tags
from ..schemas.recipes import IngredientIn, RecipeIn
from . import recipes as svc
from .lookup import runtime
from .lookup.media import FILE_RE, InvalidImage, delete_image, store_image

log = get_logger("pantrynanny.mealie_import")

PER_PAGE = 100
MAX_TAGS = 20
LOCAL_PREFIX = "/api/media/"


@dataclass
class MealieStats:
    seen: int = 0
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    skipped: int = 0  # not here and create=False
    duplicates: int = 0  # a copy, inside Mealie, of a recipe already linked to another Mealie id
    images: int = 0
    image_failed: int = 0
    failed: int = 0
    last_error: str | None = None

    def public(self) -> dict:
        return asdict(self)


def external_id(m: dict) -> str:
    return f"mealie:{m['id']}"


def _names(v: object) -> list[str]:
    out = []
    for x in v or []:  # type: ignore[union-attr]
        name = (x.get("name") if isinstance(x, dict) else x) or ""
        if str(name).strip():
            out.append(str(name).strip()[:40])
    return list(dict.fromkeys(out))


_DUR = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*(h|hour|hours|t|time|timer|m|min|mins|minute|minutes)\b", re.I
)


def _minutes(seconds: object, text: object) -> int | None:
    """Mealie >= 1.x sends `*TimeSeconds`; older versions free text ("1 hour 30 minutes")."""
    if isinstance(seconds, int | float) and seconds > 0:
        return min(int(round(seconds / 60)), 10_000)
    if isinstance(text, str) and text.strip():
        total = 0.0
        for n, unit in _DUR.findall(text):
            v = float(n.replace(",", "."))
            total += v * 60 if unit.lower()[0] in "ht" else v
        if total:
            return min(int(round(total)), 10_000)
        if text.strip().isdigit():
            return min(int(text.strip()), 10_000)
    return None


def times(m: dict) -> tuple[int | None, int | None]:
    prep = _minutes(m.get("prepTimeSeconds"), m.get("prepTime"))
    cook = _minutes(m.get("performTimeSeconds"), m.get("performTime") or m.get("cookTime"))
    if cook is None:
        total = _minutes(m.get("totalTimeSeconds"), m.get("totalTime"))
        if total is not None:
            cook = max(total - (prep or 0), 0) or None
            if cook is None and prep is None:
                cook = total
    return prep, cook


def _servings(m: dict) -> int:
    for k in ("recipeServings", "recipeYieldQuantity"):
        v = m.get(k)
        if isinstance(v, int | float) and v >= 1:
            return max(1, min(int(round(v)), 100))
    found = re.search(r"\d+", str(m.get("recipeYield") or ""))
    return max(1, min(int(found.group()), 100)) if found else 4


def _source(m: dict) -> tuple[str | None, str | None]:
    url = (m.get("orgURL") or "").strip()
    if not url.startswith(("http://", "https://")) or len(url) > 1000:
        return None, None
    host = urlparse(url).hostname or ""
    return url, (host.removeprefix("www.")[:120] or None)


def recipe_in(m: dict) -> RecipeIn:
    """A full Mealie recipe (GET /api/recipes/{slug}) as a PantryNanny recipe."""
    lines = []
    for i in m.get("recipeIngredient") or []:
        raw = (
            i
            if isinstance(i, str)
            else (i.get("display") or i.get("originalText") or i.get("note") or "")
        )
        raw = " ".join(str(raw).split())[:300]
        if raw:
            lines.append(IngredientIn(raw=raw))
    steps = []
    for s in m.get("recipeInstructions") or []:
        text = s if isinstance(s, str) else (s.get("text") or "")
        if str(text).strip():
            steps.append(str(text).strip())
    prep, cook = times(m)
    url, site = _source(m)
    cats = _names(m.get("recipeCategory"))[:MAX_TAGS]
    return RecipeIn(
        title=(m.get("name") or "Untitled").strip()[:200] or "Untitled",
        description=(m.get("description") or "").strip()[:2000] or None,
        servings=_servings(m),
        prep_min=prep,
        cook_min=cook,
        instructions=steps[:80],
        tags=_names(m.get("tags"))[:MAX_TAGS],
        categories=cats,
        course=from_tags(cats),  # None: worked out from title/tags/ingredients on create
        source_url=url,
        source_name=site,
        ingredients=lines[:100],
    )


class MealieClient:
    def __init__(
        self, base_url: str, token: str, client: httpx.AsyncClient, timeout_s: float = 20.0
    ):
        self.base = base_url.rstrip("/")
        self.headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
        self.client = client
        self.timeout = timeout_s

    async def _json(self, path: str, params: dict | None = None) -> dict:
        r = await self.client.get(
            f"{self.base}{path}", params=params, headers=self.headers, timeout=self.timeout
        )
        r.raise_for_status()
        return r.json()

    async def page(self, page: int) -> dict:
        return await self._json(
            "/api/recipes",
            {"page": page, "perPage": PER_PAGE, "orderBy": "name", "orderDirection": "asc"},
        )

    async def recipe(self, slug: str) -> dict:
        return await self._json(f"/api/recipes/{slug}")

    async def image(self, recipe_id: str, limit: int) -> bytes | None:
        url = f"{self.base}/api/media/recipes/{recipe_id}/images/original.webp"
        async with self.client.stream("GET", url, headers=self.headers, timeout=self.timeout) as r:
            if r.status_code != 200:
                return None
            data = bytearray()
            async for chunk in r.aiter_bytes():
                data += chunk
                if len(data) > limit:
                    return None
            return bytes(data)


async def _find(s: AsyncSession, household_id: uuid.UUID, m: dict) -> Recipe | None:
    base = (Recipe.household_id == household_id, Recipe.deleted_at.is_(None))
    url, _ = _source(m)
    title = (m.get("name") or "").strip().lower()
    for cond in (
        Recipe.external_id == external_id(m),
        (Recipe.source_url == url) if url else None,
        func.lower(Recipe.title) == title if title else None,
    ):
        if cond is None:
            continue
        r = (
            await s.execute(
                select(Recipe)
                .where(
                    *base,
                    cond,
                    or_(Recipe.external_id.is_(None), Recipe.external_id == external_id(m)),
                )
                .order_by(Recipe.created_at, Recipe.id)
                .limit(1)
            )
        ).scalar_one_or_none()
        if r is not None:
            return r
    return None


COPY_SUFFIX = re.compile(r"\s*\(\d+\)$")


def base_title(title: str) -> str:
    """Mealie names a second recipe with the same name "Name (1)"."""
    return COPY_SUFFIX.sub("", title.strip()).strip().lower()


async def _copy_of(s: AsyncSession, household_id: uuid.UUID, m: dict) -> Recipe | None:
    """A recipe linked to another Mealie id that this one is a copy of: same source URL, or
    "Name (n)" of the same name where at most one side has a source URL."""
    url, _ = _source(m)
    name = base_title(m.get("name") or "")
    near = [Recipe.source_url == url] if url else []
    if name:  # narrowed in SQL, "(n)" checked below
        near.append(func.lower(Recipe.title).startswith(name, autoescape=True))
    if not near:
        return None
    rows = (
        await s.execute(
            select(Recipe).where(
                Recipe.household_id == household_id,
                Recipe.deleted_at.is_(None),
                Recipe.external_id.like("mealie:%"),
                Recipe.external_id != external_id(m),
                or_(*near),
            )
        )
    ).scalars()
    for r in rows:
        if url and r.source_url == url:
            return r
        if name and base_title(r.title) == name and not (url and r.source_url):
            return r
    return None


def _merge(r: Recipe, m: dict) -> bool:
    """Fill in what Mealie knows and the recipe lacks. True when something changed."""
    changed = False
    if r.external_id is None:
        r.external_id, changed = external_id(m), True
    cats = _names(m.get("recipeCategory"))
    merged_cats = list(dict.fromkeys([*(r.categories or []), *cats]))[:MAX_TAGS]
    if merged_cats != list(r.categories or []):
        r.categories, changed = merged_cats, True
    have = {t.lower() for t in r.tags or []}
    extra = [t for t in _names(m.get("tags")) if t.lower() not in have]
    if extra and len(r.tags or []) < MAX_TAGS:
        r.tags, changed = [*(r.tags or []), *extra][:MAX_TAGS], True
    if r.prep_min is None and r.cook_min is None:
        prep, cook = times(m)
        if prep is not None or cook is not None:
            r.prep_min, r.cook_min, changed = prep, cook, True
    if r.source_url is None:
        url, site = _source(m)
        if url:
            r.source_url, r.source_name, changed = url, r.source_name or site, True
    if r.course is None:
        course = from_tags(cats) or classify(
            r.title, [*cats, *(r.tags or [])], [i.name for i in r.ingredients]
        )
        if course:
            r.course, changed = course, True
    return changed


def _wants_image(r: Recipe, m: dict, replace: bool) -> bool:
    if not m.get("image"):
        return False
    local = bool(r.image_url and r.image_url.startswith(LOCAL_PREFIX))
    return replace or not local


async def run(
    sm: async_sessionmaker[AsyncSession],
    household_id: uuid.UUID,
    mealie: MealieClient,
    *,
    create: bool = True,
    images: bool = True,
    replace_images: bool = False,
    limit: int | None = None,
    upload_dir: str | None = None,
    progress: Callable[[MealieStats], None] | None = None,
) -> MealieStats:
    st = MealieStats()
    max_bytes = runtime.get_settings().image_download_max_bytes
    page, pages = 1, 1
    while page <= pages and (limit is None or st.seen < limit):
        data = await mealie.page(page)
        pages = int(data.get("total_pages") or data.get("totalPages") or 1)
        for m in data.get("items") or []:
            if limit is not None and st.seen >= limit:
                break
            st.seen += 1
            try:
                await _one(
                    sm,
                    household_id,
                    mealie,
                    m,
                    st,
                    create,
                    images,
                    replace_images,
                    max_bytes,
                    upload_dir,
                )
            except (httpx.HTTPError, ValidationError, ValueError, KeyError) as exc:
                st.failed += 1
                st.last_error = f"{m.get('slug')}: {type(exc).__name__}: {exc}"[:300]
                log.warning("mealie_import_failed", slug=m.get("slug"), error=type(exc).__name__)
            if progress and st.seen % 25 == 0:
                progress(st)
        page += 1
    log.info("mealie_import_done", **{k: v for k, v in st.public().items() if k != "last_error"})
    return st


async def _one(
    sm,
    household_id,
    mealie: MealieClient,
    m: dict,
    st: MealieStats,
    create,
    images,
    replace_images,
    max_bytes,
    upload_dir,
) -> None:
    async with sm() as s:
        r = await _find(s, household_id, m)
        if r is None and await _copy_of(s, household_id, m) is not None:
            st.duplicates += 1
            return
        rid = r.id if r is not None else None
        want_image = images and (r is None or _wants_image(r, m, replace_images))
    if rid is None and not create:
        st.skipped += 1
        return
    full = await mealie.recipe(m["slug"]) if rid is None else None
    photo = None
    if want_image:
        try:
            raw = await mealie.image(m["id"], max_bytes)
            photo = await store_image(raw, upload_dir) if raw else None
        except (httpx.HTTPError, InvalidImage):
            photo = None
        if photo is None:
            st.image_failed += 1
    async with sm() as s, s.begin():
        if rid is None:
            r = await svc.create_recipe(s, household_id, recipe_in({**m, **full}), None)
            r.external_id = external_id(m)
            st.created += 1
            changed = True
        else:
            r = await s.get(Recipe, rid, with_for_update=True)
            changed = _merge(r, m)
        if photo:
            old = r.image_url
            r.image_url = f"{LOCAL_PREFIX}{photo}"
            if old and old.startswith(LOCAL_PREFIX) and FILE_RE.match(old[len(LOCAL_PREFIX) :]):
                delete_image(old[len(LOCAL_PREFIX) :], upload_dir)
            st.images += 1
            changed = True
        if rid is not None:
            if changed:
                r.version += 1
                r.updated_at = datetime.now(UTC)
                st.updated += 1
            else:
                st.unchanged += 1
