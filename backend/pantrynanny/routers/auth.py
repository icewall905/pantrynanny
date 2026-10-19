import uuid

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..errors import AppError
from ..logging import get_logger
from ..models import Household, KioskCode, Session, User
from ..schemas.admin import KioskLoginIn, LoginIn, MeOut, TokenIn, TokenOut
from ..security import (
    COOKIE_NAME,
    TTL_BROWSER_REMEMBER,
    TTL_BROWSER_SHORT,
    TTL_DEVICE,
    TTL_KIOSK,
    Principal,
    RateLimiter,
    averify_password,
    client_ip,
    create_session,
    get_principal,
    hash_token,
    kiosk_limiter,
    login_limiter,
    now,
)
from ..services.households import get_household_settings

router = APIRouter(tags=["auth"])
log = get_logger()
ip_limiter = RateLimiter(limit=60, window_s=300)


async def build_me(
    session: AsyncSession, principal_household: uuid.UUID, user: User | None, kiosk: bool
) -> MeOut:
    hh = await session.get(Household, principal_household)
    settings = await get_household_settings(session, principal_household)
    return MeOut.model_validate(
        {"user": user, "household": hh, "kiosk": kiosk, "settings": settings},
        from_attributes=True,
    )


async def _authenticate(
    session: AsyncSession, request: Request, username: str, password: str
) -> User:
    key = f"{client_ip(request)}|{username.strip().lower()}"
    ip = client_ip(request)
    ip_limiter.acquire(ip)
    try:
        login_limiter.acquire(key)
    except AppError:
        ip_limiter.release(ip)
        raise
    user = (
        await session.execute(select(User).where(User.username == username.strip().lower()))
    ).scalar_one_or_none()
    ok = await averify_password(user.password_hash if user else None, password)
    if not ok or user is None or not user.is_active or user.deleted_at is not None:
        log.info("login_failed", ip=client_ip(request))
        raise AppError(401, "invalid_credentials", "Wrong username or password")
    login_limiter.reset(key)
    ip_limiter.release(ip)
    return user


def _set_cookie(request: Request, response: Response, token: str, ttl: int) -> None:
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=ttl,
        httponly=True,
        samesite="lax",
        secure=request.url.scheme == "https",
        path="/",
    )


@router.post("/auth/login", response_model=MeOut)
async def login(
    body: LoginIn,
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_session),
):
    user = await _authenticate(session, request, body.username, body.password)
    ttl = TTL_BROWSER_REMEMBER if body.remember else TTL_BROWSER_SHORT
    token = await create_session(
        session,
        household_id=user.household_id,
        user_id=user.id,
        kind="browser",
        ttl_seconds=ttl,
        device_name=(request.headers.get("user-agent") or "")[:100] or None,
    )
    me = await build_me(session, user.household_id, user, False)
    await session.commit()
    _set_cookie(request, response, token, ttl)
    return me


@router.post("/auth/token", response_model=TokenOut)
async def issue_token(
    body: TokenIn, request: Request, session: AsyncSession = Depends(get_session)
):
    user = await _authenticate(session, request, body.username, body.password)
    token = await create_session(
        session,
        household_id=user.household_id,
        user_id=user.id,
        kind="device",
        ttl_seconds=TTL_DEVICE,
        device_name=body.device_name,
        platform=body.platform,
    )
    me = await build_me(session, user.household_id, user, False)
    await session.commit()
    return TokenOut(token=token, me=me)


@router.post("/auth/kiosk", response_model=MeOut)
async def kiosk_login(
    body: KioskLoginIn,
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_session),
):
    ip = client_ip(request)
    kiosk_limiter.acquire(ip)
    code = (
        await session.execute(
            select(KioskCode)
            .where(
                KioskCode.code_hash == hash_token(body.code.strip().upper()),
                KioskCode.used_at.is_(None),
                KioskCode.expires_at > now(),
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if code is None:
        raise AppError(401, "invalid_code", "Invalid or expired pairing code")
    kiosk_limiter.release(ip)
    code.used_at = now()
    token = await create_session(
        session,
        household_id=code.household_id,
        user_id=None,
        kind="kiosk",
        ttl_seconds=TTL_KIOSK,
        device_name=code.name,
        platform="kiosk",
    )
    me = await build_me(session, code.household_id, None, True)
    await session.commit()
    _set_cookie(request, response, token, TTL_KIOSK)
    return me


@router.post("/auth/logout")
async def logout(
    response: Response,
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
):
    await session.execute(
        update(Session).where(Session.id == principal.session_id).values(revoked_at=now())
    )
    await session.commit()
    response.delete_cookie(COOKIE_NAME, path="/")
    return {"ok": True}


@router.get("/auth/me", response_model=MeOut)
async def me(
    principal: Principal = Depends(get_principal), session: AsyncSession = Depends(get_session)
):
    user = await session.get(User, principal.user_id) if principal.user_id else None
    return await build_me(session, principal.household_id, user, principal.is_kiosk)
