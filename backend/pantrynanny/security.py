"""Passwords, session tokens, CSRF, kiosk scope, roles and login rate limiting."""

import hashlib
import re
import secrets
import time
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import Depends, Request
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .db import get_sessionmaker
from .errors import AppError, forbidden
from .models import Session, User

COOKIE_NAME = "pn_session"
CSRF_HEADER = "x-pn-csrf"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
TOUCH_INTERVAL = timedelta(minutes=1)

TTL_BROWSER_SHORT = 12 * 3600
TTL_BROWSER_REMEMBER = 180 * 86400
TTL_DEVICE = 365 * 86400
TTL_KIOSK = 365 * 86400

ROLES = ("owner", "admin", "member")

# --------------------------------------------------------------------------- passwords/tokens

_hasher = PasswordHasher()
# Verified against when the user does not exist so timing does not reveal valid usernames.
_DUMMY_HASH = _hasher.hash("pantrynanny-dummy-password")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    try:
        return _hasher.verify(password_hash or _DUMMY_HASH, password) and password_hash is not None
    except (VerificationError, InvalidHashError):
        return False


def new_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def new_kiosk_code() -> str:
    return "".join(secrets.choice(_CODE_ALPHABET) for _ in range(8))


def now() -> datetime:
    return datetime.now(UTC)


# --------------------------------------------------------------------------- rate limiting


class RateLimiter:
    """Sliding-window failure counter held in process memory (single worker deployment)."""

    def __init__(self, limit: int, window_s: float):
        self.limit = limit
        self.window_s = window_s
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def _prune(self, key: str) -> deque[float]:
        q = self._hits[key]
        cutoff = time.monotonic() - self.window_s
        while q and q[0] < cutoff:
            q.popleft()
        if not q:
            self._hits.pop(key, None)
            return deque()
        return q

    def check(self, key: str) -> None:
        q = self._prune(key)
        if len(q) >= self.limit:
            retry = max(1, int(self.window_s - (time.monotonic() - q[0])))
            err = AppError(429, "rate_limited", "Too many attempts, try again later")
            err.headers = {"Retry-After": str(retry)}  # type: ignore[attr-defined]
            raise err

    def fail(self, key: str) -> None:
        self._prune(key)
        self._hits[key].append(time.monotonic())

    def reset(self, key: str | None = None) -> None:
        if key is None:
            self._hits.clear()
        else:
            self._hits.pop(key, None)


login_limiter = RateLimiter(limit=10, window_s=300)
kiosk_limiter = RateLimiter(limit=10, window_s=300)


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


# --------------------------------------------------------------------------- principal


@dataclass(frozen=True, slots=True)
class Principal:
    household_id: uuid.UUID
    session_id: uuid.UUID
    kind: str  # browser | device | kiosk
    via: str  # cookie | bearer
    user_id: uuid.UUID | None
    role: str | None
    username: str | None
    display_name: str | None
    device_name: str | None

    @property
    def is_kiosk(self) -> bool:
        return self.kind == "kiosk"

    @property
    def is_admin(self) -> bool:
        return self.role in ("owner", "admin")


_ID = r"[0-9a-fA-F-]{36}"
# (method set, compiled path) pairs a kiosk principal may call. Everything else is 403.
_KIOSK_ALLOW: list[tuple[frozenset[str], re.Pattern[str]]] = [
    (frozenset({"GET"}), re.compile(r"^/api/products$")),
    (frozenset({"GET"}), re.compile(rf"^/api/products/{_ID}$")),
    (frozenset({"GET"}), re.compile(r"^/api/products/by-barcode/.+$")),
    (frozenset({"POST"}), re.compile(rf"^/api/products/{_ID}/photo$")),
    (frozenset({"GET"}), re.compile(rf"^/api/inventory(/{_ID})?$")),
    (frozenset({"GET"}), re.compile(r"^/api/(locations|categories)$")),
    (frozenset({"GET"}), re.compile(r"^/api/shopping(/suggestions)?$")),
    (frozenset({"GET"}), re.compile(r"^/api/sync/(snapshot|changes)$")),
    (frozenset({"POST"}), re.compile(r"^/api/sync/ops$")),
    # session plumbing the kiosk client needs
    (frozenset({"GET"}), re.compile(r"^/api/(auth/me|settings)$")),
    (frozenset({"POST"}), re.compile(r"^/api/auth/logout$")),
]


