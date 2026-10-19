"""Admin connectivity test for the AI endpoint: models list, a text answer and an image answer.

Every step reports what actually came back (latency, finish_reason, reasoning, error text), so a
misbehaving endpoint can be diagnosed from the web UI instead of from server logs.
"""

import base64
import io
import time
from typing import Any

import httpx
from PIL import Image

from ..errors import AppError
from .client import AIClient


def _probe_image() -> str:
    """96x96 PNG, left half red and right half blue; a vision model should say 'red and blue'."""
    img = Image.new("RGB", (96, 96), (220, 30, 30))
    img.paste((30, 60, 220), (48, 0, 96, 96))
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def _ms(t0: float) -> int:
    return int((time.monotonic() - t0) * 1000)


def _from_msg(msg: dict[str, Any], t0: float) -> dict[str, Any]:
    reasoning = msg.get("reasoning_content") or msg.get("reasoning") or ""
    return {
        "ok": bool(msg.get("content")),
        "ms": _ms(t0),
        "answer": (msg.get("content") or "")[:300],
        "finish_reason": msg.get("finish_reason"),
        "reasoning_chars": len(reasoning) if isinstance(reasoning, str) else 0,
        "retried_without_thinking": bool(msg.get("retried_without_thinking")),
        "error": None,
    }


def _err(t0: float, e: Exception) -> dict[str, Any]:
    detail = e.detail if isinstance(e, AppError) else f"{type(e).__name__}: {e}"
    return {"ok": False, "ms": _ms(t0), "answer": None, "error": detail}


async def run(client: AIClient, *, vision: bool = True) -> dict[str, Any]:
    cfg = client.cfg
    out: dict[str, Any] = {"base_url": client.base_url, "model": None, "steps": {}}
    if not cfg.active:
        out["steps"]["models"] = {"ok": False, "error": "AI is disabled or no endpoint URL is set"}
        return out

    t0 = time.monotonic()
    try:
        async with client._http(min(cfg.timeout_s, 10.0)) as c:
            r = await c.get("/models")
        ids = [m.get("id") for m in (r.json().get("data") or []) if isinstance(m, dict)]
        out["steps"]["models"] = {
            "ok": r.status_code < 400,
            "ms": _ms(t0),
            "status": r.status_code,
            "models": [i for i in ids if i][:30],
            "error": None if r.status_code < 400 else r.text[:200],
        }
    except (httpx.HTTPError, ValueError, AttributeError) as e:
        out["steps"]["models"] = _err(t0, e)
        return out

    out["model"] = await client.detect_model()
    t0 = time.monotonic()
    try:
        msg = await client.chat(
            [{"role": "user", "content": "Reply with exactly one word: OK"}],
            max_tokens=256,
            temperature=0,
        )
        out["steps"]["text"] = _from_msg(msg, t0)
    except Exception as e:  # report, never raise: this is a diagnostic
        out["steps"]["text"] = _err(t0, e)

    if vision:
        t0 = time.monotonic()
        content = [
            {
                "type": "text",
                "text": "Which two colours fill this image? Answer in at most 5 words.",
            },
            {"type": "image_url", "image_url": {"url": _probe_image()}},
        ]
        try:
            msg = await client.chat(
                [{"role": "user", "content": content}], max_tokens=256, temperature=0
            )
            step = _from_msg(msg, t0)
            ans = (step["answer"] or "").lower()
            step["looks_right"] = any(w in ans for w in ("red", "rød", "blue", "blå"))
            out["steps"]["vision"] = step
        except Exception as e:
            out["steps"]["vision"] = _err(t0, e)
    return out
