import uuid
from datetime import timedelta

from fastapi import APIRouter, Depends, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..errors import forbidden, not_found
from ..models import KioskCode, Session, User
from ..schemas.admin import DeviceOut, KioskCodeIn, KioskCodeOut
from ..security import Principal, hash_token, new_kiosk_code, now, require_admin

router = APIRouter(tags=["devices"])
KIOSK_CODE_TTL = timedelta(minutes=15)


@router.get("/devices", response_model=list[DeviceOut])
async def list_devices(
    principal: Principal = Depends(require_admin), session: AsyncSession = Depends(get_session)
):
    rows = await session.execute(
        select(Session, User.username)
        .outerjoin(User, User.id == Session.user_id)
        .where(
            Session.household_id == principal.household_id,
            Session.revoked_at.is_(None),
            Session.expires_at > now(),
        )
        .order_by(Session.last_used_at.desc())
    )
    return [
        DeviceOut(
            id=s.id,
            kind=s.kind,
            device_name=s.device_name,
            platform=s.platform,
            user_id=s.user_id,
            username=username,
            created_at=s.created_at,
            last_used_at=s.last_used_at,
            expires_at=s.expires_at,
            current=s.id == principal.session_id,
        )
        for s, username in rows.all()
    ]


@router.delete("/devices/{device_id}", status_code=204)
async def revoke_device(
    device_id: uuid.UUID,
    principal: Principal = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    row = (
        await session.execute(
            select(Session, User.role)
            .outerjoin(User, User.id == Session.user_id)
            .where(Session.id == device_id, Session.household_id == principal.household_id)
        )
    ).first()
    if row is None or row[0].revoked_at is not None:
        raise not_found("Device not found")
    if row[1] == "owner" and principal.role != "owner":
        raise forbidden("Only an owner can revoke an owner's devices", "owner_required")
    row[0].revoked_at = now()
    await session.commit()
    return Response(status_code=204)


@router.post("/devices/kiosk-codes", response_model=KioskCodeOut, status_code=201)
async def create_kiosk_code(
    body: KioskCodeIn,
    principal: Principal = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    code = new_kiosk_code()
    expires = now() + KIOSK_CODE_TTL
    session.add(
        KioskCode(
            household_id=principal.household_id,
            name=body.name,
            code_hash=hash_token(code),
            created_by=principal.user_id,
            expires_at=expires,
        )
    )
    await session.commit()
    return KioskCodeOut(code=code, expires_at=expires)
