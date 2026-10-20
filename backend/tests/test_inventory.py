import asyncio
import uuid

from sqlalchemy import func, select

from pantrynanny.models import StockBatch, StockTransaction


async def inv(env, **params):
    r = await env.client.get("/api/inventory", params=params, headers=env.member)
    assert r.status_code == 200, r.text
    return r.json()


async def test_add_one(env):
    p = await env.product("Mælk")
    (res,) = await env.ops(env.op("add", product_id=p["id"]))
    assert res["status"] == "applied" and res["error"] is None
    assert res["total_quantity"] == 1 and res["product"]["id"] == p["id"]
    items = await inv(env)
    assert len(items) == 1 and items[0]["total_quantity"] == 1
    # default location = household default (the fridge)
    assert items[0]["batches"][0]["location_id"] == env.locations["Køleskab"]


async def test_location_resolution_prefers_op_then_product_default(env):
    p = await env.product("Smør", default_location_id=env.locations["Køleskab"])
    a, b = await env.ops(
        env.op("add", product_id=p["id"]),
        env.op("add", product_id=p["id"], location_id=env.locations["Fryser"]),
    )
    assert a["status"] == b["status"] == "applied"
    item = (await inv(env))[0]
    by_loc = {x["location_id"]: x["quantity"] for x in item["batches"]}
    assert by_loc == {env.locations["Køleskab"]: 1, env.locations["Fryser"]: 1}
    r = await env.client.get(
        "/api/inventory", params={"location_id": env.locations["Fryser"]}, headers=env.member
    )
    assert r.json()[0]["total_quantity"] == 1 and r.json()[0]["product"]["id"] == p["id"]


async def test_remove_one(env):
    p = await env.product()
    await env.ops(env.op("add", quantity=3, product_id=p["id"]))
    (res,) = await env.ops(env.op("remove", product_id=p["id"]))
    assert res["status"] == "applied" and res["total_quantity"] == 2
    assert await env.total(p["id"]) == 2


async def test_add_multiple_identical_merges_into_one_batch(env):
    p = await env.product()
    ops = [env.op("add", product_id=p["id"], expires_at="2026-12-01") for _ in range(5)]
    results = await env.ops(*ops)
    assert [r["status"] for r in results] == ["applied"] * 5
    item = (await inv(env))[0]
    assert item["total_quantity"] == 5 and len(item["batches"]) == 1
    assert item["next_expiry"] == "2026-12-01"
    # different expiry -> separate batch
    await env.ops(env.op("add", product_id=p["id"], expires_at="2026-11-01"))
    item = (await inv(env))[0]
    assert len(item["batches"]) == 2 and item["next_expiry"] == "2026-11-01"


async def test_decimal_quantities(env):
    p = await env.product("Mel", stock_unit="kg")
    await env.ops(env.op("add", quantity=1.5, product_id=p["id"]))
    (res,) = await env.ops(env.op("remove", quantity=0.25, product_id=p["id"]))
    assert res["total_quantity"] == 1.25


async def test_negative_stock_is_clamped_by_default(env):
    p = await env.product()
    await env.ops(env.op("add", quantity=2, product_id=p["id"]))
    (res,) = await env.ops(env.op("remove", quantity=5, product_id=p["id"]))
    assert res["status"] == "applied" and res["error"] == "clamped"
    assert res["total_quantity"] == 0
    txn = (await env.client.get("/api/transactions", headers=env.member)).json()[0]
    assert txn["quantity_delta"] == -2
    # removing from empty stock: still recorded (zero delta), idempotent on retry
    op = env.op("remove", product_id=p["id"])
    (r1,) = await env.ops(op)
    (r2,) = await env.ops(op)
    assert r1["status"] == "applied" and r1["error"] == "clamped" and r1["total_quantity"] == 0
    assert r2["status"] == "duplicate" and r2["transaction_id"] == r1["transaction_id"]


