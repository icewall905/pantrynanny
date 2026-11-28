"""Read a recipe off a page that has no schema.org data, using the household's own model.

Small blogs, page builders and video pages show the ingredients and the method as plain text and
never say so in JSON-LD, which is why an import from them saves nothing. The local model is asked
to copy them out as they are written, and then every line it returns is checked against the page's
own words: a line that is not on the page is dropped, and an answer that is mostly not on the page
is thrown away entirely. Nothing the model makes up can reach a recipe that way.
"""

import html
import re

from ..ai.service import parse_json_object

DROP_RE = re.compile(r"<(script|style|noscript|svg)\b[^>]*>.*?</\1>", re.I | re.S)
TAG_RE = re.compile(r"<[^>]+>")
SPACE_RE = re.compile(r"[ \t\r\f\v]+")
TOKEN_RE = re.compile(r"[^\W_]+", re.UNICODE)
MAX_PAGE_CHARS = 14_000
MAX_LINES = 100
# an answer is believed only if at least this much of it is really on the page
KEEP_RATIO = 0.5

PROMPT = """You read a cooking page and copy its recipe out exactly as written.
Return JSON: {"ingredients": ["<one line as written>", ...], "instructions": ["<one step>", ...]}
Rules: copy the page's own words; never invent, translate or tidy anything; keep the quantities and
units as they are; one ingredient per line; split the method into its steps; if the page has no
ingredient list or no method, return an empty list for that. No other text."""


def page_text(page: str) -> str:
    """The readable words of a page: no scripts, styles or tags, whitespace collapsed."""
    text = DROP_RE.sub(" ", page)
    text = TAG_RE.sub(" ", text)
    text = html.unescape(text).replace("\xa0", " ")
    text = SPACE_RE.sub(" ", text)
    return re.sub(r"\n{2,}", "\n", text).strip()[:MAX_PAGE_CHARS]


def tokens(text: str) -> list[str]:
    return TOKEN_RE.findall(html.unescape(text).lower())


def on_page(line: str, page_tokens: list[str]) -> bool:
    """True when every word of the line is on the page in that order (entities/hyphens aside)."""
    words = tokens(line)
    if not words:
        return False
    it = iter(page_tokens)
    return all(w in it for w in words)


def verified_lines(lines: list[str], page_tokens: list[str]) -> tuple[list[str], int]:
    """The lines that are really on the page, and how many were dropped because they are not."""
    keep = [line for line in lines if on_page(line, page_tokens)]
    return keep, len(lines) - len(keep)


def _lines(value: object, limit: int) -> list[str]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return []
    return [str(x).strip()[:limit] for x in value if str(x).strip()][:MAX_LINES]


def believe(
    candidates: dict[str, list[str]], page_tokens: list[str]
) -> dict[str, list[str]] | None:
    """Keep only what is on the page; give up when the answer is mostly not from it."""
    total = sum(len(v) for v in candidates.values())
    if not total:
        return None
    out: dict[str, list[str]] = {}
    kept = 0
    for key, lines in candidates.items():
        good, _ = verified_lines(lines, page_tokens)
        out[key] = good
        kept += len(good)
    if kept < KEEP_RATIO * total or not (out.get("ingredients") or out.get("instructions")):
        return None
    return out


async def read(ai, page: str) -> dict[str, list[str]] | None:
    """Ask the model for the recipe on this page; None when its answer is not from the page."""
    text = page_text(page)
    if len(text) < 200:  # a page with nothing to read is not worth a request
        return None
    message = await ai.chat(
        [
            {"role": "system", "content": PROMPT},
            {"role": "user", "content": text},
        ],
        json_mode=True,
        max_tokens=2048,
        temperature=0.0,
    )
    try:
        data = parse_json_object(str(message.get("content") or ""))
    except ValueError:
        return None
    candidates = {
        "ingredients": _lines(data.get("ingredients"), 300),
        "instructions": _lines(data.get("instructions"), 2000),
    }
    return believe(candidates, tokens(text))