def kiosk_allowed(method: str, path: str) -> bool:
    return any(method in m and p.match(path) for m, p in _KIOSK_ALLOW)


def _extract_token(request: Request) -> tuple[str, str] | None:
    auth = request.headers.get("authorization")
    if auth:
        scheme, _, value = auth.partition(" ")
        if scheme.lower() == "bearer" and value.strip():
            return value.strip(), "bearer"
        raise AppError(401, "unauthenticated", "Invalid authorization header")
    cookie = request.cookies.get(COOKIE_NAME)
    if cookie:
        return cookie, "cookie"
    return None


async def _touch_session(
    sm: async_sessionmaker[AsyncSession], session_id: uuid.UUID, ttl: int
) -> None:
    ts = now()
    async with sm() as s, s.begin():
        await s.execute(
            update(Session)
            .where(Session.id == session_id)
            .values(last_used_at=ts, expires_at=ts + timedelta(seconds=ttl))
        )


async def get_principal(
    request: Request, sm: async_sessionmaker[AsyncSession] = Depends(get_sessionmaker)
) -> Principal:
    found = _extract_token(request)
    if found is None:
        raise AppError(401, "unauthenticated", "Not authenticated")
    token, via = found
    async with sm() as s:
        row = (
            await s.execute(
                select(Session, User)
                .outerjoin(User, User.id == Session.user_id)
                .where(Session.token_hash == hash_token(token))
            )
        ).first()
    if row is None:
        raise AppError(401, "unauthenticated", "Invalid or expired session")
    sess, user = row
    ts = now()
    if sess.revoked_at is not None or sess.expires_at <= ts:
        raise AppError(401, "unauthenticated", "Invalid or expired session")
    if sess.kind != "kiosk" and (user is None or not user.is_active or user.deleted_at):
        raise AppError(401, "unauthenticated", "Invalid or expired session")

    unsafe = request.method not in SAFE_METHODS
    if via == "cookie" and unsafe and request.headers.get(CSRF_HEADER) != "1":
        raise forbidden("Missing CSRF header", "csrf_required")

    principal = Principal(
        household_id=sess.household_id,
        session_id=sess.id,
        kind=sess.kind,
        via=via,
        user_id=user.id if user else None,
        role=user.role if user else None,
        username=user.username if user else None,
        display_name=user.display_name if user else None,
        device_name=sess.device_name,
    )
    if principal.is_kiosk and not kiosk_allowed(request.method, request.url.path):
        raise forbidden("Not allowed for kiosk devices", "kiosk_forbidden")

    if ts - sess.last_used_at >= TOUCH_INTERVAL:
        await _touch_session(sm, sess.id, sess.ttl_seconds)
    return principal


async def require_admin(principal: Principal = Depends(get_principal)) -> Principal:
    if not principal.is_admin:
        raise forbidden("Administrator role required", "admin_required")
    return principal


async def create_session(
    db: AsyncSession,
    *,
    household_id: uuid.UUID,
    user_id: uuid.UUID | None,
    kind: str,
    ttl_seconds: int,
    device_name: str | None = None,
    platform: str | None = None,
) -> str:
    """Create a session row and return the *plain* token (only its hash is stored)."""
    token = new_token()
    ts = now()
    db.add(
        Session(
            token_hash=hash_token(token),
            user_id=user_id,
            household_id=household_id,
            kind=kind,
            device_name=device_name,
            platform=platform,
            ttl_seconds=ttl_seconds,
            created_at=ts,
            last_used_at=ts,
            expires_at=ts + timedelta(seconds=ttl_seconds),
        )
    )
    await db.flush()
    return token
