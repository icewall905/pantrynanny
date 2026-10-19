"""Extract a schema.org Recipe from a web page's JSON-LD. The page is untrusted input: only plain
text is kept (tags stripped, lengths capped), nothing from it is ever executed or rendered as HTML.
"""

import html
import json
import re
from dataclasses import dataclass, field

SCRIPT_RE = re.compile(
    r"<script[^>]+type\s*=\s*[\"']application/ld\+json[\"'][^>]*>(.*?)</script>",
    re.IGNORECASE | re.DOTALL,
)
TAG_RE = re.compile(r"<[^>]+>")
DURATION_RE = re.compile(
    r"^P(?:(?P<d>\d+)D)?(?:T(?:(?P<h>\d+(?:\.\d+)?)H)?(?:(?P<m>\d+(?:\.\d+)?)M)?(?:[\d.]+S)?)?$",
    re.IGNORECASE,
)
TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
SITE_RE = re.compile(
    r"<meta[^>]+property\s*=\s*[\"']og:site_name[\"'][^>]+content\s*=\s*[\"']([^\"']+)", re.I
)

MAX_INGREDIENTS = 100
MAX_STEPS = 60


@dataclass
class RecipeDraft:
    title: str
    description: str | None = None
    servings: int | None = None
    prep_min: int | None = None
    cook_min: int | None = None
    ingredients: list[str] = field(default_factory=list)
    instructions: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    image_url: str | None = None
    source_name: str | None = None


def text(v: object, limit: int = 2000) -> str:
    if v is None:
        return ""
    if isinstance(v, (list, tuple)):
        v = " ".join(text(x, limit) for x in v)
    s = html.unescape(TAG_RE.sub(" ", str(v)))
    return re.sub(r"\s+", " ", s).strip()[:limit]


def minutes(v: object) -> int | None:
    if not isinstance(v, str):
        return None
    m = DURATION_RE.match(v.strip())
    if not m or not any(m.groupdict().values()):
        return None
    total = int(m.group("d") or 0) * 1440 + float(m.group("h") or 0) * 60 + float(m.group("m") or 0)
    return int(round(total)) if 0 < total < 10_000 else None


def servings(v: object) -> int | None:
    if isinstance(v, list):
        for x in v:
            if (s := servings(x)) is not None:
                return s
        return None
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return int(v) if 0 < v <= 100 else None
    m = re.search(r"\d+", text(v, 100))
    return int(m.group()) if m and 0 < int(m.group()) <= 100 else None


def _types(node: dict) -> set[str]:
    t = node.get("@type")
    return {str(x).lower() for x in (t if isinstance(t, list) else [t])}


def _walk(node: object, depth: int = 0):
    if depth > 6:
        return
    if isinstance(node, list):
        for x in node:
            yield from _walk(x, depth + 1)
    elif isinstance(node, dict):
        if "recipe" in _types(node):
            yield node
        for k in ("@graph", "mainEntity", "itemListElement", "item"):
            if k in node:
                yield from _walk(node[k], depth + 1)


def _steps(v: object, depth: int = 0) -> list[str]:
    if depth > 4 or v is None:
        return []
    if isinstance(v, str):
        # some sites put every step in one string separated by newlines
        parts = [text(p, 1500) for p in re.split(r"\n+|<br\s*/?>|</p>", v)]
        return [p for p in parts if p]
    if isinstance(v, list):
        return [s for x in v for s in _steps(x, depth + 1)]
    if isinstance(v, dict):
        if "itemListElement" in v:  # HowToSection
            return _steps(v["itemListElement"], depth + 1)
        return [s for s in [text(v.get("text") or v.get("name"), 1500)] if s]
    return []


def _image(v: object) -> str | None:
    if isinstance(v, list):
        v = v[0] if v else None
    if isinstance(v, dict):
        v = v.get("url") or v.get("contentUrl")
    s = text(v, 1000)
    return s if s.startswith(("https://", "http://")) else None


def extract(page: str) -> RecipeDraft | None:
    page = page[:3_000_000]
    for block in SCRIPT_RE.findall(page):
        try:
            data = json.loads(html.unescape(block.strip()) if "&quot;" in block else block.strip())
        except ValueError:
            continue
        for node in _walk(data):
            title = text(node.get("name"), 200)
            ingredients = [
                s for s in (text(x, 300) for x in (node.get("recipeIngredient") or [])) if s
            ][:MAX_INGREDIENTS]
            if not title or not ingredients:
                continue
            keywords = node.get("keywords")
            tags = (
                [text(k, 40) for k in keywords.split(",")]
                if isinstance(keywords, str)
                else [text(k, 40) for k in keywords]
                if isinstance(keywords, list)
                else []
            )
            for extra in ("recipeCategory", "recipeCuisine"):
                v = node.get(extra)
                tags += [text(v, 40)] if isinstance(v, str) else [text(x, 40) for x in v or []]
            prep, cook = minutes(node.get("prepTime")), minutes(node.get("cookTime"))
            if prep is None and cook is None:
                cook = minutes(node.get("totalTime"))
            site = SITE_RE.search(page)
            return RecipeDraft(
                title=title,
                description=text(node.get("description"), 1000) or None,
                servings=servings(node.get("recipeYield")),
                prep_min=prep,
                cook_min=cook,
                ingredients=ingredients,
                instructions=_steps(node.get("recipeInstructions"))[:MAX_STEPS],
                tags=list(dict.fromkeys(t for t in tags if t))[:12],
                image_url=_image(node.get("image")),
                source_name=text(site.group(1), 100) if site else None,
            )
    return None
