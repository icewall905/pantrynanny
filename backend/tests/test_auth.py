import httpx

from .conftest import PASSWORD

CSRF = {"X-PN-CSRF": "1"}


async def test_unauthenticated_is_401(client, env):
    for path in ("/api/products", "/api/inventory", "/api/auth/me", "/api/sync/snapshot"):
        r = await client.get(path)
        assert r.status_code == 401, path
        assert r.json()["code"] == "unauthenticated"
    r = await client.get("/api/products", headers={"Authorization": "Bearer nonsense"})
    assert r.status_code == 401


async def test_cookie_login_requires_csrf_for_unsafe_methods(app, env):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post(
            "/api/auth/login", json={"username": "member", "password": PASSWORD, "remember": True}
        )
        assert r.status_code == 200, r.text
        set_cookie = r.headers["set-cookie"]
        assert "pn_session=" in set_cookie and "HttpOnly" in set_cookie
        assert "samesite=lax" in set_cookie.lower() and "Max-Age=15552000" in set_cookie
        assert "secure" not in set_cookie.lower()
        body = r.json()
        assert body["user"]["username"] == "member" and body["kiosk"] is False
        assert body["household"]["name"] == "Testhjem"
        assert body["settings"]["scan_rearm_ms"] == 600

        assert (await c.get("/api/auth/me")).status_code == 200  # safe method: no CSRF needed
        r = await c.post("/api/locations", json={"name": "Garage"})
        assert r.status_code == 403 and r.json()["code"] == "csrf_required"
        r = await c.post("/api/locations", json={"name": "Garage"}, headers=CSRF)
        assert r.status_code == 201


async def test_cookie_secure_flag_behind_https_proxy(app, env):
    transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 1234))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post(
            "/api/auth/login",
            json={"username": "member", "password": PASSWORD},
            headers={"X-Forwarded-Proto": "https"},
        )
        assert r.status_code == 200
        assert "secure" in r.headers["set-cookie"].lower()
        assert "Max-Age=43200" in r.headers["set-cookie"]  # 12 h when not remembered


async def test_bearer_needs_no_csrf(client, env):
    r = await client.post("/api/locations", json={"name": "Kælder"}, headers=env.member)
    assert r.status_code == 201


async def test_wrong_password_and_inactive_user(client, env):
    r = await client.post("/api/auth/login", json={"username": "member", "password": "nope"})
    assert r.status_code == 401 and r.json()["code"] == "invalid_credentials"
    r = await client.post("/api/auth/login", json={"username": "ghost", "password": "nope"})
    assert r.status_code == 401
    # deactivate member -> existing token stops working
    r = await client.get("/api/users", headers=env.admin)
    member = next(u for u in r.json() if u["username"] == "member")
    r = await client.patch(
        f"/api/users/{member['id']}", json={"is_active": False}, headers=env.admin
    )
    assert r.status_code == 200
    assert (await client.get("/api/auth/me", headers=env.member)).status_code == 401


async def test_login_rate_limit(client, env):
    for _ in range(10):
        r = await client.post("/api/auth/login", json={"username": "member", "password": "bad"})
        assert r.status_code == 401
    r = await client.post("/api/auth/login", json={"username": "member", "password": PASSWORD})
    assert r.status_code == 429 and "retry-after" in r.headers
    # a different username is tracked separately
    r = await client.post("/api/auth/login", json={"username": "owner", "password": PASSWORD})
    assert r.status_code == 200


async def test_logout_revokes_token(client, env):
    assert (await client.get("/api/auth/me", headers=env.member)).status_code == 200
    r = await client.post("/api/auth/logout", headers=env.member)
    assert r.status_code == 200
    assert (await client.get("/api/auth/me", headers=env.member)).status_code == 401
    assert (await client.get("/api/auth/me", headers=env.admin)).status_code == 200