async def test_negative_stock_allowed_when_enabled(env):
    await env.client.patch("/api/settings", json={"allow_negative_stock": True}, headers=env.admin)
    p = await env.product()
    await env.ops(env.op("add", quantity=1, product_id=p["id"]))
    (res,) = await env.ops(env.op("remove", quantity=3, product_id=p["id"]))
    assert res["status"] == "applied" and res["error"] is None and res["total_quantity"] == -2
    (res,) = await env.ops(env.op("add", quantity=2, product_id=p["id"]))
    assert res["total_quantity"] == 0


async def test_fifo_by_expiry_nulls_last(env):
    p = await env.product()
    loc = env.locations["Køleskab"]
    await env.ops(
        env.op("add", quantity=2, product_id=p["id"], location_id=loc),  # no expiry
        env.op("add", quantity=2, product_id=p["id"], location_id=loc, expires_at="2026-12-10"),
        env.op("add", quantity=2, product_id=p["id"], location_id=loc, expires_at="2026-11-01"),
    )
    (res,) = await env.ops(env.op("remove", quantity=3, product_id=p["id"], location_id=loc))
    assert res["total_quantity"] == 3
    batches = {b["expires_at"]: b["quantity"] for b in (await inv(env))[0]["batches"]}
    # earliest (Nov) emptied first and dropped from view, then Dec partly, no-expiry untouched
    assert batches == {"2026-12-10": 1, None: 2}


async def test_remove_prefers_target_location_then_others(env):
    p = await env.product()
    fridge, freezer = env.locations["Køleskab"], env.locations["Fryser"]
    await env.ops(
        env.op("add", quantity=1, product_id=p["id"], location_id=fridge, expires_at="2026-11-01"),
        env.op("add", quantity=2, product_id=p["id"], location_id=freezer, expires_at="2027-01-01"),
    )
    # remove at freezer: freezer stock first even though the fridge batch expires sooner
    (res,) = await env.ops(env.op("remove", quantity=1, product_id=p["id"], location_id=freezer))
    assert res["total_quantity"] == 2
    by_loc = {b["location_id"]: b["quantity"] for b in (await inv(env))[0]["batches"]}
    assert by_loc == {fridge: 1, freezer: 1}
    # asking for more than the freezer has spills over into the fridge
    (res,) = await env.ops(env.op("remove", quantity=1.5, product_id=p["id"], location_id=freezer))
    assert res["total_quantity"] == 0.5
    by_loc = {b["location_id"]: b["quantity"] for b in (await inv(env))[0]["batches"]}
    assert by_loc == {fridge: 0.5}  # freezer batch emptied (hidden), remainder from the fridge


async def test_adjust_signed(env):
    p = await env.product()
    await env.ops(env.op("add", quantity=4, product_id=p["id"]))
    (up,) = await env.ops(env.op("adjust", quantity=3, product_id=p["id"], reason="fundet"))
    (down,) = await env.ops(env.op("adjust", quantity=-5, product_id=p["id"]))
    assert up["total_quantity"] == 7 and down["total_quantity"] == 2
    zero = (await env.ops(env.op("adjust", quantity=0, product_id=p["id"])))[0]
    assert zero["status"] == "rejected" and zero["error_code"] == "invalid_quantity"


async def test_move_between_locations(env):
    p = await env.product()
    pantry, freezer = env.locations["Spisekammer"], env.locations["Fryser"]
    await env.ops(
        env.op("add", quantity=3, product_id=p["id"], location_id=pantry, expires_at="2026-12-24")
    )
    (res,) = await env.ops(
        env.op("move", quantity=2, product_id=p["id"], location_id=pantry, to_location_id=freezer)
    )
    assert res["status"] == "applied" and res["total_quantity"] == 3  # total unchanged
    batches = {
        b["location_id"]: (b["quantity"], b["expires_at"]) for b in (await inv(env))[0]["batches"]
    }
    assert batches == {pantry: (1, "2026-12-24"), freezer: (2, "2026-12-24")}
    # moving more than available clamps
    (res,) = await env.ops(
        env.op("move", quantity=5, product_id=p["id"], location_id=pantry, to_location_id=freezer)
    )
    assert res["error"] == "clamped"
    batches = {b["location_id"]: b["quantity"] for b in (await inv(env))[0]["batches"]}
    assert batches == {freezer: 3}
    bad = (
        await env.ops(
            env.op("move", product_id=p["id"], location_id=freezer, to_location_id=freezer)
        )
    )[0]
    assert bad["status"] == "rejected"
    missing = (await env.ops(env.op("move", product_id=p["id"])))[0]
    assert missing["status"] == "rejected"


