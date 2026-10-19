"""Optional read-only AI assistant. Every endpoint returns 503 ``ai_unavailable`` when the
endpoint is not configured or unreachable; nothing else in the app depends on it."""

from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..ai import service
from ..ai.client import AIClient, ai_unavailable, get_ai_client
from ..ai.schemas import (
    ChatIn,
    ChatOut,
    PhotoSuggestion,
    RecipesIn,
    RecipesOut,
    StatusOut,
)
from ..ai.tools import ToolContext
from ..db import get_session
from ..errors import forbidden
from ..logging import get_logger
from ..models import Category, Location
from ..security import Principal, RateLimiter, get_principal

router = APIRouter(prefix="/ai", tags=["ai"])
log = get_logger("pantrynanny.ai")

# 20 requests / minute / user (in memory; single worker deployment).
ai_limiter = RateLimiter(limit=20, window_s=60)


def _client(request: Request) -> AIClient:
    return get_ai_client(request.app)


def member_ai(feature: str):
    async def dep(
        request: Request, principal: Principal = Depends(get_principal)
    ) -> tuple[Principal, AIClient]:
        return await _member_ai(request, principal, feature)

    return dep


async def _member_ai(
    request: Request, principal: Principal, feature: str
) -> tuple[Principal, AIClient]:
    if principal.is_kiosk:
        raise forbidden("Not allowed for kiosk devices", "kiosk_forbidden")
    ai = _client(request)
    await ai.refresh(request.app.state.sessionmaker)
    if not ai.enabled:
        raise ai_unavailable("AI assistant is disabled")
    if not ai.feature(feature):
        raise ai_unavailable(f"AI feature '{feature}' is turned off in Admin → AI")
    key = str(principal.user_id or principal.session_id)
    ai_limiter.check(key)
    ai_limiter.fail(key)
    return principal, ai


def _ctx(request: Request, session: AsyncSession, principal: Principal) -> ToolContext:
    tz = ZoneInfo(request.app.state.settings.timezone)
    return ToolContext(session, principal.household_id, datetime.now(tz).date())


@router.get("/status", response_model=StatusOut)
async def status(request: Request, principal: Principal = Depends(get_principal)):
    ai = _client(request)
    await ai.refresh(request.app.state.sessionmaker)
    features = {f: ai.feature(f) for f in ("chat", "recipes", "photo")}
    if not ai.enabled:
        return StatusOut(enabled=False, reachable=False, model=None, features=features)
    reachable = await ai.reachable(timeout=1.0)
    model = await ai.detect_model(timeout=1.0) if reachable else None
    return StatusOut(enabled=True, reachable=reachable, model=model, features=features)


@router.post("/chat", response_model=ChatOut)
async def chat(
    body: ChatIn,
    request: Request,
    dep: tuple[Principal, AIClient] = Depends(member_ai("chat")),
    session: AsyncSession = Depends(get_session),
):
    principal, ai = dep
    log.debug("ai_chat", user=str(principal.user_id), messages=len(body.messages))
    ctx = _ctx(request, session, principal)
    locs = (
        (
            await session.execute(
                select(Location.name).where(
                    Location.household_id == principal.household_id, Location.deleted_at.is_(None)
                )
            )
        )
        .scalars()
        .all()
    )
    return await service.chat(ai, ctx, body.messages, body.locale, list(locs))


@router.post("/recipes", response_model=RecipesOut)
async def recipes(
    body: RecipesIn,
    request: Request,
    dep: tuple[Principal, AIClient] = Depends(member_ai("recipes")),
    session: AsyncSession = Depends(get_session),
):
    principal, ai = dep
    log.debug("ai_recipes", user=str(principal.user_id), count=body.count)
    items, model = await service.recipes(
        ai, _ctx(request, session, principal), body.prompt, body.count, body.locale
    )
    return RecipesOut(recipes=items, model=model)


@router.post("/identify-photo", response_model=PhotoSuggestion)
async def identify_photo(
    request: Request,
    file: UploadFile = File(...),
    locale: str = Form("da"),
    dep: tuple[Principal, AIClient] = Depends(member_ai("photo")),
    session: AsyncSession = Depends(get_session),
):
    principal, ai = dep
    data = await file.read(service.MAX_IMAGE_BYTES + 1)
    cats = (
        (
            await session.execute(
                select(Category.name).where(
                    Category.household_id == principal.household_id, Category.deleted_at.is_(None)
                )
            )
        )
        .scalars()
        .all()
    )
    suggestion, _ = await service.identify_photo(
        ai, data, list(cats), "en" if locale == "en" else "da"
    )
    return suggestion
