import uuid


async def test_create_get_and_barcode_conflict(env):
    p = await env.product(
        "Letmælk",
        brand="Arla",
        barcodes=["5701234567899"],
        aliases=["mælk", "letmaelk"],
        category_id=env.categories["Mejeri"],
        package_size=1,
        package_unit="l",
        stock_unit="pkg",
    )
    assert p["version"] == 1 and p["status"] == "known" and p["source"] == "user"
    assert p["barcodes"][0] == {
        "code": "05701234567899",
        "raw": "5701234567899",
        "symbology": "ean_13",
    }
    assert sorted(p["aliases"]) == ["letmaelk", "mælk"]
    assert p["package_size"] == 1 and p["locked_fields"] == []
    r = await env.client.get(f"/api/products/{p['id']}", headers=env.member)
    assert r.json()["id"] == p["id"]
    dup = await env.client.post(
        "/api/products", json={"name": "Anden", "barcodes": ["5701234567899"]}, headers=env.member
    )
    assert dup.status_code == 409 and dup.json()["code"] == "barcode_exists"
    assert dup.json()["product_id"] == p["id"]
    bad = await env.client.post(
        "/api/products", json={"name": "X", "stock_unit": "gallon"}, headers=env.member
    )
    assert bad.status_code == 422 and bad.json()["code"] == "validation_error"
    bad = await env.client.post(
        "/api/products", json={"name": "X", "category_id": str(uuid.uuid4())}, headers=env.member
    )
    assert bad.status_code == 422


