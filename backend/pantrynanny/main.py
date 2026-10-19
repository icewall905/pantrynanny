"""Application factory.

Production: ``uvicorn pantrynanny.main:create_app --factory --host 127.0.0.1 --port 8000
--no-access-log`` behind nginx (the app emits its own structured access log).
``pantrynanny.main:app`` is also provided for convenience.
"""

import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.types import ASGIApp, Message, Receive, Scope, Send
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from . import __version__
from .config import Settings, get_settings
from .db import make_engine, make_sessionmaker
from .errors import install_error_handlers
from .logging import configure_logging, get_logger
from .routers import (
    admin_ai,
    admin_catalogue,
    ai,
    auth,
    categories,
    dashboard,
    devices,
    export,
    ha,
    health,
    inventory,
    locations,
    media,
    products,
    settings,
    shopping,
    stats,
    sync,
    users,
)

log = get_logger("pantrynanny.access")


class BodyLimitMiddleware:
    """Reject oversized request bodies (Content-Length and streamed) with 413."""

    def __init__(self, app: ASGIApp, json_limit: int, upload_limit: int):
        self.app = app
        self.json_limit = json_limit
        self.upload_limit = upload_limit

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = dict(scope["headers"])
        ctype = headers.get(b"content-type", b"").decode("latin-1").lower()
        limit = self.upload_limit if ctype.startswith("multipart/") else self.json_limit
        declared = headers.get(b"content-length")
        too_big = False
        if declared and declared.isdigit() and int(declared) > limit:
            too_big = True

        received = 0
        sent_response = False

        async def limited_receive() -> Message:
            nonlocal received
            msg = await receive()
            if msg["type"] == "http.request":
                received += len(msg.get("body", b""))
                if received > limit:
                    raise _TooLarge
            return msg

        async def guarded_send(msg: Message) -> None:
            nonlocal sent_response
            if msg["type"] == "http.response.start":
                sent_response = True
            await send(msg)

        async def reject() -> None:
            body = b'{"detail":"Request body too large","code":"payload_too_large"}'
            await send(
                {
                    "type": "http.response.start",
                    "status": 413,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"content-length", str(len(body)).encode()),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": body})

        if too_big:
            await reject()
            return
        try:
            await self.app(scope, limited_receive, guarded_send)
        except _TooLarge:
            if not sent_response:
                await reject()


class _TooLarge(Exception):
    pass


class AccessLogMiddleware:
    """Structured access log. Logs path only (never query string, headers or cookies)."""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request_id = uuid.uuid4().hex[:12]
        structlog.contextvars.bind_contextvars(request_id=request_id)
        start = time.perf_counter()
        status = 500

        async def send_wrapper(msg: Message) -> None:
            nonlocal status
            if msg["type"] == "http.response.start":
                status = msg["status"]
                msg.setdefault("headers", []).append((b"x-request-id", request_id.encode()))
            await send(msg)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            client = scope.get("client")
            log.info(
                "request",
                method=scope["method"],
                path=scope["path"],
                status=status,
                ms=round((time.perf_counter() - start) * 1000, 1),
                ip=client[0] if client else None,
            )
            structlog.contextvars.clear_contextvars()


def create_app(settings_override: Settings | None = None) -> FastAPI:
    cfg = settings_override or get_settings()
    configure_logging(cfg.log_level, cfg.log_format)
    engine = make_engine(cfg)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        log.info("startup", version=__version__)
        yield
        await engine.dispose()

    app = FastAPI(
        title="PantryNanny API",
        version=__version__,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
        redoc_url=None,
        lifespan=lifespan,
    )
    app.state.settings = cfg
    app.state.engine = engine
    app.state.sessionmaker = make_sessionmaker(engine)
    install_error_handlers(app)

    for module in (
        health,
        auth,
        devices,
        users,
        settings,
        locations,
        categories,
        products,
        inventory,
        sync,
        shopping,
        dashboard,
        ai,
        media,
        export,
        stats,
        admin_catalogue,
        admin_ai,
        ha,
    ):
        app.include_router(module.router, prefix="/api")

    # Middleware order: last added = outermost.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cfg.cors_origin_list,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "If-Match", "X-PN-CSRF"],
        expose_headers=["X-Request-Id", "X-Total-Count", "X-Next-Before"],
    )
    app.add_middleware(
        BodyLimitMiddleware, json_limit=cfg.max_json_body, upload_limit=cfg.max_upload_body
    )
    app.add_middleware(AccessLogMiddleware)
    trusted = cfg.trusted_proxy_list
    app.add_middleware(ProxyHeadersMiddleware, trusted_hosts=trusted if trusted != ["*"] else "*")
    return app


def __getattr__(name: str):  # lazily build `app` so importing the module has no side effects
    if name == "app":
        global app
        app = create_app()
        return app
    raise AttributeError(name)
