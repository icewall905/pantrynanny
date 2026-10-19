"""Effective AI configuration: environment defaults (PN_AI_*) overridden by the admin UI.

The overrides live in ``app_settings['ai']`` and are re-read at most every few seconds, so the API
and the worker pick up changes without a restart.
"""

import time
from dataclasses import asdict, dataclass, field, replace
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..config import Settings
from ..models import AppSetting

SETTINGS_KEY = "ai"
REFRESH_S = 10.0
FEATURES = ("chat", "recipes", "photo")


@dataclass(frozen=True)
class AIConfig:
    enabled: bool = True  # master switch; also needs a base_url
    base_url: str = ""
    api_key: str = ""
    model: str = ""  # empty: first model from /models
    timeout_s: float = 90.0
    max_tokens: int = 0  # 0: per-feature defaults
    temperature: float | None = None  # None: per-feature defaults
    # Ask "thinking" models (Qwen3, Gemma 3 thinking, ...) to answer directly. Sent as
    # chat_template_kwargs, which llama.cpp and vLLM understand and other servers ignore.
    disable_thinking: bool = False
    features: dict[str, bool] = field(default_factory=lambda: dict.fromkeys(FEATURES, True))

    @property
    def active(self) -> bool:
        return self.enabled and bool(self.base_url.strip())

    def feature(self, name: str) -> bool:
        return self.active and self.features.get(name, True)


EDITABLE = {
    "enabled": bool,
    "base_url": str,
    "api_key": str,
    "model": str,
    "timeout_s": float,
    "max_tokens": int,
    "temperature": float,
    "disable_thinking": bool,
    "features": dict,
}


def from_env(settings: Settings) -> AIConfig:
    return AIConfig(
        base_url=settings.ai_base_url.strip(),
        api_key=settings.ai_api_key,
        model=settings.ai_model.strip(),
        timeout_s=settings.ai_timeout_s,
    )


def merge(base: AIConfig, overrides: dict[str, Any]) -> AIConfig:
    kw: dict[str, Any] = {}
    for k, v in (overrides or {}).items():
        if k not in EDITABLE or v is None:
            continue
        if k == "features" and isinstance(v, dict):
            kw[k] = {**base.features, **{f: bool(v[f]) for f in FEATURES if f in v}}
        else:
            kw[k] = v
    return replace(base, **kw)


async def load_overrides(session: AsyncSession) -> dict[str, Any]:
    row = await session.scalar(select(AppSetting).where(AppSetting.key == SETTINGS_KEY))
    return dict(row.value) if row and isinstance(row.value, dict) else {}


class ConfigSource:
    """Caches the merged config; ``get`` refreshes from the database every REFRESH_S seconds."""

    def __init__(self, settings: Settings):
        self.env = from_env(settings)
        self._cfg = self.env
        self._overrides: dict[str, Any] = {}
        self._at = 0.0

    @property
    def current(self) -> AIConfig:
        return self._cfg

    @property
    def overrides(self) -> dict[str, Any]:
        return dict(self._overrides)

    def set(self, overrides: dict[str, Any]) -> AIConfig:
        self._overrides = dict(overrides)
        self._cfg = merge(self.env, self._overrides)
        self._at = time.monotonic()
        return self._cfg

    async def refresh(
        self, sm: async_sessionmaker[AsyncSession] | None, *, force: bool = False
    ) -> AIConfig:
        if sm is None or (not force and time.monotonic() - self._at < REFRESH_S):
            return self._cfg
        try:
            async with sm() as session:
                return self.set(await load_overrides(session))
        except Exception:  # database hiccup: keep the last known config, AI stays optional
            self._at = time.monotonic()
            return self._cfg


def public_dict(cfg: AIConfig) -> dict[str, Any]:
    d = asdict(cfg)
    d["api_key"] = None
    d["has_api_key"] = bool(cfg.api_key)
    d["active"] = cfg.active
    return d
