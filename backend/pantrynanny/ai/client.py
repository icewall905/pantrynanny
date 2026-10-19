"""Thin async client for an OpenAI-compatible endpoint (llama.cpp style).

Everything is lazy: no network access at import or app start. A fresh ``httpx.AsyncClient`` is
used per call so there is nothing to close at shutdown.
"""

import asyncio
import re
import time
from typing import Any

import httpx
from fastapi import FastAPI

from ..config import Settings
from ..errors import AppError
from ..logging import get_logger
from .config import AIConfig, ConfigSource

log = get_logger("pantrynanny.ai")

PROBE_TTL_S = 60.0
MODEL_TTL_S = 300.0
FEATURE_TTL_S = 600.0
_THINK = re.compile(r"<think>.*?</think>", re.DOTALL)
_OPEN_THINK = re.compile(r"<think>.*\Z", re.DOTALL)  # reasoning cut off before </think>
NO_THINKING = {"enable_thinking": False}


def clean_content(content: object) -> str:
    """Visible answer text: drop <think> blocks, including one left open by a token limit."""
    if not isinstance(content, str):
        return ""
    return _OPEN_THINK.sub("", _THINK.sub("", content)).strip()


def ai_unavailable(detail: str = "AI assistant is not available") -> AppError:
    return AppError(503, "ai_unavailable", detail)


class ToolsUnsupported(Exception):
    """The endpoint rejected the ``tools`` parameter."""


