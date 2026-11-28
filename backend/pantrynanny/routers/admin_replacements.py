"""Admin → Replacements: what recipes ask for that the house has under another name (or can
swap for), with optional suggestions from the AI assistant."""

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ..ai import service as ai_service
from ..ai.client import ai_unavailable, get_ai_client
from ..db import get_session
from ..security import Principal, require_admin
from ..services import replacements as svc

router = APIRouter(prefix="/admin", tags=["admin"])


class ReplacementsOut(BaseModel):
    misses: list[svc.Miss]
    substitutes: list[svc.SubstituteOut]


class SuggestIn(BaseModel):
    ingredients: list[str] | None = Field(default=None, max_length=200)  # None = top misses
    limit: int = Field(default=50, ge=1, le=200)
    locale: Literal["da", "en"] = "da"


class Suggestion(BaseModel):
    ingredient: str
    product_id: uuid.UUID
    product_name: str
    kind: svc.Kind
    reason: str = ""


class ApproveOut(BaseModel):
    result: Literal["alias", "substitute", "already"]


@router.get("/replacements", response_model=ReplacementsOut)
async def overview(
    principal: Principal = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    """Ingredients no product matches (most recipes first) and the approved stand-ins."""
    return ReplacementsOut(
        misses=await svc.misses(session, principal.household_id),
        substitutes=await svc.list_substitutes(session, principal.household_id),
    )


@router.post("/replacements/suggest", response_model=list[Suggestion])
async def suggest(
    body: SuggestIn,
    request: Request,
    principal: Principal = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    """Ask the AI assistant (feature "recipes") to pair missing ingredients with in-stock
    products. Nothing is saved: each suggestion is approved separately."""
    ai = get_ai_client(request.app)
    await ai.refresh(request.app.state.sessionmaker)
    if not ai.enabled:
        raise ai_unavailable("AI assistant is disabled")
    if not ai.feature("recipes"):
        raise ai_unavailable("AI feature 'recipes' is turned off in Admin → AI")
    if body.ingredients is None:
        misses = await svc.misses(session, principal.household_id, limit=body.limit)
        names = [m.example for m in misses]
    else:
        names = [n.strip()[:200] for n in body.ingredients if n.strip()][: body.limit]
    pantry = await svc.in_stock(session, principal.household_id)
    products = [(p.id, p.name) for p in pantry if p.total > 0]
    return await ai_service.suggest_replacements(ai, names, products, body.locale)


@router.post("/replacements", response_model=ApproveOut)
async def approve(
    body: svc.ApproveIn,
    principal: Principal = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    """`same`: the product gets the ingredient as an alias (recipes count it as "have").
    `swap`: the product stands in when the ingredient is not in the house ("swap")."""
    result = await svc.approve(session, principal.household_id, body)
    await session.commit()
    return ApproveOut(result=result)  # type: ignore[arg-type]


@router.delete("/replacements/{sid}", status_code=204)
async def remove(
    sid: uuid.UUID,
    principal: Principal = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    await svc.delete_substitute(session, principal.household_id, sid)
    await session.commit()
    return Response(status_code=204)
