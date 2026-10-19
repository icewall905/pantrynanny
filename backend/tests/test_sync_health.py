import httpx


async def test_health(client, app):
    r = await client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok" and body["db"] == "ok" and body["ai"] == "disabled"
    assert body["version"]


async def test_openapi_and_docs(client):
    r = await client.get("/api/openapi.json")
    assert r.status_code == 200
    paths = r.json()["paths"]
    for p in ("/api/sync/ops", "/api/products/by-barcode/{raw}", "/api/inventory", "/api/health"):
        assert p in paths
    assert (await client.get("/api/docs")).status_code == 200


async def test_uniform_error_bodies(client, env):
    r = await client.get("/api/nope", headers=env.member)
    assert r.status_code == 404 and set(r.json()) >= {"detail", "code"}
    r = await client.get("/api/products/not-a-uuid", headers=env.member)
    assert r.status_code == 422 and r.json()["code"] == "validation_error"
    r = await client.post(
        "/api/auth/login",
        content=b"x" * (3 * 1024 * 1024),
        headers={"content-type": "application/json"},
    )
    assert r.status_code == 413 and r.json()["code"] == "payload_too_large"


async def test_health_reports_db_down(app, monkeypatch):
    from pantrynanny.config import Settings
    from pantrynanny.main import create_app

    broken = create_app(Settings(database_url="postgresql+asyncpg://x:y@127.0.0.1:1/none"))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=broken), base_url="http://t"
    ) as c:
        r = await c.get("/api/health")
    assert r.status_code == 503 and r.json()["db"] == "down"
    await broken.state.engine.dispose()


async def test_snapshot_and_changes_cursor(env):
    client = env.client
    p = await env.product("Mælk", category_id=env.categories["Mejeri"])
    await env.ops(
        env.op("add", quantity=2, product_id=p["id"], location_id=env.locations["Køleskab"])
    )

    snap = (await client.get("/api/sync/snapshot", headers=env.member)).json()
    assert [x["id"] for x in snap["products"]] == [p["id"]]
    assert (
        snap["inventory"][0]["product_id"] == p["id"]
        and snap["inventory"][0]["total_quantity"] == 2
    )
    assert len(snap["locations"]) == 5 and len(snap["categories"]) == 12
    assert snap["settings"]["scan_rearm_ms"] == 600
    cursor = snap["cursor"]
    assert cursor.isdigit() and int(cursor) > 0

    # nothing changed beyond the safety window re-read; replaying is harmless but ordered
    r = (await client.get("/api/sync/changes", params={"since": cursor}, headers=env.member)).json()
    assert r["full_resync_required"] is False and int(r["cursor"]) >= int(cursor)

    # a new change appears after the cursor and advances it
    other = await env.product("Smør")
    await env.ops(env.op("add", product_id=p["id"], location_id=env.locations["Køleskab"]))
    ch = (
        await client.get("/api/sync/changes", params={"since": cursor}, headers=env.member)
    ).json()
    assert int(ch["cursor"]) >= int(cursor)
    pids = {x["id"] for x in ch["products"]}
    assert other["id"] in pids
    inv = {x["product_id"]: x["total_quantity"] for x in ch["inventory"]}
    assert inv[p["id"]] == 3

    # advancing past everything yields (almost) nothing once beyond the safety window
    for _ in range(3):
        await env.product("Fyld")
    c2 = (
        await client.get("/api/sync/changes", params={"since": ch["cursor"]}, headers=env.member)
    ).json()
    assert {x["name"] for x in c2["products"]} >= {"Fyld"}

    # deletions and location/category edits propagate
    await client.delete(f"/api/products/{other['id']}", headers=env.member)
    await client.patch(
        f"/api/locations/{env.locations['Andet']}", json={"name": "Diverse"}, headers=env.member
    )
    c3 = (
        await client.get("/api/sync/changes", params={"since": c2["cursor"]}, headers=env.member)
    ).json()
    deleted = [x for x in c3["products"] if x["id"] == other["id"]]
    assert deleted and deleted[0]["deleted_at"] is not None
    assert any(x["name"] == "Diverse" for x in c3["locations"])

    # cursors from the future / garbage require a full resync
    r = (
        await client.get("/api/sync/changes", params={"since": "999999999"}, headers=env.member)
    ).json()
    assert r["full_resync_required"] is True
    r = (await client.get("/api/sync/changes", params={"since": "abc"}, headers=env.member)).json()
    assert r["full_resync_required"] is True


async def test_changes_are_household_scoped(env, other_env):
    await env.product("Hemmelig")
    snap = (await other_env.client.get("/api/sync/snapshot", headers=other_env.admin)).json()
    assert snap["products"] == []
    ch = (
        await other_env.client.get(
            "/api/sync/changes", params={"since": "0"}, headers=other_env.admin
        )
    ).json()
    assert ch["products"] == [] and ch["inventory"] == []
