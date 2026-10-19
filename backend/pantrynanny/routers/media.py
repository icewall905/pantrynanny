"""Product photos, provider refresh and (development fallback) media serving."""

import asyncio
import uuid

from fastapi import APIRouter, Depends, File, Request, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..db import get_session, get_sessionmaker
from ..errors import AppError, not_found
from ..logging import get_logger
from ..schemas.catalogue import ProductOut
from ..security import Principal, get_principal
from ..services import products as svc
from ..services.lookup import refresh_product
from ..services.lookup.media import (
    InvalidImage,
    delete_image,
    resolve_media_path,
    store_image,
)

log = get_logger()
router = APIRouter(tags=["media"])


async def _read_limited(file: UploadFile, limit: int) -> bytes:
    buf = bytearray()
    while chunk := await file.read(64 * 1024):
        buf.extend(chunk)
        if len(buf) > limit:
            raise AppError(413, "payload_too_large", f"Image exceeds {limit // (1024 * 1024)} MB")
    return bytes(buf)


@router.post("/products/{product_id}/photo", response_model=ProductOut)
async def upload_photo(
    product_id: uuid.UUID,
    request: Request,
    file: UploadFile = File(...),
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
):
    """Store a household photo (re-encoded to WebP, EXIF stripped). Locks the ``image`` field."""
    cfg = request.app.state.settings
    await svc.get_product(session, principal.household_id, product_id)  # 404 before reading body
    data = await _read_limited(file, cfg.upload_max_bytes)
    if not data:
        raise AppError(422, "invalid_image", "Empty file")
    try:
        name = await store_image(data, cfg.upload_dir)
    except InvalidImage as exc:
        raise AppError(422, "invalid_image", str(exc)) from exc
    try:
        p = await svc.get_product(
            session, principal.household_id, product_id, for_update=True, refresh=True
        )
        old = p.image_path
        p.image_path = name
        p.locked_fields = sorted({*(p.locked_fields or []), "image"})
        p.version += 1
        await session.flush()
        await session.commit()
    except Exception:
        await session.rollback()
        delete_image(name, cfg.upload_dir)
        raise
    delete_image(old, cfg.upload_dir)
    return svc.product_out(
        await svc.get_product(session, principal.household_id, product_id, refresh=True)
    )


@router.post("/products/{product_id}/refresh", response_model=ProductOut)
async def refresh(
    product_id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
    sm: async_sessionmaker[AsyncSession] = Depends(get_sessionmaker),
):
    """Re-run the external lookup now (ignores fresh cache, respects ``locked_fields``)."""
    await svc.get_product(session, principal.household_id, product_id)
    try:
        await asyncio.wait_for(
            refresh_product(sm, principal.household_id, product_id, budget_s=12.0), timeout=25.0
        )
    except TimeoutError:
        log.warning("refresh_timeout", product_id=str(product_id))
    return svc.product_out(
        await svc.get_product(session, principal.household_id, product_id, refresh=True)
    )


@router.get("/media/{name}", include_in_schema=False)
async def media(name: str, request: Request):
    """Dev fallback; nginx serves the upload directory directly in production."""
    path = resolve_media_path(name, request.app.state.settings.upload_dir)
    if path is None:
        raise not_found("Media not found")
    return FileResponse(
        path,
        media_type="image/webp",
        headers={
            "Cache-Control": "public, max-age=31536000, immutable",
            "X-Content-Type-Options": "nosniff",
        },
    )
