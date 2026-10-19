import uuid


async def test_manual_items_and_dedupe_by_product(env):
    p = await env.product("Mælk", stock_unit="pkg")
    r = await env.client.post(
        "/api/shopping", json={"product_id": p["id"], "quantity": 2}, headers=env.member
    )
    assert r.status_code == 201
    first = r.json()
    assert first["name"] == "Mælk" and first["unit"] == "pkg" and first["source"] == "manual"
    r = await env.client.post(
        "/api/shopping", json={"product_id": p["id"], "quantity": 1.5}, headers=env.member
    )
    assert r.status_code == 200
    assert (
        r.json()["id"] == first["id"] and r.json()["quantity"] == 3.5 and r.json()["version"] == 2
    )
    items = (await env.client.get("/api/shopping", headers=env.member)).json()
    assert len(items) == 1
    # free-text item
    r = await env.client.post("/api/shopping", json={"name": "Balloner"}, headers=env.member)
    assert r.status_code == 201 and r.json()["product_id"] is None and r.json()["quantity"] == 1
    r = await env.client.post("/api/shopping", json={"quantity": 1}, headers=env.member)
    assert r.status_code == 422
    r = await env.client.post(
        "/api/shopping", json={"product_id": str(uuid.uuid4())}, headers=env.member
    )
    assert r.status_code == 404


async def test_check_clear_patch_delete(env):
    a = (await env.client.post("/api/shopping", json={"name": "A"}, headers=env.member)).json()
    b = (await env.client.post("/api/shopping", json={"name": "B"}, headers=env.member)).json()
    r = await env.client.patch(
        f"/api/shopping/{a['id']}", json={"checked": True}, headers=env.member
    )
    assert r.status_code == 200 and r.json()["checked"] is True and r.json()["checked_at"]
    # editing other fields needs If-Match, stale version conflicts
    r = await env.client.patch(f"/api/shopping/{b['id']}", json={"quantity": 4}, headers=env.member)
    assert r.status_code == 428
    r = await env.client.patch(
        f"/api/shopping/{b['id']}", json={"quantity": 4}, headers={**env.member, "If-Match": "1"}
    )
    assert r.status_code == 200 and r.json()["quantity"] == 4
    r = await env.client.patch(
        f"/api/shopping/{b['id']}", json={"quantity": 5}, headers={**env.member, "If-Match": "1"}
    )
    assert r.status_code == 409 and r.json()["code"] == "version_conflict"
    # checked items sort last
    assert [
        i["name"] for i in (await env.client.get("/api/shopping", headers=env.member)).json()
    ] == ["B", "A"]
    r = await env.client.post("/api/shopping/clear-checked", headers=env.member)
    assert r.json() == {"removed": 1}
    assert [
        i["name"] for i in (await env.client.get("/api/shopping", headers=env.member)).json()
    ] == ["B"]
    assert (
        await env.client.delete(f"/api/shopping/{b['id']}", headers=env.member)
    ).status_code == 204
    assert (await env.client.get("/api/shopping", headers=env.member)).json() == []
    assert (
        await env.client.delete(f"/api/shopping/{b['id']}", headers=env.member)
    ).status_code == 404


async def test_checked_item_does_not_block_new_open_item(env):
    p = await env.product("Smør")
    first = (
        await env.client.post("/api/shopping", json={"product_id": p["id"]}, headers=env.member)
    ).json()
    await env.client.patch(
        f"/api/shopping/{first['id']}", json={"checked": True}, headers=env.member
    )
    r = await env.client.post("/api/shopping", json={"product_id": p["id"]}, headers=env.member)
    assert r.status_code == 201 and r.json()["id"] != first["id"]
    # un-checking the old one folds into the open item instead of duplicating
    r = await env.client.patch(
        f"/api/shopping/{first['id']}", json={"checked": False}, headers=env.member
    )
    assert r.status_code == 200 and r.json()["quantity"] == 2
    assert len((await env.client.get("/api/shopping", headers=env.member)).json()) == 1


