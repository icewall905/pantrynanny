"""Test harness: real PostgreSQL, schema built by running the Alembic migration."""

import asyncio
import os
import tempfile
import uuid
from dataclasses import dataclass, field

import httpx
import pytest_asyncio
from alembic import command
from alembic.config import Config
from argon2 import PasswordHasher
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

TEST_DB_URL = os.environ.get(
    "PN_TEST_DATABASE_URL",
    "postgresql+asyncpg://postgres:pn@127.0.0.1:55433/pantrynanny_test",
)
assert TEST_DB_URL.rsplit("/", 1)[-1].endswith("_test"), "refusing to run against a non-test DB"
os.environ["PN_DATABASE_URL"] = TEST_DB_URL
os.environ["PN_LOG_LEVEL"] = "WARNING"
os.environ["PN_LOG_FORMAT"] = "console"
# Never reach real providers from tests; lookup tests enable them explicitly with mocked HTTP.
os.environ["PN_OFF_ENABLED"] = "false"
os.environ["PN_EANSEARCH_TOKEN"] = ""
os.environ["PN_UPLOAD_DIR"] = tempfile.mkdtemp(prefix="pn-uploads-")

from pantrynanny import security  # noqa: E402
from pantrynanny.config import Settings  # noqa: E402
from pantrynanny.main import create_app  # noqa: E402
from pantrynanny.services.households import create_household, create_user  # noqa: E402

# Cheap argon2 parameters keep the suite fast; production uses the library defaults.
security._hasher = PasswordHasher(time_cost=1, memory_cost=1024, parallelism=1)

PASSWORD = "correct-horse-battery"


def _alembic_upgrade() -> None:
    cfg = Config(os.path.join(os.path.dirname(__file__), "..", "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(os.path.dirname(__file__), "..", "alembic"))
    command.upgrade(cfg, "head")


@pytest_asyncio.fixture(scope="session", autouse=True)
async def _database():
    engine = create_async_engine(TEST_DB_URL)
    async with engine.begin() as conn:
        await conn.execute(text("DROP SCHEMA public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))
    await engine.dispose()
    await asyncio.to_thread(_alembic_upgrade)


@pytest_asyncio.fixture(scope="session")
async def app(_database):
    application = create_app(Settings(database_url=TEST_DB_URL, log_format="console"))
    yield application
    await application.state.engine.dispose()


@pytest_asyncio.fixture(autouse=True)
async def _clean(app):
    security.login_limiter.reset()
    security.kiosk_limiter.reset()
    from pantrynanny.routers.auth import ip_limiter

    ip_limiter.reset()
    yield
    async with app.state.engine.begin() as conn:
        names = (
            await conn.execute(
                text(
                    "SELECT tablename FROM pg_tables WHERE schemaname='public' "
                    "AND tablename <> 'alembic_version' AND tablename NOT LIKE 'lookup_cache'"
                )
            )
        ).scalars()
        await conn.execute(text("TRUNCATE " + ", ".join(names) + ", lookup_cache CASCADE"))


@pytest_asyncio.fixture
async def client(app):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@dataclass
class Env:
    app: object
    client: httpx.AsyncClient
    household_id: uuid.UUID
    admin: dict = field(default_factory=dict)  # headers
    member: dict = field(default_factory=dict)
    locations: dict = field(default_factory=dict)  # name -> id
    categories: dict = field(default_factory=dict)
    member_id: str = ""

    def op(self, type_: str = "add", quantity=1, **kw) -> dict:
        d = {"client_op_id": str(uuid.uuid4()), "type": type_, "quantity": quantity}
        d.update(kw)
        return d

    async def ops(self, *ops: dict, headers: dict | None = None) -> list[dict]:
        r = await self.client.post(
            "/api/sync/ops",
            json={"device_id": "test-device", "ops": list(ops)},
            headers=headers or self.member,
        )
        assert r.status_code == 200, r.text
        return r.json()["results"]

    async def product(self, name="Mælk", **kw) -> dict:
        r = await self.client.post("/api/products", json={"name": name, **kw}, headers=self.member)
        assert r.status_code == 201, r.text
        return r.json()

    async def total(self, product_id: str) -> float:
        r = await self.client.get(f"/api/inventory/{product_id}", headers=self.member)
        assert r.status_code == 200, r.text
        return r.json()["total_quantity"]


async def _token(client: httpx.AsyncClient, username: str) -> dict:
    r = await client.post(
        "/api/auth/token",
        json={"username": username, "password": PASSWORD, "device_name": "pytest"},
    )
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


@pytest_asyncio.fixture
async def env(app, client) -> Env:
    async with app.state.sessionmaker() as s, s.begin():
        hh = await create_household(s, "Testhjem")
        await create_user(
            s,
            household_id=hh.id,
            username="owner",
            display_name="Owner",
            role="owner",
            password=PASSWORD,
        )
        member = await create_user(
            s,
            household_id=hh.id,
            username="member",
            display_name="Member",
            role="member",
            password=PASSWORD,
        )
        hh_id, member_id = hh.id, member.id
    e = Env(app=app, client=client, household_id=hh_id, member_id=str(member_id))
    e.admin = await _token(client, "owner")
    e.member = await _token(client, "member")
    r = await client.get("/api/locations", headers=e.admin)
    e.locations = {loc["name"]: loc["id"] for loc in r.json()}
    r = await client.get("/api/categories", headers=e.admin)
    e.categories = {c["name"]: c["id"] for c in r.json()}
    return e


@pytest_asyncio.fixture
async def other_env(app, client) -> Env:
    """A second, unrelated household."""
    async with app.state.sessionmaker() as s, s.begin():
        hh = await create_household(s, "Naboen")
        await create_user(
            s,
            household_id=hh.id,
            username="neighbour",
            display_name="Nabo",
            role="owner",
            password=PASSWORD,
        )
        hh_id = hh.id
    e = Env(app=app, client=client, household_id=hh_id)
    e.admin = e.member = await _token(client, "neighbour")
    r = await client.get("/api/locations", headers=e.admin)
    e.locations = {loc["name"]: loc["id"] for loc in r.json()}
    return e
