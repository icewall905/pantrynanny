"""Uniform error bodies: ``{"detail": str, "code": str}``."""

from typing import Any

import asyncpg
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import DBAPIError, InterfaceError
from sqlalchemy.exc import TimeoutError as SQLTimeoutError
from starlette.exceptions import HTTPException as StarletteHTTPException

from .logging import get_logger


class AppError(Exception):
    def __init__(
        self, status_code: int, code: str, detail: str, extra: dict[str, Any] | None = None
    ):
        super().__init__(detail)
        self.status_code = status_code
        self.code = code
        self.detail = detail
        self.extra = extra or {}


def not_found(what: str = "Not found") -> AppError:
    return AppError(404, "not_found", what)


def forbidden(detail: str = "Forbidden", code: str = "forbidden") -> AppError:
    return AppError(403, code, detail)


def conflict(code: str, detail: str, **extra: Any) -> AppError:
    return AppError(409, code, detail, extra)


def _body(detail: str, code: str, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"detail": detail, "code": code, **(extra or {})}


_STATUS_CODES = {
    400: "bad_request",
    401: "unauthenticated",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    413: "payload_too_large",
    422: "validation_error",
    428: "precondition_required",
    429: "rate_limited",
}


_DB_DOWN_SQLSTATES = (
    "08",
    "57P0",
)  # connection exceptions; admin/crash shutdown, cannot connect now


def is_db_unavailable(exc: BaseException) -> bool:
    """True for failures that mean "the database cannot be reached right now" (restart, network,
    pool exhaustion) as opposed to a bug or a constraint violation."""
    seen: set[int] = set()
    cur: BaseException | None = exc
    while cur is not None and id(cur) not in seen:
        seen.add(id(cur))
        if isinstance(cur, OSError | SQLTimeoutError | asyncpg.PostgresConnectionError):
            return True
        if isinstance(cur, DBAPIError) and (
            cur.connection_invalidated or isinstance(cur, InterfaceError)
        ):
            return True
        state = getattr(cur, "sqlstate", None)
        if isinstance(state, str) and state.startswith(_DB_DOWN_SQLSTATES):
            return True
        cur = cur.__cause__ or getattr(cur, "orig", None) or cur.__context__
    return False


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError):
        return JSONResponse(
            _body(exc.detail, exc.code, exc.extra),
            status_code=exc.status_code,
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, exc: StarletteHTTPException):
        code = _STATUS_CODES.get(exc.status_code, "error")
        return JSONResponse(
            _body(str(exc.detail), code), status_code=exc.status_code, headers=exc.headers
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception):
        if is_db_unavailable(exc):
            # Clients treat 503 as "retry later" (e.g. while PostgreSQL restarts).
            get_logger().warning("db_unavailable", path=request.url.path, error=type(exc).__name__)
            return JSONResponse(
                _body("Database temporarily unavailable", "db_unavailable"),
                status_code=503,
                headers={"Retry-After": "5"},
            )
        # Never leak internals; the traceback goes to the structured log only.
        get_logger().error("unhandled_exception", path=request.url.path, exc_info=exc)
        return JSONResponse(_body("internal error", "internal"), status_code=500)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError):
        parts = []
        for err in exc.errors()[:10]:
            loc = ".".join(str(p) for p in err["loc"] if p != "body")
            parts.append(f"{loc}: {err['msg']}" if loc else err["msg"])
        return JSONResponse(
            _body("; ".join(parts) or "Invalid request", "validation_error"), status_code=422
        )
