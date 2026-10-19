"""Activity timeline, run-out forecasts and shops on the shopping list."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from pantrynanny.services.forecast import confidence, estimate


def test_forecast_needs_enough_history():
    now = datetime(2026, 10, 19, tzinfo=UTC)
    assert estimate(Decimal(2), 2, now - timedelta(days=30), now, Decimal(5)) is None
    per_day, days_left, span, conf = estimate(
        Decimal(6), 6, now - timedelta(days=30), now, Decimal(4)
    )
    assert round(per_day, 2) == 0.2 and round(days_left) == 20 and conf == "high"
    # a burst of use on one day is spread over at least a week, not extrapolated wildly
    per_day, days_left, span, conf = estimate(
        Decimal(3), 3, now - timedelta(hours=2), now, Decimal(3)
    )
    assert span == 7 and conf == "medium" and round(days_left) == 7
    assert confidence(10, 30) == "high" and confidence(1, 30) is None


async def test_runout_endpoint(env):
    c = env.client
    milk = await env.product("Mælk")
    rare = await env.product("Kapers")
    now = datetime.now(UTC)
    await env.ops(
        env.op(
            "add",
            product_id=milk["id"],
            quantity=20,
            occurred_at=(now - timedelta(days=30)).isoformat(),
        )
    )
    for d in (28, 21, 14, 7, 3, 1):
        await env.ops(
            env.op(
                "remove",
                product_id=milk["id"],
                quantity=2,
                occurred_at=(now - timedelta(days=d)).isoformat(),
            )
        )
    await env.ops(
        env.op("add", product_id=rare["id"], quantity=2),
        env.op("remove", product_id=rare["id"], quantity=1),
    )
    r = await c.get("/api/stats/runout?days=30", headers=env.member)
    assert r.status_code == 200, r.text
    rows = r.json()
    assert [x["name"] for x in rows] == ["Mælk"]  # Kapers: too little history for a forecast
    m = rows[0]
    assert m["total_quantity"] == 8 and m["confidence"] == "high"
    assert 15 < m["days_left"] < 25
    assert (await c.get("/api/stats/runout?days=5", headers=env.member)).json() == []
    one = (await c.get(f"/api/stats/runout?product_id={milk['id']}", headers=env.member)).json()
    assert len(one) == 1


async def test_activity_timeline_names_people_and_products(env):
    p = await env.product("Rugbrød")
    await env.ops(env.op("add", product_id=p["id"], quantity=2))
    await env.ops(env.op("remove", product_id=p["id"], quantity=1), headers=env.admin)
    r = await env.client.get("/api/activity?limit=1", headers=env.member)
    assert r.status_code == 200 and r.headers.get("X-Next-Before")
    first = r.json()[0]
    assert first["type"] == "remove" and first["product"]["name"] == "Rugbrød"
    assert first["user_name"] == "Owner"
    r2 = await env.client.get(
        f"/api/activity?limit=5&before={r.headers['X-Next-Before']}", headers=env.member
    )
    assert [x["type"] for x in r2.json()] == ["add"] and r2.json()[0]["user_name"] == "Member"


async def test_shopping_item_store(env):
    c, h = env.client, env.member
    r = await c.post("/api/shopping", json={"name": "Kaffe", "store": "  Netto "}, headers=h)
    assert r.status_code == 201 and r.json()["store"] == "Netto"
    item = r.json()
    r = await c.patch(
        f"/api/shopping/{item['id']}",
        json={"store": "Rema 1000"},
        headers={**h, "If-Match": str(item["version"])},
    )
    assert r.status_code == 200 and r.json()["store"] == "Rema 1000"
    r = await c.patch(
        f"/api/shopping/{item['id']}",
        json={"store": ""},
        headers={**h, "If-Match": str(r.json()["version"])},
    )
    assert r.json()["store"] is None
