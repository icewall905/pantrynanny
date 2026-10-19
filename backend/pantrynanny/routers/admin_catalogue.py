from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..errors import AppError
from ..security import Principal, require_admin
from ..services import admin as svc
from ..services.lookup.providers import PROVIDER_NAMES

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/catalogue")
async def catalogue(
    principal: Principal = Depends(require_admin), session: AsyncSession = Depends(get_session)
):
    return await svc.catalogue(session, principal.household_id)


@router.get("/lookups")
async def lookups(
    status: str | None = Query(default=None, pattern="^[a-z_]{3,16}$"),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    principal: Principal = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    if status and status not in svc.ATTEMPT_STATUSES:
        raise AppError(422, "validation_error", f"status must be one of {svc.ATTEMPT_STATUSES}")
    return await svc.list_lookups(
        session, principal.household_id, status=status, limit=limit, offset=offset
    )


class ProviderPatchItem(BaseModel):
    name: str
    enabled: bool | None = None
    priority: int | None = Field(default=None, ge=0, le=1000)
    api_key: str | None = Field(default=None, max_length=200)


class ProvidersPatch(BaseModel):
    providers: list[ProviderPatchItem] = Field(max_length=20)


@router.get("/providers")
async def providers(
    principal: Principal = Depends(require_admin), session: AsyncSession = Depends(get_session)
):
    return {"providers": await svc.provider_infos(session)}


@router.patch("/providers")
async def patch_providers(
    body: ProvidersPatch,
    principal: Principal = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    for p in body.providers:
        if p.name not in PROVIDER_NAMES:
            raise AppError(422, "unknown_provider", f"Unknown provider: {p.name}")
    await svc.update_providers(session, [p.model_dump(exclude_unset=True) for p in body.providers])
    await session.commit()
    return {"providers": await svc.provider_infos(session)}