async def test_roles(client, env):
    assert (await client.get("/api/users", headers=env.member)).status_code == 403
    assert (await client.get("/api/devices", headers=env.member)).status_code == 403
    r = await client.patch("/api/settings", json={"scan_rearm_ms": 800}, headers=env.member)
    assert r.status_code == 403
    r = await client.patch("/api/settings", json={"scan_rearm_ms": 800}, headers=env.admin)
    assert r.status_code == 200 and r.json()["scan_rearm_ms"] == 800
    r = await client.patch("/api/settings", json={"scan_rearm_ms": 100}, headers=env.admin)
    assert r.status_code == 422
    r = await client.delete(f"/api/locations/{env.locations['Andet']}", headers=env.member)
    assert r.status_code == 403
    r = await client.delete(f"/api/locations/{env.locations['Andet']}", headers=env.admin)
    assert r.status_code == 204


async def test_user_management(client, env):
    r = await client.post(
        "/api/users",
        json={"username": "Mette", "display_name": "Mette", "role": "member", "password": PASSWORD},
        headers=env.admin,
    )
    assert r.status_code == 201 and r.json()["username"] == "mette"
    r = await client.post(
        "/api/users",
        json={"username": "mette", "display_name": "x", "role": "member", "password": PASSWORD},
        headers=env.admin,
    )
    assert r.status_code == 409
    r = await client.post(
        "/api/auth/token",
        json={"username": "METTE", "password": PASSWORD, "device_name": "phone"},
    )
    assert r.status_code == 200
    # last owner cannot be demoted or deleted
    owner = next(
        u
        for u in (await client.get("/api/users", headers=env.admin)).json()
        if u["role"] == "owner"
    )
    r = await client.patch(f"/api/users/{owner['id']}", json={"role": "member"}, headers=env.admin)
    assert r.status_code == 409 and r.json()["code"] == "last_owner"
    r = await client.delete(f"/api/users/{owner['id']}", headers=env.admin)
    assert r.status_code == 409


async def test_kiosk_pairing_and_scope(app, client, env):
    p = await env.product("Kioskmælk")
    r = await client.post(
        "/api/devices/kiosk-codes", json={"name": "Køkken-iPad"}, headers=env.admin
    )
    assert r.status_code == 201
    code = r.json()["code"]
    assert len(code) == 8

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as kiosk:
        r = await kiosk.post("/api/auth/kiosk", json={"code": "WRONGCODE"})
        assert r.status_code == 401
        r = await kiosk.post("/api/auth/kiosk", json={"code": code})
        assert r.status_code == 200, r.text
        assert r.json()["kiosk"] is True and r.json()["user"] is None
        assert "Max-Age=31536000" in r.headers["set-cookie"]

        # allowed
        assert (await kiosk.get("/api/inventory")).status_code == 200
        assert (await kiosk.get("/api/products")).status_code == 200
        assert (await kiosk.get(f"/api/products/{p['id']}")).status_code == 200
        assert (await kiosk.get("/api/locations")).status_code == 200
        assert (await kiosk.get("/api/categories")).status_code == 200
        assert (await kiosk.get("/api/shopping")).status_code == 200
        assert (await kiosk.get("/api/sync/snapshot")).status_code == 200
        assert (await kiosk.get("/api/products/by-barcode/5701234567899")).status_code == 200
        r = await kiosk.post(
            "/api/sync/ops",
            json={"ops": [env.op("add", product_id=p["id"])]},
            headers=CSRF,
        )
        assert r.status_code == 200 and r.json()["results"][0]["status"] == "applied"

        # forbidden: everything else
        forbidden = [
            ("get", "/api/users"),
            ("get", "/api/devices"),
            ("get", "/api/dashboard"),
            ("get", "/api/transactions"),
            ("post", "/api/products"),
            ("patch", f"/api/products/{p['id']}"),
            ("delete", f"/api/products/{p['id']}"),
            ("post", "/api/shopping"),
            ("patch", "/api/settings"),
            ("post", "/api/locations"),
            ("post", f"/api/products/{p['id']}/merge"),
            ("post", "/api/devices/kiosk-codes"),
        ]
        for method, path in forbidden:
            r = await getattr(kiosk, method)(
                path,
                headers={**CSRF, "If-Match": "1"},
                **({"json": {}} if method in ("post", "patch") else {}),
            )
            assert r.status_code == 403, (method, path, r.status_code)
            assert r.json()["code"] == "kiosk_forbidden"

        # cookie + unsafe + no CSRF header is rejected before anything else
        r = await kiosk.post("/api/sync/ops", json={"ops": []})
        assert r.status_code == 403 and r.json()["code"] == "csrf_required"

    # single use
    r = await client.post("/api/auth/kiosk", json={"code": code})
    assert r.status_code == 401

    # shows up as a device and can be revoked
    devices = (await client.get("/api/devices", headers=env.admin)).json()
    kiosk_dev = next(d for d in devices if d["kind"] == "kiosk")
    assert kiosk_dev["device_name"] == "Køkken-iPad"
    r = await client.delete(f"/api/devices/{kiosk_dev['id']}", headers=env.admin)
    assert r.status_code == 204