async def test_undo_and_double_undo(env):
    p = await env.product()
    add = env.op("add", quantity=3, product_id=p["id"])
    rem = env.op("remove", quantity=2, product_id=p["id"])
    await env.ops(add, rem)
    assert await env.total(p["id"]) == 1
    undo = env.op("undo", quantity=None, undoes_client_op_id=rem["client_op_id"])
    (res,) = await env.ops(undo)
    assert res["status"] == "applied" and res["total_quantity"] == 3
    # undoing the same original again (new client_op_id) is rejected
    (res2,) = await env.ops(env.op("undo", quantity=None, undoes_client_op_id=rem["client_op_id"]))
    assert res2["status"] == "rejected" and res2["error_code"] == "already_undone"
    # replaying the first undo is a duplicate
    (res3,) = await env.ops(undo)
    assert res3["status"] == "duplicate" and await env.total(p["id"]) == 3
    # unknown original
    (res4,) = await env.ops(env.op("undo", quantity=None, undoes_client_op_id=str(uuid.uuid4())))
    assert res4["status"] == "rejected" and res4["error_code"] == "not_found"
    # an undo cannot be undone
    (res5,) = await env.ops(env.op("undo", quantity=None, undoes_client_op_id=undo["client_op_id"]))
    assert res5["status"] == "rejected"
    txns = (
        await env.client.get(
            "/api/transactions", params={"product_id": p["id"]}, headers=env.member
        )
    ).json()
    original = next(t for t in txns if t["client_op_id"] == rem["client_op_id"])
    assert original["undone"] is True
    undo_txn = next(t for t in txns if t["type"] == "undo")
    assert undo_txn["undoes_id"] == original["id"] and undo_txn["quantity_delta"] == 2


async def test_undo_via_transaction_endpoint(env):
    p = await env.product()
    (res,) = await env.ops(env.op("add", quantity=2, product_id=p["id"]))
    body = {"client_op_id": str(uuid.uuid4())}
    r = await env.client.post(
        f"/api/transactions/{res['transaction_id']}/undo", json=body, headers=env.member
    )
    assert r.status_code == 200 and r.json()["total_quantity"] == 0
    r = await env.client.post(
        f"/api/transactions/{res['transaction_id']}/undo", json=body, headers=env.member
    )
    assert r.status_code == 200 and r.json()["status"] == "duplicate"
    r = await env.client.post(
        f"/api/transactions/{res['transaction_id']}/undo",
        json={"client_op_id": str(uuid.uuid4())},
        headers=env.member,
    )
    assert r.status_code == 409 and r.json()["code"] == "already_undone"


async def test_undo_move_restores_locations(env):
    p = await env.product()
    pantry, freezer = env.locations["Spisekammer"], env.locations["Fryser"]
    await env.ops(env.op("add", quantity=2, product_id=p["id"], location_id=pantry))
    mv = env.op("move", quantity=2, product_id=p["id"], location_id=pantry, to_location_id=freezer)
    await env.ops(mv)
    await env.ops(env.op("undo", quantity=None, undoes_client_op_id=mv["client_op_id"]))
    by_loc = {b["location_id"]: b["quantity"] for b in (await inv(env))[0]["batches"]}
    assert by_loc == {pantry: 2}


