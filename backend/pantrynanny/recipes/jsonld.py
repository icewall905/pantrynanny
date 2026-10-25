"""Extract a schema.org Recipe from a web page's JSON-LD (or, failing that, its microdata). The
page is untrusted input: only plain text is kept (tags stripped, lengths capped), nothing from it
is ever executed or rendered as HTML.
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


def times(prep: int | None, cook: int | None, total: int | None) -> tuple[int | None, int | None]:
    """(prep, cook) so that prep + cook is the total time when the page says more in total
    ("Tid i alt 60 min"): the rest is counted as cooking."""
    if total and (prep or 0) + (cook or 0) < total:
        cook = total - (prep or 0)
    return prep, cook


MICRO_RECIPE = re.compile(r"itemtype\s*=\s*[\"']https?://schema\.org/Recipe[\"']", re.I)
MICRO_ATTR = re.compile(r"<(\w+)\b([^>]*\bitemprop\s*=\s*[\"']([A-Za-z]+)[\"'][^>]*)>", re.I)
MICRO_CONTENT = re.compile(r"\b(?:content|datetime)\s*=\s*[\"']([^\"']*)[\"']", re.I)


def _element_html(page: str, tag: str, start: int, limit: int = 60_000) -> str:
    """Inner HTML of the element whose start tag ends at `start` (nesting of `tag` counted)."""
    depth, pos = 1, start
    pat = re.compile(rf"<(/?){tag}\b[^>]*>", re.I)
    for m in pat.finditer(page, start, min(len(page), start + limit)):
        depth += -1 if m.group(1) else 1
        if depth == 0:
            return page[start : m.start()]
        pos = m.end()
    return page[start:pos]


def _microdata(page: str) -> RecipeDraft | None:
    """schema.org Recipe as microdata (itemprop attributes), e.g. valdemarsro.dk."""
    m = MICRO_RECIPE.search(page)
    if not m:
        return None
    props: dict[str, list[tuple[str, str]]] = {}  # prop -> [(tag, inner html or content)]
    for e in MICRO_ATTR.finditer(page, m.end()):
        tag, attrs, prop = e.group(1).lower(), e.group(2), e.group(3)
        if len(props.get(prop, [])) >= MAX_INGREDIENTS:
            continue
        c = MICRO_CONTENT.search(attrs)
        if c and tag in ("meta", "time", "link") or (c and prop.endswith("Time")):
            value = c.group(1)
        elif tag in ("meta", "img", "link"):
            value = ""
        else:
            value = _element_html(page, tag, e.end())
        props.setdefault(prop, []).append((tag, value))

    def first(prop: str, limit: int = 200) -> str:
        return next((t for _, v in props.get(prop, []) if (t := text(v, limit))), "")

    title = (
        next((text(v, 200) for tag, v in props.get("name", []) if tag in ("h1", "h2", "h3")), "")
        or first("headline")
        or first("name")
    )
    ingredients = [s for s in (text(v, 300) for _, v in props.get("recipeIngredient", [])) if s]
    if not ingredients:
        ingredients = [s for s in (text(v, 300) for _, v in props.get("ingredients", [])) if s]
    if not title or not ingredients:
        return None
    steps: list[str] = []
    for _, v in props.get("recipeInstructions", []):
        steps += _steps(re.sub(r"</(?:li|p|div|h\d)>", "\n", v, flags=re.I))
    tags = [text(t, 40) for t in first("keywords", 400).split(",")] + [
        text(v, 40) for _, v in props.get("recipeCategory", [])
    ]
    prep, cook = times(
        minutes(first("prepTime", 40)),
        minutes(first("cookTime", 40)),
        minutes(first("totalTime", 40)),
    )
    img = re.search(r"<img\b[^>]*\bitemprop\s*=\s*[\"']image[\"'][^>]*>", page[m.end() :], re.I)
    src = re.search(r"\bsrc\s*=\s*[\"']([^\"']+)", img.group(0)) if img else None
    image = src.group(1) if src else None
    site = SITE_RE.search(page)
    return RecipeDraft(
        title=title,
        description=first("description", 1000) or None,
        servings=servings(first("recipeYield", 100)),
        prep_min=prep,
        cook_min=cook,
        ingredients=ingredients[:MAX_INGREDIENTS],
        instructions=steps[:MAX_STEPS],
        tags=list(dict.fromkeys(t for t in tags if t))[:12],
        image_url=_image(image),
        source_name=text(site.group(1), 100) if site else None,
    )


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
            prep, cook = times(
                minutes(node.get("prepTime")),
                minutes(node.get("cookTime")),
                minutes(node.get("totalTime")),
            )
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
    return _microdata(page)
