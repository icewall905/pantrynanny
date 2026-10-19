"""Async SQLAlchemy engine/session plumbing."""

from collections.abc import AsyncIterator

from fastapi import Request
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from .config import Settings


def make_engine(settings: Settings) -> AsyncEngine:
    return create_async_engine(
        settings.database_url, pool_size=10, max_overflow=20, pool_pre_ping=True
    )


def make_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False, autoflush=False)


def get_sessionmaker(request: Request) -> async_sessionmaker[AsyncSession]:
    return request.app.state.sessionmaker


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """Request-scoped session. Handlers commit explicitly; otherwise changes are rolled back."""
    async with request.app.state.sessionmaker() as session:
        yield session