async def test_household_isolation_returns_404(client, env, other_env):
    p = await env.product("Privat")
    loc = env.locations["Køleskab"]
    cat = env.categories["Mejeri"]
    res = (await env.ops(env.op("add", product_id=p["id"])))[0]
    assert res["status"] == "applied"
    txn_id = res["transaction_id"]

    other = other_env.admin
    assert (await client.get(f"/api/products/{p['id']}", headers=other)).status_code == 404
    assert (await client.get(f"/api/inventory/{p['id']}", headers=other)).status_code == 404
    r = await client.patch(
        f"/api/products/{p['id']}", json={"name": "x"}, headers={**other, "If-Match": "1"}
    )
    assert r.status_code == 404
    assert (await client.delete(f"/api/products/{p['id']}", headers=other)).status_code == 404
    assert (
        await client.post(
            f"/api/products/{p['id']}/merge", json={"into_id": p["id"]}, headers=other
        )
    ).status_code in (404, 422)
    assert (
        await client.patch(f"/api/locations/{loc}", json={"name": "x"}, headers=other)
    ).status_code == 404
    assert (await client.delete(f"/api/categories/{cat}", headers=other)).status_code == 404
    r = await client.post(
        f"/api/transactions/{txn_id}/undo",
        json={"client_op_id": env.op()["client_op_id"]},
        headers=other,
    )
    assert r.status_code == 404
    assert (await client.get("/api/products", headers=other)).json() == []
    assert (await client.get("/api/inventory", headers=other)).json() == []
    assert (await client.get("/api/transactions", headers=other)).json() == []
    # an op naming a foreign product is rejected, not applied
    res = (await other_env.ops(other_env.op("add", product_id=p["id"])))[0]
    assert res["status"] == "rejected" and res["error_code"] == "product_not_found"
    # foreign location id is rejected too
    mine = await other_env.product("Egen")
    res = (await other_env.ops(other_env.op("add", product_id=mine["id"], location_id=loc)))[0]
    assert res["status"] == "rejected"
    # foreign user/session listing
    assert (await client.get("/api/devices", headers=other)).json()[0]["username"] == "neighbour"


async def test_sliding_expiry_updates_last_used_at_at_most_once_per_minute(app, client, env):
    from datetime import timedelta

    from sqlalchemy import select, update

    from pantrynanny.models import Session, User
    from pantrynanny.security import now

    async with app.state.sessionmaker() as s:
        sid = (
            await s.execute(
                select(Session.id)
                .join(User, User.id == Session.user_id)
                .where(User.username == "owner")
            )
        ).scalar_one()

    async def row():
        async with app.state.sessionmaker() as s:
            return await s.get(Session, sid, populate_existing=True)

    async with app.state.sessionmaker() as s, s.begin():
        await s.execute(
            update(Session)
            .where(Session.id == sid)
            .values(last_used_at=now() - timedelta(minutes=5), expires_at=now() + timedelta(days=1))
        )
    stale = await row()
    await client.get("/api/auth/me", headers=env.admin)
    touched = await row()
    assert touched.last_used_at > stale.last_used_at
    assert touched.expires_at > stale.expires_at + timedelta(days=300)  # re-slid to ~365 days
    await client.get("/api/auth/me", headers=env.admin)
    assert (await row()).last_used_at == touched.last_used_at  # not touched again within a minute


async def test_expired_session_is_rejected(app, client, env):
    from datetime import timedelta

    from sqlalchemy import update

    from pantrynanny.models import Session
    from pantrynanny.security import now

    async with app.state.sessionmaker() as s, s.begin():
        await s.execute(update(Session).values(expires_at=now() - timedelta(seconds=1)))
    assert (await client.get("/api/auth/me", headers=env.admin)).status_code == 401
