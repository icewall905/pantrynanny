import uuid

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..db import get_session, get_sessionmaker
from ..schemas.catalogue import (
    BarcodeAddIn,
    BarcodeOut,
    ByBarcodeOut,
    MergeIn,
    ProductCreate,
    ProductOut,
    ProductPatch,
    Symbology,
)
from ..security import Principal, get_principal
from ..services import products as svc
from ._common import if_match_required

router = APIRouter(tags=["products"])


@router.get("/products", response_model=list[ProductOut])
async def search_products(
    response: Response,
    q: str | None = Query(default=None, max_length=200),
    status: str | None = Query(default=None, pattern="^(known|unknown|needs_review)$"),
    category_id: uuid.UUID | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
):
    rows = await svc.list_products(
        session,
        principal.household_id,
        q=q,
        status=status,
        category_id=category_id,
        limit=limit,
        offset=offset,
    )
    return [svc.product_out(p) for p in rows]


@router.post("/products", response_model=ProductOut, status_code=201)
async def create_product(
    body: ProductCreate,
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
):
    p = await svc.create_product(session, principal.household_id, body)
    await session.commit()
    return svc.product_out(
        await svc.get_product(session, principal.household_id, p.id, refresh=True)
    )


# Declared before /products/{id} so "by-barcode" is never treated as an id.
@router.get("/products/by-barcode/{raw:path}", response_model=ByBarcodeOut)
async def by_barcode(
    raw: str,
    request: Request,
    lookup: bool = True,
    symbology: Symbology | None = None,
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
    sm: async_sessionmaker[AsyncSession] = Depends(get_sessionmaker),
):
    """Resolve a scanned code to a product. Never changes stock."""
    svc.normalize_input(raw, symbology)  # 422 for blank / oversized codes
    status, product, source, nb = await svc.resolve_barcode(
        session,
        sm,
        principal.household_id,
        raw,
        symbology,
        lookup=lookup,
        timeout_s=request.app.state.settings.lookup_timeout_s,
    )
    return ByBarcodeOut(
        status=status,
        product=svc.product_out(product) if product else None,
        source=source,
        barcode=BarcodeOut(code=nb.code, raw=nb.raw, symbology=nb.symbology),
        valid=nb.valid,
    )


@router.get("/products/{product_id}", response_model=ProductOut)
async def get_product(
    product_id: uuid.UUID,
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
):
    return svc.product_out(await svc.get_product(session, principal.household_id, product_id))


@router.patch("/products/{product_id}", response_model=ProductOut)
async def patch_product(
    product_id: uuid.UUID,
    body: ProductPatch,
    version: int = Depends(if_match_required),
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
):
    p = await svc.patch_product(session, principal.household_id, product_id, body, version)
    await session.commit()
    return svc.product_out(p)


@router.delete("/products/{product_id}", status_code=204)
async def delete_product(
    product_id: uuid.UUID,
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
):
    await svc.soft_delete_product(session, principal.household_id, product_id)
    await session.commit()
    return Response(status_code=204)


@router.post("/products/{product_id}/barcodes", response_model=ProductOut, status_code=201)
async def add_barcode(
    product_id: uuid.UUID,
    body: BarcodeAddIn,
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
):
    p = await svc.add_barcode(session, principal.household_id, product_id, body.raw, body.symbology)
    await session.commit()
    return svc.product_out(p)


@router.delete("/products/{product_id}/barcodes/{code:path}", response_model=ProductOut)
async def remove_barcode(
    product_id: uuid.UUID,
    code: str,
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
):
    p = await svc.remove_barcode(session, principal.household_id, product_id, code)
    await session.commit()
    return svc.product_out(p)


@router.post("/products/{product_id}/merge", response_model=ProductOut)
async def merge_product(
    product_id: uuid.UUID,
    body: MergeIn,
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
):
    p = await svc.merge_products(session, principal.household_id, product_id, body.into_id)
    await session.commit()
    return svc.product_out(p)