async def test_idempotent_retry_counts_once(env):
    p = await env.product()
    op = env.op("add", quantity=2, product_id=p["id"])
    (first,) = await env.ops(op)
    (second,) = await env.ops(op)
    (third,) = await env.ops(op)
    assert first["status"] == "applied"
    assert second["status"] == third["status"] == "duplicate"
    assert second["transaction_id"] == first["transaction_id"]
    assert second["total_quantity"] == 2
    assert await env.total(p["id"]) == 2
    async with env.app.state.sessionmaker() as s:
        n = await s.scalar(select(func.count()).select_from(StockTransaction))
    assert n == 1


async def test_duplicate_within_one_batch_and_across_households_ids(env, other_env):
    p = await env.product()
    op = env.op("add", product_id=p["id"])
    r = await env.ops(op, op)
    assert [x["status"] for x in r] == ["applied", "duplicate"]
    # same client_op_id in another household is independent (uniqueness is per household)
    q = await other_env.product("Andet")
    (res,) = await other_env.ops({**op, "product_id": q["id"]})
    assert res["status"] == "applied"


async def test_concurrent_ops_on_same_product_exact_total(env):
    p = await env.product()
    n_add, n_remove = 30, 10
    await env.ops(env.op("add", quantity=100, product_id=p["id"]))

    async def one(op):
        # each call is its own HTTP request -> own DB sessions/transactions
        r = await env.client.post("/api/sync/ops", json={"ops": [op]}, headers=env.member)
        return r.json()["results"][0]

    ops = [env.op("add", product_id=p["id"]) for _ in range(n_add)]
    ops += [env.op("remove", product_id=p["id"]) for _ in range(n_remove)]
    ops += ops[:5]  # concurrent replays of identical client_op_ids
    results = await asyncio.gather(*(one(o) for o in ops))
    statuses = [r["status"] for r in results]
    assert statuses.count("applied") == n_add + n_remove
    assert statuses.count("duplicate") == 5
    assert await env.total(p["id"]) == 100 + n_add - n_remove
    async with env.app.state.sessionmaker() as s:
        total = await s.scalar(select(func.sum(StockBatch.quantity)))
        txns = await s.scalar(select(func.count()).select_from(StockTransaction))
    assert total == 120 and txns == 1 + n_add + n_remove


async def test_concurrent_removals_never_go_negative(env):
    p = await env.product()
    await env.ops(env.op("add", quantity=5, product_id=p["id"]))
    results = await asyncio.gather(
        *(
            env.client.post(
                "/api/sync/ops",
                json={"ops": [env.op("remove", product_id=p["id"])]},
                headers=env.member,
            )
            for _ in range(12)
        )
    )
    outs = [r.json()["results"][0] for r in results]
    assert sum(1 for o in outs if o["error"] is None) == 5
    assert sum(1 for o in outs if o["error"] == "clamped") == 7
    assert await env.total(p["id"]) == 0


async def test_concurrent_scans_of_same_new_barcode_create_one_product(env):
    code = "5701234567899"
    ops = [env.op("add", barcode=code, symbology="ean_13") for _ in range(10)]
    results = await asyncio.gather(
        *(env.client.post("/api/sync/ops", json={"ops": [o]}, headers=env.member) for o in ops)
    )
    outs = [r.json()["results"][0] for r in results]
    assert all(o["status"] == "applied" for o in outs), outs
    assert len({o["product"]["id"] for o in outs}) == 1
    items = await inv(env)
    assert len(items) == 1 and items[0]["total_quantity"] == 10


