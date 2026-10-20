"""Regression tests for the T1a review findings."""

import asyncio
import uuid

import httpx
from sqlalchemy import func, select, text

from pantrynanny.models import StockTransaction

from .conftest import PASSWORD


async def inv_total(env, pid):
    return await env.total(pid)


# 1. quantity bounds ---------------------------------------------------------------------------
async def test_absurd_quantity_rejects_only_that_op(env):
    p = await env.product()
    ops = [
        env.op("add", quantity=1e30, product_id=p["id"]),
        env.op("add", quantity="99999999999", product_id=p["id"]),
        env.op("add", quantity=1.2345, product_id=p["id"]),
        env.op("add", quantity=2, product_id=p["id"]),
    ]
    results = await env.ops(*ops)
    assert [r["status"] for r in results] == ["rejected", "rejected", "rejected", "applied"]
    assert all(r["error_code"] == "invalid_quantity" for r in results[:3])
    assert await env.total(p["id"]) == 2


async def test_stock_total_cannot_overflow_numeric(env):
    p = await env.product()
    big = 1_000_000
    results = await env.ops(*[env.op("add", quantity=big, product_id=p["id"]) for _ in range(3)])
    assert [r["status"] for r in results] == ["applied"] * 3
    # push one batch toward the 1e8 per-batch ceiling in steps; the op that would cross is rejected
    r = await env.ops(env.op("add", quantity=big, product_id=p["id"]))
    assert r[0]["status"] == "applied"
    p2 = await env.product("Andet")
    steps = [env.op("add", quantity=big, product_id=p2["id"]) for _ in range(101)]
    res = await env.ops(*steps)
    statuses = [x["status"] for x in res]
    assert statuses.count("applied") == 100 and res[-1]["error_code"] == "invalid_quantity"


async def test_shopping_quantity_bounds(env):
    r = await env.client.post(
        "/api/shopping", json={"name": "x", "quantity": 1e7}, headers=env.member
    )
    assert r.status_code == 422
    r = await env.client.post(
        "/api/shopping", json={"name": "x", "quantity": 1.2345}, headers=env.member
    )
    assert r.status_code == 422
    p = await env.product()
    for _ in range(3):
        r = await env.client.post(
            "/api/shopping", json={"product_id": p["id"], "quantity": 600000}, headers=env.member
        )
        assert r.status_code in (200, 201)
    assert r.json()["quantity"] == 1_000_000  # merge is capped, never overflows


# 2 + 6. blank / oversized barcodes ---------------------------------------------------------------
async def test_blank_and_oversized_barcodes(env):
    p = await env.product()
    (res,) = await env.ops(env.op("add", barcode="   "))
    assert res["status"] == "rejected" and res["error_code"] == "missing_target"
    res = await env.ops(env.op("add", barcode="   ", product_id=p["id"]))
    assert res[0]["status"] == "applied"  # product_id wins; blank barcode ignored
    r = await env.client.get("/api/products/by-barcode/%20", headers=env.member)
    assert r.status_code == 422
    r = await env.client.get("/api/products/by-barcode/" + "9" * 201, headers=env.member)
    assert r.status_code == 422 and r.json()["code"] == "invalid_barcode"
    r = await env.client.post(
        f"/api/products/{p['id']}/barcodes", json={"raw": "  "}, headers=env.member
    )
    assert r.status_code == 422
    r = await env.client.post(
        "/api/products", json={"name": "Z", "barcodes": ["   "]}, headers=env.member
    )
    assert r.status_code == 422
    (res,) = await env.ops(env.op("add", barcode="1" * 300))
    assert res["status"] == "rejected" and res["error_code"] == "invalid_barcode"


# 3. merged product ids in queued ops -----------------------------------------------------------------
async def test_op_for_merged_product_follows_merge(env):
    keep = await env.product("Rigtig")
    r = await env.client.get("/api/products/by-barcode/5701234567899", headers=env.member)
    ph = r.json()["product"]
    mid = await env.product("Mellem")
    await env.client.post(
        f"/api/products/{ph['id']}/merge", json={"into_id": mid["id"]}, headers=env.member
    )
    await env.client.post(
        f"/api/products/{mid['id']}/merge", json={"into_id": keep["id"]}, headers=env.member
    )
    (res,) = await env.ops(env.op("add", quantity=2, product_id=ph["id"]))  # two hops
    assert res["status"] == "applied" and res["product"]["id"] == keep["id"]
    assert await env.total(keep["id"]) == 2
    # deleted (not merged) product + barcode falls back to the barcode's product
    gone = await env.product("Slettet")
    await env.client.delete(f"/api/products/{gone['id']}", headers=env.member)
    (res,) = await env.ops(env.op("add", product_id=gone["id"], barcode="5701234567899"))
    assert res["status"] == "applied" and res["product"]["id"] == keep["id"]
    (res,) = await env.ops(env.op("add", product_id=gone["id"]))
    assert res["status"] == "rejected" and res["error_code"] == "product_not_found"


