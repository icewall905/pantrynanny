"""Admin: AI endpoint settings (overrides of PN_AI_*) and a connectivity test."""

from typing import Any
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..ai import diagnostics
from ..ai.client import AIClient, get_ai_client
from ..ai.config import FEATURES, SETTINGS_KEY, load_overrides, public_dict
from ..db import get_session
from ..models import AppSetting
from ..security import Principal, require_admin

router = APIRouter(prefix="/admin/ai", tags=["admin"])


class AIPatch(BaseModel):
    """All fields optional; ``null`` means "use the environment default" for that field."""

    enabled: bool | None = None
    base_url: str | None = Field(default=None, max_length=300)
    api_key: str | None = Field(default=None, max_length=500)  # "" clears a stored key
    model: str | None = Field(default=None, max_length=200)
    timeout_s: float | None = Field(default=None, ge=5, le=600)
    max_tokens: int | None = Field(default=None, ge=0, le=32768)
    temperature: float | None = Field(default=None, ge=0, le=2)
    disable_thinking: bool | None = None
    features: dict[str, bool] | None = None

    @field_validator("base_url")
    @classmethod
    def _url(cls, v: str | None) -> str | None:
        if v is None or v.strip() == "":
            return v
        u = urlparse(v.strip())
        if u.scheme not in ("http", "https") or not u.netloc:
            raise ValueError("must be an http(s) URL, e.g. http://192.0.2.20:8080/v1")
        return v.strip().rstrip("/")

    @field_validator("features")
    @classmethod
    def _features(cls, v: dict[str, bool] | None) -> dict[str, bool] | None:
        if v is not None and set(v) - set(FEATURES):
            raise ValueError(f"features: allowed keys are {', '.join(FEATURES)}")
        return v


def _view(ai: AIClient) -> dict[str, Any]:
    ov = ai.source.overrides
    return {
        "config": public_dict(ai.cfg),
        "env": public_dict(ai.source.env),
        "overridden": sorted(k for k, v in ov.items() if v is not None),
        "api_key_source": "db" if ov.get("api_key") else ("env" if ai.source.env.api_key else None),
        "features": list(FEATURES),
    }


def _apply(current: dict[str, Any], patch: AIPatch) -> dict[str, Any]:
    new = dict(current)
    for k, v in patch.model_dump(exclude_unset=True).items():
        if k == "api_key" and v == "":
            new.pop("api_key", None)  # clear the stored key (falls back to env)
        elif v is None:
            new.pop(k, None)
        elif k == "features":
            new["features"] = {**(new.get("features") or {}), **v}
        else:
            new[k] = v
    return new


@router.get("")
async def get_ai(request: Request, principal: Principal = Depends(require_admin)):
    ai = get_ai_client(request.app)
    await ai.refresh(request.app.state.sessionmaker, force=True)
    return _view(ai)


@router.patch("")
async def patch_ai(
    body: AIPatch,
    request: Request,
    principal: Principal = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    ai = get_ai_client(request.app)
    new = _apply(await load_overrides(session), body)
    stmt = insert(AppSetting).values(key=SETTINGS_KEY, value=new)
    await session.execute(
        stmt.on_conflict_do_update(index_elements=["key"], set_={"value": stmt.excluded.value})
    )
    await session.commit()
    ai.source.set(new)
    await ai.refresh(None, force=True)  # reset model/probe caches when the endpoint changed
    return _view(ai)


@router.post("/test")
async def test_ai(
    request: Request,
    body: AIPatch | None = None,
    vision: bool = True,
    principal: Principal = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    """Test the saved settings, or (with a body) unsaved form values layered on top of them."""
    ai = get_ai_client(request.app)
    probe = AIClient(ai.settings, transport=ai._transport)
    candidate = _apply(await load_overrides(session), body) if body else ai.source.overrides
    probe.source.set(candidate)
    return await diagnostics.run(probe, vision=vision)