async def test_patch_requires_if_match_and_conflicts(env):
    p = await env.product("Gammelt navn")
    r = await env.client.patch(f"/api/products/{p['id']}", json={"name": "Nyt"}, headers=env.member)
    assert r.status_code == 428 and r.json()["code"] == "if_match_required"

    r = await env.client.patch(
        f"/api/products/{p['id']}",
        json={"name": "Nyt navn", "brand": "Mærke", "min_stock": 2},
        headers={**env.member, "If-Match": '"1"'},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["version"] == 2 and body["name"] == "Nyt navn"
    assert sorted(body["locked_fields"]) == ["brand", "min_stock", "name"]

    # stale version -> 409 with the current product
    r = await env.client.patch(
        f"/api/products/{p['id']}",
        json={"description": "x"},
        headers={**env.member, "If-Match": "1"},
    )
    assert r.status_code == 409 and r.json()["code"] == "version_conflict"
    assert r.json()["product"]["version"] == 2 and r.json()["product"]["name"] == "Nyt navn"

    # a second edit appends to locked_fields
    r = await env.client.patch(
        f"/api/products/{p['id']}",
        json={"description": "x", "brand": None},
        headers={**env.member, "If-Match": "2"},
    )
    assert r.status_code == 200
    assert sorted(r.json()["locked_fields"]) == ["brand", "description", "min_stock", "name"]
    assert r.json()["brand"] is None and r.json()["version"] == 3

    r = await env.client.patch(
        f"/api/products/{p['id']}", json={"name": None}, headers={**env.member, "If-Match": "3"}
    )
    assert r.status_code == 422


async def test_editing_placeholder_makes_it_known(env):
    r = await env.client.get("/api/products/by-barcode/5701234567899", headers=env.member)
    pid = r.json()["product"]["id"]
    r = await env.client.patch(
        f"/api/products/{pid}", json={"name": "Kaffe"}, headers={**env.member, "If-Match": "1"}
    )
    assert r.json()["status"] == "known" and r.json()["source"] == "user"
    unknown = await env.client.get(
        "/api/products", params={"status": "unknown"}, headers=env.member
    )
    assert unknown.json() == []


async def test_barcode_add_remove(env):
    a = await env.product("A")
    b = await env.product("B", barcodes=["4006381333931"])
    r = await env.client.post(
        f"/api/products/{a['id']}/barcodes",
        json={"raw": "96385074", "symbology": "ean_8"},
        headers=env.member,
    )
    assert r.status_code == 201 and r.json()["barcodes"][0]["code"] == "00000096385074"
    assert r.json()["version"] == 2
    r = await env.client.post(
        f"/api/products/{a['id']}/barcodes", json={"raw": "4006381333931"}, headers=env.member
    )
    assert r.status_code == 409 and r.json()["product_id"] == b["id"]
    # adding an existing barcode of the same product is a no-op
    r = await env.client.post(
        f"/api/products/{a['id']}/barcodes", json={"raw": "96385074"}, headers=env.member
    )
    assert len(r.json()["barcodes"]) == 1
    r = await env.client.delete(
        f"/api/products/{a['id']}/barcodes/00000096385074", headers=env.member
    )
    assert r.status_code == 200 and r.json()["barcodes"] == []
    r = await env.client.delete(f"/api/products/{a['id']}/barcodes/nope", headers=env.member)
    assert r.status_code == 404
    # QR style codes with colons/slashes round-trip
    r = await env.client.post(
        f"/api/products/{a['id']}/barcodes",
        json={"raw": "https://x.y/z", "symbology": "qr"},
        headers=env.member,
    )
    code = r.json()["barcodes"][0]["code"]
    assert code == "local:https://x.y/z"
    r = await env.client.delete(f"/api/products/{a['id']}/barcodes/{code}", headers=env.member)
    assert r.status_code == 200 and r.json()["barcodes"] == []


async def test_search_is_forgiving(env):
    await env.product(
        "Økologisk Letmælk",
        brand="Arla",
        aliases=["mælk"],
        category_id=env.categories["Mejeri"],
        barcodes=["5701234567899"],
    )
    await env.product("Rugbrød", brand="Schulstad", category_id=env.categories["Brød & bagværk"])
    await env.product("Havregryn", brand="Quaker")

    async def names(q):
        r = await env.client.get("/api/products", params={"q": q}, headers=env.member)
        assert r.status_code == 200
        return [p["name"] for p in r.json()]

    assert await names("okologisk") == ["Økologisk Letmælk"]  # unaccent
    assert await names("MÆLK") == ["Økologisk Letmælk"]
    assert await names("arla") == ["Økologisk Letmælk"]  # brand
    assert await names("mejeri") == ["Økologisk Letmælk"]  # category
    assert await names("5701234") == ["Økologisk Letmælk"]  # barcode prefix
    assert await names("rugbrod schulstad") == ["Rugbrød"]  # multi-token AND
    assert await names("rugbrd") == ["Rugbrød"]  # typo via trigram
    assert await names("havregyn") == ["Havregryn"]
    assert await names("zzzzzz") == []
    assert len(await names("")) == 3
    # relevance: exact name beats brand/category matches
    await env.product("Arla", brand="Andet")
    assert (await names("arla"))[0] == "Arla"
    # pagination
    r = await env.client.get("/api/products", params={"limit": 2, "offset": 2}, headers=env.member)
    assert len(r.json()) == 2


async def test_soft_delete_frees_barcode(env):
    p = await env.product("Slettes", barcodes=["4006381333931"])
    r = await env.client.delete(f"/api/products/{p['id']}", headers=env.member)
    assert r.status_code == 204
    assert (await env.client.get(f"/api/products/{p['id']}", headers=env.member)).status_code == 404
    assert (await env.client.get("/api/products", headers=env.member)).json() == []
    again = await env.product("Ny", barcodes=["4006381333931"])
    assert again["id"] != p["id"]


async def test_merge_moves_everything(env):
    keep = await env.product("Rigtig mælk", barcodes=["4006381333931"], aliases=["mælk"])
    dup = await env.product("Ukendt vare", barcodes=["5701234567899"])
    await env.ops(
        env.op("add", quantity=2, product_id=keep["id"]),
        env.op("add", quantity=3, product_id=dup["id"]),
    )
    await env.client.post(
        "/api/shopping", json={"product_id": keep["id"], "quantity": 1}, headers=env.member
    )
    await env.client.post(
        "/api/shopping", json={"product_id": dup["id"], "quantity": 2}, headers=env.member
    )
    r = await env.client.post(
        f"/api/products/{dup['id']}/merge", json={"into_id": keep["id"]}, headers=env.member
    )
    assert r.status_code == 200, r.text
    merged = r.json()
    assert {b["code"] for b in merged["barcodes"]} == {"04006381333931", "05701234567899"}
    assert await env.total(keep["id"]) == 5
    assert (
        await env.client.get(f"/api/products/{dup['id']}", headers=env.member)
    ).status_code == 404
    # old barcode now resolves to the surviving product and scans add to it
    (res,) = await env.ops(env.op("add", barcode="5701234567899"))
    assert res["product"]["id"] == keep["id"] and res["total_quantity"] == 6
    shopping = (await env.client.get("/api/shopping", headers=env.member)).json()
    assert (
        len(shopping) == 1
        and shopping[0]["quantity"] == 3
        and shopping[0]["product_id"] == keep["id"]
    )
    txns = (
        await env.client.get(
            "/api/transactions", params={"product_id": keep["id"]}, headers=env.member
        )
    ).json()
    assert len(txns) == 3
    # self merge / unknown target
    r = await env.client.post(
        f"/api/products/{keep['id']}/merge", json={"into_id": keep["id"]}, headers=env.member
    )
    assert r.status_code == 422
    r = await env.client.post(
        f"/api/products/{keep['id']}/merge", json={"into_id": str(uuid.uuid4())}, headers=env.member
    )
    assert r.status_code == 404


async def test_locations_and_categories_crud(env):
    r = await env.client.post(
        "/api/locations", json={"name": "Garage", "icon": "car"}, headers=env.member
    )
    assert r.status_code == 201 and r.json()["is_default"] is False
    loc = r.json()
    r = await env.client.patch(
        f"/api/locations/{loc['id']}", json={"is_default": True}, headers=env.member
    )
    assert r.json()["is_default"] is True
    locs = (await env.client.get("/api/locations", headers=env.member)).json()
    assert [x["name"] for x in locs if x["is_default"]] == ["Garage"]
    # default location cannot be deleted; stocked location cannot be deleted
    r = await env.client.delete(f"/api/locations/{loc['id']}", headers=env.admin)
    assert r.status_code == 409 and r.json()["code"] == "default_location"
    p = await env.product()
    await env.ops(env.op("add", product_id=p["id"], location_id=env.locations["Fryser"]))
    r = await env.client.delete(f"/api/locations/{env.locations['Fryser']}", headers=env.admin)
    assert r.status_code == 409 and r.json()["code"] == "location_not_empty"
    r = await env.client.delete(f"/api/locations/{env.locations['Andet']}", headers=env.admin)
    assert r.status_code == 204
    names = [x["name"] for x in (await env.client.get("/api/locations", headers=env.member)).json()]
    assert "Andet" not in names
    withdel = (
        await env.client.get(
            "/api/locations", params={"include_deleted": "true"}, headers=env.member
        )
    ).json()
    assert next(x for x in withdel if x["name"] == "Andet")["deleted_at"] is not None

    c = await env.client.post(
        "/api/categories", json={"name": "Baby", "color": "#fff"}, headers=env.member
    )
    assert c.status_code == 201
    q = await env.product("Barnemad", category_id=c.json()["id"])
    r = await env.client.delete(f"/api/categories/{c.json()['id']}", headers=env.admin)
    assert r.status_code == 204
    assert (await env.client.get(f"/api/products/{q['id']}", headers=env.member)).json()[
        "category_id"
    ] is None
    assert (
        len((await env.client.get("/api/categories", headers=env.member)).json()) == 12
    )  # seeded defaults