async def test_low_stock_auto_add_without_duplicates(env):
    p = await env.product("Æg", min_stock=6, stock_unit="pcs")
    await env.ops(env.op("add", quantity=8, product_id=p["id"]))
    assert (await env.client.get("/api/shopping", headers=env.member)).json() == []
    await env.ops(env.op("remove", quantity=1, product_id=p["id"]))  # 7 >= 6
    assert (await env.client.get("/api/shopping", headers=env.member)).json() == []
    await env.ops(env.op("remove", quantity=2, product_id=p["id"]))  # 5 < 6
    items = (await env.client.get("/api/shopping", headers=env.member)).json()
    assert len(items) == 1
    assert items[0]["source"] == "low_stock" and items[0]["product_id"] == p["id"]
    assert items[0]["quantity"] == 1 and items[0]["unit"] == "pcs"
    # further removals must not create duplicates or change the existing item
    await env.ops(
        env.op("remove", quantity=1, product_id=p["id"]),
        env.op("adjust", quantity=-1, product_id=p["id"]),
    )
    items = (await env.client.get("/api/shopping", headers=env.member)).json()
    assert len(items) == 1
    # also merges with a manually added open item
    q = await env.product("Fløde", min_stock=2)
    await env.client.post(
        "/api/shopping", json={"product_id": q["id"], "quantity": 3}, headers=env.member
    )
    await env.ops(
        env.op("add", quantity=2, product_id=q["id"]),
        env.op("remove", quantity=1, product_id=q["id"]),
    )
    flod = [
        i
        for i in (await env.client.get("/api/shopping", headers=env.member)).json()
        if i["product_id"] == q["id"]
    ]
    assert len(flod) == 1 and flod[0]["quantity"] == 3 and flod[0]["source"] == "manual"


async def test_low_stock_respects_setting_and_suggestions(env):
    await env.client.patch(
        "/api/settings", json={"auto_shopping_low_stock": False}, headers=env.admin
    )
    p = await env.product("Kaffe", min_stock=3)
    await env.ops(
        env.op("add", quantity=3, product_id=p["id"]),
        env.op("remove", quantity=1, product_id=p["id"]),
    )
    assert (await env.client.get("/api/shopping", headers=env.member)).json() == []
    sugg = (await env.client.get("/api/shopping/suggestions", headers=env.member)).json()
    assert [s["product"]["id"] for s in sugg] == [p["id"]] and sugg[0]["low_stock"] is True
    await env.client.post("/api/shopping", json={"product_id": p["id"]}, headers=env.member)
    assert (await env.client.get("/api/shopping/suggestions", headers=env.member)).json() == []
    dash = (await env.client.get("/api/dashboard", headers=env.member)).json()
    assert dash["shopping_open_count"] == 1 and len(dash["low_stock"]) == 1
    assert len(dash["recently_consumed"]) == 1


async def test_undo_of_removal_does_not_trigger_low_stock_but_undo_of_add_can(env):
    p = await env.product("Te", min_stock=2)
    add = env.op("add", quantity=3, product_id=p["id"])
    await env.ops(add)
    await env.ops(env.op("undo", quantity=None, undoes_client_op_id=add["client_op_id"]))
    items = (await env.client.get("/api/shopping", headers=env.member)).json()
    assert len(items) == 1 and items[0]["source"] == "low_stock"


async def test_concurrent_adds_of_same_product_merge(env):
    import asyncio

    p = await env.product("Brød")
    rs = await asyncio.gather(
        *(
            env.client.post(
                "/api/shopping", json={"product_id": p["id"], "quantity": 1}, headers=env.member
            )
            for _ in range(8)
        )
    )
    assert all(r.status_code in (200, 201) for r in rs), [r.text for r in rs]
    items = (await env.client.get("/api/shopping", headers=env.member)).json()
    assert len(items) == 1 and items[0]["quantity"] == 8