# 4. clamped undo --------------------------------------------------------------------------------------
async def test_clamped_undo_records_actual_delta(env):
    p = await env.product()
    add = env.op("add", quantity=3, product_id=p["id"])
    await env.ops(add, env.op("remove", quantity=2, product_id=p["id"]))
    (res,) = await env.ops(env.op("undo", quantity=None, undoes_client_op_id=add["client_op_id"]))
    assert res["status"] == "applied" and res["error"] == "clamped"
    txns = (
        await env.client.get(
            "/api/transactions", params={"product_id": p["id"]}, headers=env.member
        )
    ).json()
    undo = next(t for t in txns if t["type"] == "undo")
    assert undo["quantity_delta"] == -1  # only one unit was left to take back, not 3
    assert await env.total(p["id"]) == 0


async def test_clamped_undo_of_move_records_moved_back_amount(env):
    p = await env.product()
    pantry, freezer = env.locations["Spisekammer"], env.locations["Fryser"]
    await env.ops(env.op("add", quantity=4, product_id=p["id"], location_id=pantry))
    mv = env.op("move", quantity=4, product_id=p["id"], location_id=pantry, to_location_id=freezer)
    await env.ops(mv, env.op("remove", quantity=3, product_id=p["id"], location_id=freezer))
    (res,) = await env.ops(env.op("undo", quantity=None, undoes_client_op_id=mv["client_op_id"]))
    assert res["error"] == "clamped"
    undo = next(
        t
        for t in (await env.client.get("/api/transactions", headers=env.member)).json()
        if t["type"] == "undo"
    )
    assert undo["quantity_delta"] == 1


# 5. cross-household category on shopping ------------------------------------------------------------------
async def test_shopping_rejects_foreign_category(env, other_env):
    cat = (await other_env.client.get("/api/categories", headers=other_env.admin)).json()
    # other_env has its own seeded categories
    foreign = cat[0]["id"]
    r = await env.client.post(
        "/api/shopping", json={"name": "x", "category_id": foreign}, headers=env.member
    )
    assert r.status_code == 422 and r.json()["code"] == "category_not_found"
    ok = await env.client.post(
        "/api/shopping",
        json={"name": "x", "category_id": env.categories["Mejeri"]},
        headers=env.member,
    )
    assert ok.status_code == 201
    r = await env.client.patch(
        f"/api/shopping/{ok.json()['id']}",
        json={"category_id": foreign},
        headers={**env.member, "If-Match": "1"},
    )
    assert r.status_code == 422


# 7. sync cursor with an uncommitted lower-seq writer --------------------------------------------------------
async def test_changes_do_not_skip_slow_writer(env):
    client = env.client
    cursor0 = (await client.get("/api/sync/snapshot", headers=env.member)).json()["cursor"]
    engine = env.app.state.engine
    slow = await engine.connect()
    trans = await slow.begin()
    # Slow writer draws the LOWER change_seq but commits last.
    await slow.execute(
        text("INSERT INTO products (household_id, name) VALUES (:h, 'Langsom')"),
        {"h": env.household_id},
    )
    fast = await env.product("Hurtig")  # higher seq, committed first
    ch1 = (
        await client.get("/api/sync/changes", params={"since": cursor0}, headers=env.member)
    ).json()
    names1 = {p["name"] for p in ch1["products"]}
    assert "Hurtig" in names1 and "Langsom" not in names1
    assert fast["id"] in {p["id"] for p in ch1["products"]}
    await trans.commit()
    await slow.close()
    ch2 = (
        await client.get("/api/sync/changes", params={"since": ch1["cursor"]}, headers=env.member)
    ).json()
    assert "Langsom" in {p["name"] for p in ch2["products"]}  # not lost
    # the feed never goes backwards (it may re-send rows while other transactions are open)
    assert int(ch2["cursor"].split(".")[2]) >= int(ch1["cursor"].split(".")[2])


# 8a. locked_fields only for changed values ------------------------------------------------------------------
async def test_patch_locks_only_changed_fields(env):
    p = await env.product("Mælk", brand="Arla", min_stock=2)
    form = {
        "name": "Mælk",  # unchanged
        "brand": "Arla",  # unchanged
        "min_stock": 2,
        "description": None,  # unchanged null
        "category_id": None,
        "ingredients": "vand",  # the only real edit
        "aliases": [],
        "allergens": [],
        "nutrition": None,
    }
    r = await env.client.patch(
        f"/api/products/{p['id']}", json=form, headers={**env.member, "If-Match": "1"}
    )
    assert r.status_code == 200
    assert r.json()["locked_fields"] == ["ingredients"] and r.json()["version"] == 2
    # a pure no-op does not bump the version or lock anything
    r = await env.client.patch(
        f"/api/products/{p['id']}", json=form, headers={**env.member, "If-Match": "2"}
    )
    assert (
        r.status_code == 200
        and r.json()["version"] == 2
        and r.json()["locked_fields"] == ["ingredients"]
    )


