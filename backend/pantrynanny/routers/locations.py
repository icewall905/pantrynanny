import uuid

from fastapi import APIRouter, Depends, Response
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..errors import AppError, conflict, not_found
from ..models import Location, Product, StockBatch
from ..schemas.catalogue import LocationIn, LocationOut, LocationPatch
from ..security import Principal, get_principal, now, require_admin

router = APIRouter(tags=["locations"])


async def _get(session: AsyncSession, household_id: uuid.UUID, loc_id: uuid.UUID) -> Location:
    loc = (
        await session.execute(
            select(Location)
            .where(
                Location.id == loc_id,
                Location.household_id == household_id,
                Location.deleted_at.is_(None),
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if loc is None:
        raise not_found("Location not found")
    return loc


async def _make_default(session: AsyncSession, household_id: uuid.UUID, loc_id: uuid.UUID):
    await session.execute(
        update(Location)
        .where(Location.household_id == household_id, Location.id != loc_id, Location.is_default)
        .values(is_default=False)
    )


@router.get("/locations", response_model=list[LocationOut])
async def list_locations(
    include_deleted: bool = False,
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
):
    stmt = select(Location).where(Location.household_id == principal.household_id)
    if not include_deleted:
        stmt = stmt.where(Location.deleted_at.is_(None))
    rows = await session.execute(stmt.order_by(Location.sort_order, Location.name))
    return rows.scalars().all()


@router.post("/locations", response_model=LocationOut, status_code=201)
async def create_location(
    body: LocationIn,
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
):
    loc = Location(household_id=principal.household_id, **body.model_dump(exclude={"is_default"}))
    session.add(loc)
    await session.flush()
    has_default = await session.scalar(
        select(Location.id).where(
            Location.household_id == principal.household_id,
            Location.is_default,
            Location.deleted_at.is_(None),
        )
    )
    if body.is_default or has_default is None:
        await _make_default(session, principal.household_id, loc.id)
        loc.is_default = True
    await session.commit()
    return loc


@router.patch("/locations/{loc_id}", response_model=LocationOut)
async def patch_location(
    loc_id: uuid.UUID,
    body: LocationPatch,
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
):
    loc = await _get(session, principal.household_id, loc_id)
    sent = body.model_fields_set
    if "name" in sent and body.name is None:
        raise AppError(422, "validation_error", "name cannot be null")
    if "is_default" in sent:
        if body.is_default:
            await _make_default(session, principal.household_id, loc.id)
            loc.is_default = True
        elif loc.is_default:
            raise AppError(422, "default_required", "Set another location as default instead")
    for field in ("name", "icon", "sort_order"):
        if field in sent and getattr(body, field) is not None:
            setattr(loc, field, getattr(body, field))
    if "icon" in sent and body.icon is None:
        loc.icon = None
    await session.commit()
    await session.refresh(loc)
    return loc


@router.delete("/locations/{loc_id}", status_code=204)
async def delete_location(
    loc_id: uuid.UUID,
    principal: Principal = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    loc = await _get(session, principal.household_id, loc_id)
    if loc.is_default:
        raise conflict("default_location", "The default location cannot be deleted")
    stocked = await session.scalar(
        select(func.count())
        .select_from(StockBatch)
        .where(StockBatch.location_id == loc.id, StockBatch.quantity != 0)
    )
    if stocked:
        raise conflict("location_not_empty", "Move the stock out of this location first")
    await session.execute(
        update(Product)
        .where(Product.default_location_id == loc.id)
        .values(default_location_id=None, version=Product.version + 1)
    )
    loc.deleted_at = now()
    await session.commit()
    return Response(status_code=204)