async def test_unknown_barcode_creates_placeholder_then_resolves_same_product(env):
    code = "5701234567899"
    (res,) = await env.ops(env.op("add", barcode=code, symbology="ean_13"))
    assert res["status"] == "applied"
    prod = res["product"]
    assert prod["status"] == "unknown" and prod["source"] == "placeholder"
    assert prod["name"].startswith("Ukendt vare")
    assert prod["barcodes"][0]["code"] == "05701234567899"
    assert prod["barcodes"][0]["raw"] == code
    (res2,) = await env.ops(env.op("add", barcode=code))
    assert res2["product"]["id"] == prod["id"] and res2["total_quantity"] == 2
    # same product found via a UPC-A style padded variant
    (res3,) = await env.ops(env.op("remove", barcode="0" + code))
    assert res3["product"]["id"] == prod["id"] and res3["total_quantity"] == 1
    async with env.app.state.sessionmaker() as s:
        queued = (await s.execute(text_count("enrichment_queue"))).scalar_one()
    assert queued == 1


def text_count(table):
    from sqlalchemy import text

    return text(f"SELECT count(*) FROM {table}")


async def test_by_barcode_never_changes_stock(env):
    code = "5701234567899"
    r = await env.client.get(
        f"/api/products/by-barcode/{code}", params={"lookup": "false"}, headers=env.member
    )
    assert r.json()["status"] == "not_found" and r.json()["product"] is None
    r = await env.client.get(f"/api/products/by-barcode/{code}", headers=env.member)
    body = r.json()
    assert r.status_code == 200 and body["status"] == "created_placeholder"
    assert body["product"]["status"] == "unknown" and body["barcode"]["code"] == "05701234567899"
    r = await env.client.get(f"/api/products/by-barcode/{code}", headers=env.member)
    assert r.json()["status"] == "found" and r.json()["product"]["id"] == body["product"]["id"]
    assert await inv(env) == []
    assert await inv(env, include_empty="true") != []
    async with env.app.state.sessionmaker() as s:
        assert await s.scalar(select(func.count()).select_from(StockTransaction)) == 0
        assert await s.scalar(select(func.count()).select_from(StockBatch)) == 0
    # a later scan op resolves the same product
    (res,) = await env.ops(env.op("add", barcode=code))
    assert res["product"]["id"] == body["product"]["id"]


async def test_by_barcode_local_and_instore_codes(env):
    r = await env.client.get("/api/products/by-barcode/NOT-A-GTIN", headers=env.member)
    assert r.json()["barcode"]["code"] == "local:NOT-A-GTIN" and r.json()["valid"] is False
    r = await env.client.get("/api/products/by-barcode/2012345001237", headers=env.member)
    # (checksum may be invalid for this literal; either way it is stable)
    assert r.status_code == 200


async def test_batch_metadata_patch_does_not_change_stock(env):
    p = await env.product()
    await env.ops(env.op("add", quantity=2, product_id=p["id"]))
    batch = (await inv(env))[0]["batches"][0]
    r = await env.client.patch(
        f"/api/batches/{batch['id']}",
        json={"expires_at": "2026-11-30", "opened_at": "2026-10-19"},
        headers=env.member,
    )
    assert r.status_code == 200 and r.json()["expires_at"] == "2026-11-30"
    assert r.json()["quantity"] == 2
    assert (
        await env.client.patch(f"/api/batches/{uuid.uuid4()}", json={}, headers=env.member)
    ).status_code == 404


