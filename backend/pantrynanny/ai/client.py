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

log = get_logger("pantrynanny.ai")

PROBE_TTL_S = 60.0
MODEL_TTL_S = 300.0
FEATURE_TTL_S = 600.0
_THINK = re.compile(r"<think>.*?</think>", re.DOTALL)


def ai_unavailable(detail: str = "AI assistant is not available") -> AppError:
    return AppError(503, "ai_unavailable", detail)


class ToolsUnsupported(Exception):
    """The endpoint rejected the ``tools`` parameter."""


class AIClient:
    def __init__(self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None):
        self.settings = settings
        self._transport = transport
        self._model: str | None = None
        self._model_at = 0.0
        self._probe: tuple[float, bool] | None = None
        self._probe_lock = asyncio.Lock()
        self._no_tools_until = 0.0
        self._no_json_mode_until = 0.0

    # ------------------------------------------------------------------ config
    @property
    def enabled(self) -> bool:
        return bool(self.settings.ai_base_url.strip())

    @property
    def base_url(self) -> str:
        return self.settings.ai_base_url.strip().rstrip("/")

    @property
    def tools_supported(self) -> bool:
        return time.monotonic() >= self._no_tools_until

    @property
    def json_mode_supported(self) -> bool:
        return time.monotonic() >= self._no_json_mode_until

    def _headers(self) -> dict[str, str]:
        h = {"Content-Type": "application/json"}
        if self.settings.ai_api_key:
            h["Authorization"] = f"Bearer {self.settings.ai_api_key}"
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
        if self.settings.ai_model.strip():
            return self.settings.ai_model.strip()
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
        async with self._probe_lock:
            now = time.monotonic()
            if not force and self._probe and now - self._probe[0] < PROBE_TTL_S:
                return self._probe[1]
            ok = False
            try:
                async with asyncio.timeout(timeout):
                    async with self._http(timeout) as c:
                        r = await c.get("/models")
                    ok = r.status_code < 500
            except (TimeoutError, httpx.HTTPError):
                ok = False
            self._probe = (time.monotonic(), ok)
            return ok

    # ------------------------------------------------------------------ chat
    async def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        json_mode: bool = False,
        max_tokens: int = 2048,
        temperature: float = 0.3,
    ) -> dict[str, Any]:
        """Return the assistant message dict (``content`` normalised to a string)."""
        if not self.enabled:
            raise ai_unavailable("AI assistant is disabled")
        model = await self.detect_model()
        if not model:
            raise ai_unavailable("AI endpoint unreachable")
        body: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": False,
        }
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"
        if json_mode and self.json_mode_supported:
            body["response_format"] = {"type": "json_object"}
        try:
            async with self._http(self.settings.ai_timeout_s) as c:
                r = await c.post("/chat/completions", json=body)
        except httpx.TimeoutException as e:
            raise ai_unavailable("AI endpoint timed out") from e
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
                )
            if tools and r.status_code in (400, 422, 501):
                self._no_tools_until = time.monotonic() + FEATURE_TTL_S
                raise ToolsUnsupported
            log.warning("ai_http_error", status=r.status_code)
            raise ai_unavailable(f"AI endpoint returned HTTP {r.status_code}")
        try:
            choice = r.json()["choices"][0]
            msg = dict(choice["message"])
        except (ValueError, KeyError, IndexError, TypeError) as e:
            raise AppError(
                502, "ai_bad_response", "AI endpoint returned an invalid response"
            ) from e
        content = msg.get("content")
        msg["content"] = _THINK.sub("", content).strip() if isinstance(content, str) else ""
        msg["finish_reason"] = choice.get("finish_reason")
        return msg


def get_ai_client(app: FastAPI) -> AIClient:
    client = getattr(app.state, "ai_client", None)
    if client is None:
        client = AIClient(app.state.settings)
        app.state.ai_client = client
    return client
