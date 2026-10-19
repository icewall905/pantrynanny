import uuid

from fastapi import APIRouter, Depends, Response
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..errors import AppError, not_found
from ..models import Category, Product
from ..schemas.catalogue import CategoryIn, CategoryOut, CategoryPatch
from ..security import Principal, get_principal, now, require_admin

router = APIRouter(tags=["categories"])


async def _get(session: AsyncSession, household_id: uuid.UUID, cat_id: uuid.UUID) -> Category:
    cat = (
        await session.execute(
            select(Category)
            .where(
                Category.id == cat_id,
                Category.household_id == household_id,
                Category.deleted_at.is_(None),
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if cat is None:
        raise not_found("Category not found")
    return cat


@router.get("/categories", response_model=list[CategoryOut])
async def list_categories(
    include_deleted: bool = False,
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
):
    stmt = select(Category).where(Category.household_id == principal.household_id)
    if not include_deleted:
        stmt = stmt.where(Category.deleted_at.is_(None))
    rows = await session.execute(stmt.order_by(Category.sort_order, Category.name))
    return rows.scalars().all()


@router.post("/categories", response_model=CategoryOut, status_code=201)
async def create_category(
    body: CategoryIn,
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
):
    cat = Category(household_id=principal.household_id, **body.model_dump())
    session.add(cat)
    await session.commit()
    return cat


@router.patch("/categories/{cat_id}", response_model=CategoryOut)
async def patch_category(
    cat_id: uuid.UUID,
    body: CategoryPatch,
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
):
    cat = await _get(session, principal.household_id, cat_id)
    sent = body.model_fields_set
    if "name" in sent and body.name is None:
        raise AppError(422, "validation_error", "name cannot be null")
    for field in ("name", "icon", "color", "sort_order"):
        if field in sent:
            setattr(cat, field, getattr(body, field))
    await session.commit()
    await session.refresh(cat)
    return cat


@router.delete("/categories/{cat_id}", status_code=204)
async def delete_category(
    cat_id: uuid.UUID,
    principal: Principal = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    cat = await _get(session, principal.household_id, cat_id)
    await session.execute(
        update(Product)
        .where(Product.category_id == cat.id)
        .values(category_id=None, version=Product.version + 1)
    )
    cat.deleted_at = now()
    await session.commit()
    return Response(status_code=204)