async def test_inventory_filters_sort_detail_and_dashboard(env):
    milk = await env.product("Mælk", category_id=env.categories["Mejeri"], min_stock=2)
    rice = await env.product("Ris", category_id=env.categories["Kolonial"])
    await env.ops(
        env.op(
            "add",
            quantity=1,
            product_id=milk["id"],
            location_id=env.locations["Køleskab"],
            expires_at="2020-01-01",
        ),
        env.op("add", quantity=5, product_id=rice["id"], location_id=env.locations["Spisekammer"]),
    )
    names = [i["product"]["name"] for i in await inv(env, sort="name")]
    assert names == ["Mælk", "Ris"]
    assert [i["product"]["name"] for i in await inv(env, sort="quantity")] == ["Ris", "Mælk"]
    assert [i["product"]["name"] for i in await inv(env, sort="expiry")] == ["Mælk", "Ris"]
    assert [
        i["product"]["name"] for i in await inv(env, category_id=env.categories["Kolonial"])
    ] == ["Ris"]
    assert [i["product"]["name"] for i in await inv(env, q="maelk")] == ["Mælk"]  # unaccented
    milk_item = (await inv(env, q="mælk"))[0]
    assert milk_item["low_stock"] is True

    d = (await env.client.get(f"/api/inventory/{milk['id']}", headers=env.member)).json()
    assert len(d["transactions"]) == 1 and d["total_quantity"] == 1
    dash = (await env.client.get("/api/dashboard", headers=env.member)).json()
    assert dash["totals"] == {"products_in_stock": 2, "items": 6}
    assert [i["product"]["name"] for i in dash["low_stock"]] == ["Mælk"]
    assert [i["product"]["name"] for i in dash["expired"]] == ["Mælk"]
    assert dash["expiring_soon"] == []
    assert len(dash["recently_added"]) == 2 and dash["recently_added"][0]["product"]["name"]
    assert dash["recently_consumed"] == []
    by_loc = {x["location"]["name"]: x["item_count"] for x in dash["by_location"]}
    assert by_loc["Køleskab"] == 1 and by_loc["Spisekammer"] == 1 and by_loc["Fryser"] == 0
    assert dash["shopping_open_count"] == 0  # no removal happened yet


async def test_ops_validation_and_limits(env):
    p = await env.product()
    r = await env.client.post(
        "/api/sync/ops",
        json={"ops": [env.op("add", product_id=p["id"]) for _ in range(501)]},
        headers=env.member,
    )
    assert r.status_code == 422 and r.json()["code"] == "validation_error"
    (res,) = await env.ops(env.op("add", quantity=0, product_id=p["id"]))
    assert res["status"] == "rejected" and res["error_code"] == "invalid_quantity"
    (res,) = await env.ops(env.op("add", quantity=1))
    assert res["status"] == "rejected" and res["error_code"] == "missing_target"
    (res,) = await env.ops(env.op("add", product_id=p["id"], location_id=str(uuid.uuid4())))
    assert res["status"] == "rejected" and res["error_code"] == "location_not_found"
    # one rejected op does not block later ops in the batch
    r = await env.ops(
        env.op("add", quantity=-1, product_id=p["id"]), env.op("add", product_id=p["id"])
    )
    assert [x["status"] for x in r] == ["rejected", "applied"]


async def test_unknown_place_is_the_fridge_and_moves_are_remembered(env):
    fridge, pantry, freezer = (env.locations[n] for n in ("Køleskab", "Spisekammer", "Fryser"))
    rice = await env.product("Ris")

    async def default():
        return (await env.client.get(f"/api/products/{rice['id']}", headers=env.member)).json()[
            "default_location_id"
        ]

    (a,) = await env.ops(env.op("add", product_id=rice["id"]))
    item = (await inv(env))[0]
    assert item["batches"][0]["location_id"] == fridge
    assert await default() is None  # a fallback is not a decision

    # the user moves it to the pantry: from now on new rice goes there
    (mv,) = await env.ops(env.op("move", product_id=rice["id"], quantity=1, to_location_id=pantry))
    assert mv["status"] == "applied" and await default() == pantry
    await env.ops(env.op("add", product_id=rice["id"]))
    item = (await inv(env))[0]
    assert {b["location_id"]: b["quantity"] for b in item["batches"]} == {pantry: 2}

    # undoing the move forgets it again
    await env.ops(env.op("undo", quantity=None, undoes_client_op_id=mv["client_op_id"]))
    assert await default() == fridge

    # an explicit place on the first add of a new product is learned; later ones are not
    peas = await env.product("Ærter")
    await env.ops(env.op("add", product_id=peas["id"], location_id=freezer))
    await env.ops(env.op("add", product_id=peas["id"], location_id=pantry))
    p = (await env.client.get(f"/api/products/{peas['id']}", headers=env.member)).json()
    assert p["default_location_id"] == freezer
