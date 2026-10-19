"""Kitchen screen tiles and favourites."""


async def test_tiles_rank_favourites_then_frequency(env):
    c = env.client
    milk = await env.product("Mælk")
    bread = await env.product("Rugbrød")
    butter = await env.product("Smør")
    await env.ops(*[env.op("add", product_id=milk["id"]) for _ in range(3)])
    await env.ops(env.op("add", product_id=bread["id"]))
    r = await c.get("/api/kitchen/tiles", headers=env.member)
    assert r.status_code == 200, r.text
    assert [x["product"]["name"] for x in r.json()] == ["Mælk", "Rugbrød"]
    assert r.json()[0]["uses"] == 3 and r.json()[0]["total_quantity"] == 3

    # a favourite comes first even when it was never used (and is out of stock)
    v0 = (await c.get(f"/api/products/{butter['id']}", headers=env.member)).json()["version"]
    r = await c.put(
        f"/api/products/{butter['id']}/favorite", json={"favorite": True}, headers=env.member
    )
    assert r.status_code == 200 and r.json()["favorite"] is True
    assert r.json()["version"] == v0 and r.json()["locked_fields"] == []  # not an "edit"
    names = [
        x["product"]["name"] for x in (await c.get("/api/kitchen/tiles", headers=env.member)).json()
    ]
    assert names == ["Smør", "Mælk", "Rugbrød"]

    # undone scans do not count
    res = await env.ops(env.op("add", product_id=bread["id"]))
    await env.ops(env.op("undo", undoes_client_op_id=res[0]["client_op_id"]))
    tiles = (await c.get("/api/kitchen/tiles?limit=1", headers=env.member)).json()
    assert [x["product"]["name"] for x in tiles] == ["Smør"]  # favourites are never cut off


async def test_favourite_is_household_scoped(env):
    milk = await env.product("Mælk")
    r = await env.client.put(f"/api/products/{milk['id']}/favorite", json={"favorite": True})
    assert r.status_code == 401