# nits ------------------------------------------------------------------------------------------------------------
async def test_deleted_location_in_queued_op_falls_back(env):
    p = await env.product()
    loc = (
        await env.client.post("/api/locations", json={"name": "Midlertidig"}, headers=env.member)
    ).json()
    await env.client.delete(f"/api/locations/{loc['id']}", headers=env.admin)
    (res,) = await env.ops(env.op("add", product_id=p["id"], location_id=loc["id"]))
    assert res["status"] == "applied"
    item = (await env.client.get("/api/inventory", headers=env.member)).json()[0]
    assert item["batches"][0]["location_id"] == env.locations["Køleskab"]
    # a move to a deleted destination is still rejected
    (res,) = await env.ops(
        env.op(
            "move",
            product_id=p["id"],
            location_id=env.locations["Spisekammer"],
            to_location_id=loc["id"],
        )
    )
    assert res["status"] == "rejected"


async def test_login_limiter_is_atomic_under_concurrency(env):
    rs = await asyncio.gather(
        *(
            env.client.post("/api/auth/login", json={"username": "member", "password": "bad"})
            for _ in range(25)
        )
    )
    codes = sorted(r.status_code for r in rs)
    assert codes.count(401) == 10 and codes.count(429) == 15


def test_wildcard_cors_rejected():
    import pytest

    from pantrynanny.config import Settings

    with pytest.raises(ValueError):
        Settings(cors_origins="*")
    assert Settings(cors_origins="https://a.example").cors_origin_list[0] == "https://a.example"


async def test_unhandled_error_is_generic_json(app, env):
    from fastapi import APIRouter

    router = APIRouter()

    @router.get("/api/_boom")
    async def boom():
        raise RuntimeError("secret internals /etc/passwd")

    app.include_router(router)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.get("/api/_boom")
    assert r.status_code == 500 and r.json() == {"detail": "internal error", "code": "internal"}


async def test_product_collection_bounds(env):
    r = await env.client.post(
        "/api/products", json={"name": "X", "allergens": ["a" * 101]}, headers=env.member
    )
    assert r.status_code == 422
    r = await env.client.post(
        "/api/products",
        json={"name": "X", "nutrition": {f"k{i}": i for i in range(101)}},
        headers=env.member,
    )
    assert r.status_code == 422
    r = await env.client.post(
        "/api/products", json={"name": "X", "nutrition": {"k": "v" * 9000}}, headers=env.member
    )
    assert r.status_code == 422
    r = await env.client.post(
        "/api/products",
        json={"name": "X", "nutrition": {"kcal": 52}, "countries": ["DK"]},
        headers=env.member,
    )
    assert r.status_code == 201


async def test_admin_cannot_revoke_owner_device(client, env):
    r = await client.post(
        "/api/users",
        json={"username": "adm", "display_name": "Adm", "role": "admin", "password": PASSWORD},
        headers=env.admin,
    )
    assert r.status_code == 201
    tok = (
        await client.post(
            "/api/auth/token",
            json={"username": "adm", "password": PASSWORD, "device_name": "adm-phone"},
        )
    ).json()["token"]
    adm = {"Authorization": f"Bearer {tok}"}
    devices = (await client.get("/api/devices", headers=adm)).json()
    owner_dev = next(d for d in devices if d["username"] == "owner")
    r = await client.delete(f"/api/devices/{owner_dev['id']}", headers=adm)
    assert r.status_code == 403 and r.json()["code"] == "owner_required"
    member_dev = next(d for d in devices if d["username"] == "member")
    assert (await client.delete(f"/api/devices/{member_dev['id']}", headers=adm)).status_code == 204
    assert (
        await client.delete(f"/api/devices/{owner_dev['id']}", headers=env.admin)
    ).status_code == 204


async def test_fk_dedupe_count_unchanged(app, env):
    # sanity: nothing above wrote stray transactions for rejected ops
    async with app.state.sessionmaker() as s:
        assert await s.scalar(select(func.count()).select_from(StockTransaction)) == 0
    assert uuid.UUID(env.member_id)


