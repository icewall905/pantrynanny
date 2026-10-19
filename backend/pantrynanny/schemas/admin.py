from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from .common import ORM, Role


class SettingsOut(ORM):
    locale: Literal["da", "en"]
    allow_negative_stock: bool
    expiry_soon_days: int
    auto_shopping_low_stock: bool
    remove_mode_timeout_min: int
    scan_rearm_ms: int


class SettingsPatch(BaseModel):
    locale: Literal["da", "en"] | None = None
    allow_negative_stock: bool | None = None
    expiry_soon_days: int | None = Field(default=None, ge=0, le=365)
    auto_shopping_low_stock: bool | None = None
    remove_mode_timeout_min: int | None = Field(default=None, ge=1, le=240)
    scan_rearm_ms: int | None = Field(default=None, ge=250, le=3000)


class UserOut(ORM):
    id: UUID
    username: str
    display_name: str
    role: str


class UserAdminOut(UserOut):
    is_active: bool
    created_at: datetime
    deleted_at: datetime | None


class UserCreate(BaseModel):
    username: str = Field(min_length=2, max_length=64, pattern=r"^[A-Za-z0-9_.@-]+$")
    display_name: str = Field(min_length=1, max_length=100)
    role: Role = "member"
    password: str = Field(min_length=8, max_length=200)


class UserPatch(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=100)
    role: Role | None = None
    password: str | None = Field(default=None, min_length=8, max_length=200)
    is_active: bool | None = None


class HouseholdOut(ORM):
    id: UUID
    name: str


class MeOut(BaseModel):
    user: UserOut | None  # null for kiosk principals
    household: HouseholdOut
    kiosk: bool
    settings: SettingsOut


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=200)
    remember: bool = False


class TokenIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=200)
    device_name: str = Field(min_length=1, max_length=100)
    platform: str | None = Field(default=None, max_length=40)


class TokenOut(BaseModel):
    token: str
    me: MeOut


class KioskLoginIn(BaseModel):
    code: str = Field(min_length=4, max_length=32)


class KioskCodeIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class KioskCodeOut(BaseModel):
    code: str
    expires_at: datetime


class DeviceOut(BaseModel):
    id: UUID
    kind: str
    device_name: str | None
    platform: str | None
    user_id: UUID | None
    username: str | None
    created_at: datetime
    last_used_at: datetime
    expires_at: datetime
    current: bool