class AIClient:
    def __init__(self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None):
        self.settings = settings
        self.source = ConfigSource(settings)
        self._transport = transport
        self._model: str | None = None
        self._model_at = 0.0
        self._probe: tuple[float, bool] | None = None
        self._probe_lock = asyncio.Lock()
        self._no_tools_until = 0.0
        self._no_json_mode_until = 0.0

    # ------------------------------------------------------------------ config
    @property
    def cfg(self) -> AIConfig:
        return self.source.current

    async def refresh(self, sm=None, *, force: bool = False) -> AIConfig:
        """Pick up admin-UI overrides (cached for a few seconds). Resets caches on change."""
        before = self.cfg
        cfg = await self.source.refresh(sm, force=force)
        key = (cfg.base_url, cfg.model, cfg.api_key)
        if key != (before.base_url, before.model, before.api_key):
            self._model, self._probe = None, None
            self._no_tools_until = self._no_json_mode_until = 0.0
        return cfg

    @property
    def enabled(self) -> bool:
        return self.cfg.active

    def feature(self, name: str) -> bool:
        return self.cfg.feature(name)

    @property
    def base_url(self) -> str:
        return self.cfg.base_url.strip().rstrip("/")

    @property
    def tools_supported(self) -> bool:
        return time.monotonic() >= self._no_tools_until

    @property
    def json_mode_supported(self) -> bool:
        return time.monotonic() >= self._no_json_mode_until

    def _headers(self) -> dict[str, str]:
        h = {"Content-Type": "application/json"}
        if self.cfg.api_key:
            h["Authorization"] = f"Bearer {self.cfg.api_key}"
        return h

    def _http(self, timeout: float) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self.base_url,
            headers=self._headers(),
            transport=self._transport,
            timeout=httpx.Timeout(timeout, connect=min(5.0, timeout)),
        )

    # ------------------------------------------------------------------ model/probe
    async def detect_model(self, timeout: float | None = None) -> str | None:  # noqa: ASYNC109
        if self.cfg.model.strip():
            return self.cfg.model.strip()
        if self._model and time.monotonic() - self._model_at < MODEL_TTL_S:
            return self._model
        try:
            async with self._http(timeout or 5.0) as c:
                r = await c.get("/models")
            r.raise_for_status()
            data = r.json().get("data") or []
        except (httpx.HTTPError, ValueError, AttributeError):
            return self._model
        # Prefer a canonical id over alias entries (llama.cpp lists aliases as extra models).
        canonical = [
            m for m in data if isinstance(m, dict) and not m.get("alias_of") and m.get("id")
        ]
        pick = (canonical or [m for m in data if isinstance(m, dict) and m.get("id")] or [None])[0]
        if pick:
            self._model, self._model_at = str(pick["id"]), time.monotonic()
        return self._model

    async def reachable(self, timeout: float = 1.0, *, force: bool = False) -> bool:  # noqa: ASYNC109
        """Cached (60 s) reachability probe; never blocks longer than ``timeout``."""
        if not self.enabled:
            return False
        now = time.monotonic()
        if not force and self._probe and now - self._probe[0] < PROBE_TTL_S:
            return self._probe[1]
        cached = self._probe[1] if self._probe else False
        try:
            # The lock wait is inside the timeout so a slow concurrent probe cannot stall callers.
            async with asyncio.timeout(timeout):
                async with self._probe_lock:
                    now = time.monotonic()
                    if not force and self._probe and now - self._probe[0] < PROBE_TTL_S:
                        return self._probe[1]
                    ok = False
                    try:
                        async with self._http(timeout) as c:
                            r = await c.get("/models")
                        ok = r.status_code < 500
                    except httpx.HTTPError:
                        ok = False
                    self._probe = (time.monotonic(), ok)
                    return ok
        except TimeoutError:
            if self._probe is None or time.monotonic() - self._probe[0] >= PROBE_TTL_S:
                self._probe = (time.monotonic(), False)
                return False
            return cached

    # ------------------------------------------------------------------ chat
    async def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        json_mode: bool = False,
        max_tokens: int = 2048,
        temperature: float = 0.3,
        _retry_empty: bool = True,
    ) -> dict[str, Any]:
        """Return the assistant message dict (``content`` normalised to a string)."""
        if not self.enabled:
            raise ai_unavailable("AI assistant is disabled")
        cfg = self.cfg
        model = await self.detect_model()
        if not model:
            raise ai_unavailable("AI endpoint unreachable")
        body: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": cfg.max_tokens or max_tokens,
            "temperature": cfg.temperature if cfg.temperature is not None else temperature,
            "stream": False,
        }
        if cfg.disable_thinking or not _retry_empty:
            body["chat_template_kwargs"] = NO_THINKING
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"
        if json_mode and self.json_mode_supported:
            body["response_format"] = {"type": "json_object"}
        started = time.monotonic()
        try:
            async with self._http(cfg.timeout_s) as c:
                r = await c.post("/chat/completions", json=body)
        except httpx.TimeoutException as e:
            raise ai_unavailable(
                f"AI endpoint did not answer within {cfg.timeout_s:.0f} s (raise the timeout in "
                "Admin → AI, or use a faster model)"
            ) from e
        except httpx.HTTPError as e:
            self._probe = (time.monotonic(), False)
            raise ai_unavailable("AI endpoint unreachable") from e

        if r.status_code >= 400:
            text = r.text[:300].lower()
            if tools and r.status_code in (400, 422, 501) and "tool" in text:
                self._no_tools_until = time.monotonic() + FEATURE_TTL_S
                raise ToolsUnsupported
            if "response_format" in body and r.status_code in (400, 422, 501):
                self._no_json_mode_until = time.monotonic() + FEATURE_TTL_S
                return await self.chat(
                    messages,
                    tools=tools,
                    json_mode=False,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    _retry_empty=_retry_empty,
                )
            if tools and r.status_code in (400, 422, 501):
                self._no_tools_until = time.monotonic() + FEATURE_TTL_S
                raise ToolsUnsupported
            log.warning("ai_http_error", status=r.status_code, body=r.text[:200])
            raise ai_unavailable(f"AI endpoint returned HTTP {r.status_code}: {r.text[:120]}")
        try:
            choice = r.json()["choices"][0]
            msg = dict(choice["message"])
        except (ValueError, KeyError, IndexError, TypeError) as e:
            raise AppError(
                502, "ai_bad_response", "AI endpoint returned an invalid response"
            ) from e
        msg["content"] = clean_content(msg.get("content"))
        msg["finish_reason"] = choice.get("finish_reason")
        reasoning = msg.get("reasoning_content") or msg.get("reasoning") or ""
        log.info(
            "ai_chat_done",
            model=model,
            ms=int((time.monotonic() - started) * 1000),
            finish=msg["finish_reason"],
            content_chars=len(msg["content"]),
            reasoning_chars=len(reasoning) if isinstance(reasoning, str) else 0,
        )
        if not msg["content"] and not msg.get("tool_calls"):
            # Typical for reasoning models: the whole token budget went into thinking
            # (reasoning_content / an unclosed <think>), so no answer was written.
            if _retry_empty:
                retried = await self.chat(
                    messages,
                    tools=tools,
                    json_mode=json_mode,
                    max_tokens=max(max_tokens * 2, 4096),
                    temperature=temperature,
                    _retry_empty=False,
                )
                retried["retried_without_thinking"] = True
                return retried
            raise AppError(
                502,
                "ai_empty_response",
                "The model returned no answer"
                + (
                    " (it used its token budget for reasoning)"
                    if reasoning or msg["finish_reason"] == "length"
                    else ""
                )
                + ". Try 'Disable thinking' or a higher token limit in Admin → AI.",
            )
        return msg


def get_ai_client(app: FastAPI) -> AIClient:
    client = getattr(app.state, "ai_client", None)
    if client is None:
        client = AIClient(app.state.settings)
        app.state.ai_client = client
    return client
