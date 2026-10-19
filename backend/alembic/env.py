"""Async Alembic environment. URL from PN_DATABASE_URL."""

import asyncio

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine

from pantrynanny.config import get_settings
from pantrynanny.models import Base

config = context.config
target_metadata = Base.metadata


def _url() -> str:
    return config.attributes.get("url") or get_settings().database_url


def include_object(obj, name, type_, reflected, compare_to):
    # Expression/trigram indexes are created with raw SQL in the migration only.
    if type_ == "index" and reflected and compare_to is None:
        return not (name.endswith(("_trgm", "_pattern")))
    return True


def run_migrations_offline() -> None:
    context.configure(url=_url(), target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def _do_run(connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        include_object=include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    engine = create_async_engine(_url())
    async with engine.connect() as connection:
        await connection.run_sync(_do_run)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
