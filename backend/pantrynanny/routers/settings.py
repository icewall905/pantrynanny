from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..schemas.admin import SettingsOut, SettingsPatch
from ..security import Principal, get_principal, require_admin
from ..services.households import get_household_settings

router = APIRouter(tags=["settings"])


@router.get("/settings", response_model=SettingsOut)
async def read_settings(
    principal: Principal = Depends(get_principal), session: AsyncSession = Depends(get_session)
):
    return await get_household_settings(session, principal.household_id)


@router.patch("/settings", response_model=SettingsOut)
async def update_settings(
    body: SettingsPatch,
    principal: Principal = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    row = await get_household_settings(session, principal.household_id)
    for key in body.model_fields_set:
        value = getattr(body, key)
        if value is not None:
            setattr(row, key, value)
    await session.commit()
    return row
