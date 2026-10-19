import uuid

from fastapi import APIRouter, Depends, Response
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..errors import AppError, forbidden, not_found
from ..models import Session, User
from ..schemas.admin import UserAdminOut, UserCreate, UserPatch
from ..security import Principal, ahash_password, now, require_admin
from ..services.households import create_user

router = APIRouter(tags=["users"])


def _check_can_manage(principal: Principal, target_role: str) -> None:
    if target_role == "owner" and principal.role != "owner":
        raise forbidden("Only an owner can manage owners", "owner_required")


async def _active_owner_count(session: AsyncSession, household_id: uuid.UUID) -> int:
    return (
        await session.scalar(
            select(func.count())
            .select_from(User)
            .where(
                User.household_id == household_id,
                User.role == "owner",
                User.is_active.is_(True),
                User.deleted_at.is_(None),
            )
        )
        or 0
    )


async def _get(session: AsyncSession, household_id: uuid.UUID, user_id: uuid.UUID) -> User:
    user = (
        await session.execute(
            select(User).where(
                User.id == user_id, User.household_id == household_id, User.deleted_at.is_(None)
            )
        )
    ).scalar_one_or_none()
    if user is None:
        raise not_found("User not found")
    return user


@router.get("/users", response_model=list[UserAdminOut])
async def list_users(
    principal: Principal = Depends(require_admin), session: AsyncSession = Depends(get_session)
):
    rows = await session.execute(
        select(User)
        .where(User.household_id == principal.household_id, User.deleted_at.is_(None))
        .order_by(User.created_at)
    )
    return rows.scalars().all()


@router.post("/users", response_model=UserAdminOut, status_code=201)
async def add_user(
    body: UserCreate,
    principal: Principal = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    _check_can_manage(principal, body.role)
    user = await create_user(
        session,
        household_id=principal.household_id,
        username=body.username,
        display_name=body.display_name,
        role=body.role,
        password=body.password,
    )
    await session.commit()
    return user


async def _revoke_sessions(session: AsyncSession, user_id: uuid.UUID) -> None:
    await session.execute(
        update(Session)
        .where(Session.user_id == user_id, Session.revoked_at.is_(None))
        .values(revoked_at=now())
    )


@router.patch("/users/{user_id}", response_model=UserAdminOut)
async def patch_user(
    user_id: uuid.UUID,
    body: UserPatch,
    principal: Principal = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    user = await _get(session, principal.household_id, user_id)
    _check_can_manage(principal, user.role)
    if body.role is not None:
        _check_can_manage(principal, body.role)
    demoting = (body.role is not None and body.role != "owner") or body.is_active is False
    if (
        user.role == "owner"
        and demoting
        and await _active_owner_count(session, principal.household_id) <= 1
    ):
        raise AppError(409, "last_owner", "The household needs at least one active owner")
    if body.display_name is not None:
        user.display_name = body.display_name.strip()
    if body.role is not None:
        user.role = body.role
    if body.is_active is not None:
        user.is_active = body.is_active
        if not body.is_active:
            await _revoke_sessions(session, user.id)
    if body.password is not None:
        user.password_hash = await ahash_password(body.password)
        await _revoke_sessions(session, user.id)
    await session.commit()
    return user


@router.delete("/users/{user_id}", status_code=204)
async def delete_user(
    user_id: uuid.UUID,
    principal: Principal = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    user = await _get(session, principal.household_id, user_id)
    _check_can_manage(principal, user.role)
    if user.id == principal.user_id:
        raise AppError(409, "cannot_delete_self", "You cannot delete your own account")
    if user.role == "owner" and await _active_owner_count(session, principal.household_id) <= 1:
        raise AppError(409, "last_owner", "The household needs at least one active owner")
    user.deleted_at = now()
    user.is_active = False
    await _revoke_sessions(session, user.id)
    await session.commit()
    return Response(status_code=204)
