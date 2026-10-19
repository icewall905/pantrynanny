from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

from .. import __version__
from ..ai.client import get_ai_client

router = APIRouter(tags=["health"])


@router.get("/health")
async def health(request: Request):
    """Unauthenticated liveness/readiness probe."""
    client = get_ai_client(request.app)
    if not client.enabled:
        ai = "disabled"
    else:
        ai = "ok" if await client.reachable(timeout=1.0) else "down"
    try:
        async with request.app.state.sessionmaker() as session:
            await session.execute(text("SELECT 1"))
    except Exception:
        return JSONResponse(
            {"status": "error", "db": "down", "version": __version__, "ai": ai}, status_code=503
        )
    return {"status": "ok", "db": "ok", "version": __version__, "ai": ai}
