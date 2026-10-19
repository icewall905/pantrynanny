"""Exports, stats, admin catalogue and Home Assistant summary."""

import csv
import io

import pytest

from pantrynanny.models import LookupAttempt


async def seed(env):
    milk = await env.product(
        "Økologisk Mælk æøå",
        brand="Thise",
        min_stock=3,
        stock_unit="pcs",
        barcodes=["5705830010018"],
    )
    bread = await env.product('Rugbrød; "stærkt"', brand="Kohberg")
    await env.ops(
        env.op("add", 2, product_id=milk["id"], expires_at="2020-01-01"),
        env.op("add", 3, product_id=bread["id"]),
    )
    await env.ops(env.op("remove", 1, product_id=bread["id"]))
    return milk, bread


@pytest.mark.parametrize("res", ["inventory", "shopping", "expiring", "products", "transactions"])
async def test_exports_exist_in_both_formats(env, res):
    await seed(env)
    for fmt in ("csv", "json"):
        r = await env.client.get(f"/api/export/{res}.{fmt}", headers=env.member)
        assert r.status_code == 200, r.text
        assert "attachment" in r.headers["content-disposition"]
        assert f"pantrynanny-{res}-" in r.headers["content-disposition"]
    assert (await env.client.get("/api/export/nope.csv", headers=env.member)).status_code == 404


async def test_csv_bom_separator_and_danish_roundtrip(env):
    await seed(env)
    r = await env.client.get("/api/export/inventory.csv", headers=env.member)
    raw = r.content
    assert raw.startswith(b"\xef\xbb\xbf")
    text = raw.decode("utf-8-sig")
    rows = list(csv.reader(io.StringIO(text), delimiter=";"))
    header = rows[0]
    assert header[:3] == ["product_id", "name", "brand"]
    names = {row[header.index("name")] for row in rows[1:]}
    assert names == {"Økologisk Mælk æøå", 'Rugbrød; "stærkt"'}  # quoting round-trips
    bread = next(row for row in rows[1:] if row[1].startswith("Rugbr"))
    assert bread[header.index("quantity")] == "2"
    assert "\r\n" in text


async def test_csv_decimal_comma_and_formula_guard(env):
    p = await env.product("=HYPERLINK(1)", package_size=1.5, package_unit="l")
    r = await env.client.get("/api/export/products.csv", headers=env.member)
    rows = list(csv.reader(io.StringIO(r.content.decode("utf-8-sig")), delimiter=";"))
    h = rows[0]
    assert rows[1][h.index("name")] == "'=HYPERLINK(1)"
    assert rows[1][h.index("package_size")] == "1,5"
    j = (await env.client.get("/api/export/products.json", headers=env.member)).json()
    assert j[0]["package_size"] == 1.5 and j[0]["id"] == p["id"]


async def test_expiring_export_lists_expired_batch(env):
    await seed(env)
    j = (await env.client.get("/api/export/expiring.json", headers=env.member)).json()
    assert [x["name"] for x in j] == ["Økologisk Mælk æøå"]


async def test_stats(env):
    milk, bread = await seed(env)
    r = await env.client.get("/api/stats?days=7", headers=env.member)
    assert r.status_code == 200
    s = r.json()
    assert len(s["daily"]) == 7
    assert s["daily"][-1]["added"] == 5 and s["daily"][-1]["removed"] == 1
    assert {t["name"] for t in s["top_added"]} == {"Økologisk Mælk æøå", 'Rugbrød; "stærkt"'}
    assert s["top_consumed"][0]["product_id"] == bread["id"]
    assert s["top_consumed"][0]["quantity"] == 1
    r = await env.client.get(f"/api/stats?days=3&product_id={bread['id']}", headers=env.member)
    assert r.json()["series"][-1]["quantity"] == 2
    assert (await env.client.get("/api/stats?days=0", headers=env.member)).status_code == 422


async def test_admin_catalogue_and_lookups(env, app):
    await env.product("Mælk", brand="Arla", barcodes=["5705830010018"])
    await env.product("Mælk", brand="Arla", barcodes=["5705830020017"])
    await env.product("Cola", brand="Coop")
    async with app.state.sessionmaker() as s, s.begin():
        s.add_all(
            [
                LookupAttempt(
                    household_id=env.household_id,
                    code="1",
                    provider="openfoodfacts",
                    status="not_found",
                ),
                LookupAttempt(
                    household_id=env.household_id,
                    code="2",
                    provider="openfoodfacts",
                    status="found",
                ),
                LookupAttempt(
                    household_id=env.household_id,
                    code="2",
                    provider="openfoodfacts",
                    status="cache_hit",
                ),
                LookupAttempt(
                    household_id=env.household_id,
                    code="3",
                    provider="openfoodfacts",
                    status="error",
                    error="HTTP 503",
                ),
            ]
        )
    r = await env.client.get("/api/admin/catalogue", headers=env.admin)
    assert r.status_code == 200, r.text
    c = r.json()
    assert c["by_status"]["known"] == 3 and c["by_source"]["user"] == 3
    assert {f["barcode"] for f in c["failed_lookups"]} == {"1", "3"}
    assert len(c["duplicate_candidates"]) == 1
    d = c["duplicate_candidates"][0]
    assert d["reason"] == "same_name" and d["a"]["name"] == "Mælk"
    ls = c["lookup_stats"]
    assert (ls["attempts"], ls["hits"], ls["misses"], ls["errors"]) == (4, 2, 1, 1)
    assert ls["cache_hit_rate"] == 0.25
    r = await env.client.get("/api/admin/lookups?status=error", headers=env.admin)
    assert [a["barcode"] for a in r.json()] == ["3"]
    assert (
        await env.client.get("/api/admin/lookups?status=bogus", headers=env.admin)
    ).status_code == 422


async def test_admin_endpoints_require_admin(env):
    for path in ("/api/admin/catalogue", "/api/admin/lookups", "/api/admin/providers"):
        assert (await env.client.get(path, headers=env.member)).status_code == 403
    r = await env.client.patch(
        "/api/admin/providers", json={"providers": [{"name": "nope"}]}, headers=env.admin
    )
    assert r.status_code == 422
    r = await env.client.patch(
        "/api/admin/providers",
        json={"providers": [{"name": "openfoodfacts", "enabled": False}]},
        headers=env.member,
    )
    assert r.status_code == 403


async def test_ha_summary_requires_bearer(env, client):
    milk = await env.product("Mælk", min_stock=5)
    await env.ops(env.op("add", 1, product_id=milk["id"], expires_at="2020-01-01"))
    assert (await client.get("/api/ha/summary")).status_code == 401
    r = await client.get("/api/ha/summary", headers=env.member)
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["low_stock"] == ["Mælk"] and j["low_stock_count"] == 1
    assert j["expired_count"] == 1 and j["products_in_stock"] == 1
    assert "shopping_open_count" in j and "generated_at" in j