async def test_db_down_maps_to_503(app):
    from pantrynanny.config import Settings
    from pantrynanny.main import create_app

    broken = create_app(Settings(database_url="postgresql+asyncpg://x:y@127.0.0.1:1/none"))
    transport = httpx.ASGITransport(app=broken, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.post("/api/auth/login", json={"username": "a", "password": "b"})
        assert r.status_code == 503 and r.json()["code"] == "db_unavailable"
        assert r.headers["retry-after"] == "5"
        r = await c.get("/api/auth/me", headers={"Authorization": "Bearer abc"})
        assert r.status_code == 503
    await broken.state.engine.dispose()


def test_is_db_unavailable_classification():
    import asyncpg
    from sqlalchemy.exc import IntegrityError, InterfaceError, OperationalError
    from sqlalchemy.exc import TimeoutError as PoolTimeout

    from pantrynanny.errors import is_db_unavailable

    assert is_db_unavailable(ConnectionRefusedError())
    assert is_db_unavailable(PoolTimeout("pool exhausted"))
    assert is_db_unavailable(InterfaceError("s", {}, asyncpg.ConnectionDoesNotExistError("gone")))
    err = OperationalError("s", {}, Exception("x"))
    err.connection_invalidated = True
    assert is_db_unavailable(err)
    assert is_db_unavailable(OperationalError("s", {}, asyncpg.CannotConnectNowError()))
    assert not is_db_unavailable(IntegrityError("s", {}, Exception("dup")))
    assert not is_db_unavailable(ValueError("bug"))
    assert not is_db_unavailable(OperationalError("s", {}, asyncpg.DeadlockDetectedError()))


async def test_unicode_digit_barcode_is_422_free(env):
    r = await env.client.get("/api/products/by-barcode/570123456789%C2%B2", headers=env.member)
    assert r.status_code == 200 and r.json()["barcode"]["code"].startswith("local:")
    r = await env.client.get("/api/products/by-barcode/%C2%A0", headers=env.member)
    assert r.status_code == 422
    (res,) = await env.ops(env.op("add", barcode="\x1d\xa0"))
    assert res["status"] == "rejected" and res["error_code"] == "missing_target"


async def test_barcode_op_retries_when_product_deleted_before_lock(env, monkeypatch):
    from pantrynanny.services import inventory as inv_svc

    real = inv_svc.get_or_create_placeholder
    calls = {"n": 0}

    async def flaky(session, hh, nb):
        found, created = await real(session, hh, nb)
        calls["n"] += 1
        if calls["n"] == 1:  # simulate a concurrent delete between lookup and lock
            from sqlalchemy import text

            await session.execute(
                text("UPDATE products SET deleted_at = now() WHERE id = :i"), {"i": found.id}
            )
        return found, created

    monkeypatch.setattr(inv_svc, "get_or_create_placeholder", flaky)
    (res,) = await env.ops(env.op("add", barcode="5701234567899"))
    assert res["status"] == "applied" and calls["n"] >= 2


async def test_generic_data_errors_are_invalid_op(env, monkeypatch):
    from sqlalchemy.exc import DataError

    from pantrynanny.services import inventory as inv_svc

    async def boom(*a, **k):
        raise DataError("s", {}, Exception("bad"))

    p = await env.product()
    monkeypatch.setattr(inv_svc, "_add_stock", boom)
    (res,) = await env.ops(env.op("add", product_id=p["id"]))
    assert res["status"] == "rejected" and res["error_code"] == "invalid_op"


def test_disk_full_is_not_db_unavailable():
    import errno

    from pantrynanny.errors import is_db_unavailable

    assert not is_db_unavailable(OSError(errno.ENOSPC, "No space left on device"))
    assert not is_db_unavailable(PermissionError(errno.EACCES, "denied"))
    assert is_db_unavailable(OSError(errno.ECONNRESET, "reset"))
    assert is_db_unavailable(ConnectionRefusedError())


async def test_transactions_composite_cursor_survives_created_at_ties(app, env):
    p = await env.product()
    await env.ops(*[env.op("add", product_id=p["id"]) for _ in range(5)])
    async with app.state.sessionmaker() as s, s.begin():
        await s.execute(text("UPDATE stock_transactions SET created_at = '2026-01-01T00:00:00Z'"))
    seen, before = [], None
    for _ in range(10):
        params = {"limit": 2, **({"before": before} if before else {})}
        r = await env.client.get("/api/transactions", params=params, headers=env.member)
        assert r.status_code == 200
        seen += [t["id"] for t in r.json()]
        before = r.headers.get("x-next-before")
        if not before:
            break
    assert len(seen) == 5 and len(set(seen)) == 5
    r = await env.client.get("/api/transactions", params={"before": "garbage"}, headers=env.member)
    assert r.status_code == 422
    r = await env.client.get(
        "/api/transactions", params={"before": "2027-01-01T00:00:00Z"}, headers=env.member
    )
    assert len(r.json()) == 5
