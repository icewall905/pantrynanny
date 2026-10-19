"""Households, users and first-run seed data."""

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..errors import AppError
from ..models import Category, Household, HouseholdSettings, Location, User
from ..security import hash_password

DEFAULT_LOCATIONS = [
    ("Køleskab", "refrigerator", False),
    ("Fryser", "snowflake", False),
    ("Spisekammer", "warehouse", True),
    ("Køkkenskab", "cooking-pot", False),
    ("Andet", "package", False),
]
DEFAULT_CATEGORIES = [
    ("Mejeri", "milk", "#60a5fa"),
    ("Kød & fisk", "beef", "#f87171"),
    ("Frugt & grønt", "apple", "#4ade80"),
    ("Brød & bagværk", "croissant", "#fbbf24"),
    ("Kolonial", "wheat", "#d6a35c"),
    ("Frost", "snowflake", "#38bdf8"),
    ("Drikkevarer", "cup-soda", "#2dd4bf"),
    ("Snacks & slik", "candy", "#f472b6"),
    ("Krydderier", "flask-conical", "#fb923c"),
    ("Husholdning", "spray-can", "#94a3b8"),
    ("Personlig pleje", "bath", "#c084fc"),
    ("Andet", "package", "#a1a1aa"),
]


async def create_household(session: AsyncSession, name: str) -> Household:
    hh = Household(name=name)
    session.add(hh)
    await session.flush()
    session.add(HouseholdSettings(household_id=hh.id))
    for i, (loc_name, icon, is_default) in enumerate(DEFAULT_LOCATIONS):
        session.add(
            Location(
                household_id=hh.id, name=loc_name, icon=icon, sort_order=i, is_default=is_default
            )
        )
    for i, (cat_name, icon, color) in enumerate(DEFAULT_CATEGORIES):
        session.add(
            Category(household_id=hh.id, name=cat_name, icon=icon, color=color, sort_order=i)
        )
    await session.flush()
    return hh


async def get_household_settings(session: AsyncSession, household_id: uuid.UUID):
    row = await session.get(HouseholdSettings, household_id)
    if row is None:
        row = HouseholdSettings(household_id=household_id)
        session.add(row)
        await session.flush()
    return row


async def create_user(
    session: AsyncSession,
    *,
    household_id: uuid.UUID,
    username: str,
    display_name: str,
    role: str,
    password: str,
) -> User:
    username = username.strip().lower()
    exists = await session.scalar(select(User.id).where(User.username == username))
    if exists:
        raise AppError(409, "username_taken", "Username already in use")
    user = User(
        household_id=household_id,
        username=username,
        display_name=display_name.strip(),
        role=role,
        password_hash=hash_password(password),
    )
    session.add(user)
    await session.flush()
    return user


async def count_households(session: AsyncSession) -> int:
    return await session.scalar(select(func.count()).select_from(Household)) or 0
