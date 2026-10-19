"""Grounded AI tools for recipes/meal plan/forecasts, and proposals that never execute by themselves."""

from datetime import date, timedelta

import pytest

from pantrynanny.routers.ai import ai_limiter

from .test_ai import FakeAI, install, tool_call


@pytest.fixture(autouse=True)
def _reset(app):
    ai_limiter.reset()
    yield
    ai_limiter.reset()
    if hasattr(app.state, "ai_client"):
        del app.state.ai_client


async def _chat(env, text):
    return await env.client.post(
        "/api/ai/chat",
        headers=env.member,
        json={"messages": [{"role": "user", "content": text}], "locale": "da"},
    )


async def test_what_can_we_cook_tool_uses_saved_recipes(env, app):
    eggs = await env.product("Æg")
    await env.ops(env.op("add", product_id=eggs["id"], quantity=6))
    await env.client.post(
        "/api/recipes",
        json={"title": "Omelet", "ingredients": [{"raw": "3 æg"}, {"raw": "1 dl fløde"}]},
        headers=env.member,
    )
    fake = FakeAI([tool_call("what_can_we_cook", {}), "Omelet – I mangler kun fløde."])
    install(app, fake)
    r = await _chat(env, "Hvad kan vi lave?")
    assert r.status_code == 200, r.text
    tool_msg = next(m for m in fake.requests[1]["messages"] if m["role"] == "tool")
    assert "Omelet" in tool_msg["content"] and "fløde" in tool_msg["content"]
    assert "PANTRY_DATA" in tool_msg["content"]  # still wrapped as untrusted
    assert r.json()["proposals"] == []


async def test_proposals_are_returned_but_nothing_changes(env, app):
    c, h = env.client, env.member
    milk = await env.product("Mælk")
    await env.ops(env.op("add", product_id=milk["id"], quantity=2))
    rec = (
        await c.post(
            "/api/recipes",
            json={"title": "Pandekager", "ingredients": [{"raw": "3 æg"}]},
            headers=h,
        )
    ).json()
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    fake = FakeAI(
        [
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "a",
                        "type": "function",
                        "function": {
                            "name": "propose_add_to_shopping",
                            "arguments": '{"name": "mælk", "quantity": 2}',
                        },
                    },
                    {
                        "id": "b",
                        "type": "function",
                        "function": {
                            "name": "propose_plan_meal",
                            "arguments": f'{{"recipe": "pandekager", "day": "{tomorrow}"}}',
                        },
                    },
                    {
                        "id": "c",
                        "type": "function",
                        "function": {
                            "name": "propose_use_up",
                            "arguments": '{"product": "Mælk", "quantity": 9}',
                        },
                    },
                    {
                        "id": "d",
                        "type": "function",
                        "function": {
                            "name": "propose_use_up",
                            "arguments": '{"product": "Kaviar"}',
                        },
                    },
                ],
            },
            "Jeg har lavet tre forslag – tryk for at bekræfte.",
        ]
    )
    install(app, fake)
    r = await _chat(env, "Sæt mælk på listen, planlæg pandekager i morgen og træk mælken fra")
    assert r.status_code == 200, r.text
    props = r.json()["proposals"]
    assert [p["kind"] for p in props] == ["shopping_add", "meal_plan", "consume"]
    assert props[0]["payload"] == {"name": "Mælk", "quantity": 2, "product_id": milk["id"]}
    assert props[1]["payload"] == {"recipe_id": rec["id"], "day": tomorrow, "slot": "dinner"}
    assert props[2]["payload"]["quantity"] == 2  # capped to what is in stock
    # the unknown product was refused back to the model, not proposed
    tool_msgs = [m for m in fake.requests[1]["messages"] if m["role"] == "tool"]
    assert "not in stock" in tool_msgs[3]["content"]
    # and NOTHING happened
    assert (await c.get("/api/shopping", headers=h)).json() == []
    plan = (await c.get(f"/api/meal-plan?start={date.today()}&days=7", headers=h)).json()
    assert plan == []
    inv = (await c.get(f"/api/inventory/{milk['id']}", headers=h)).json()
    assert inv["total_quantity"] == 2


async def test_proposals_are_capped_and_validated(env, app):
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    calls = [
        {
            "id": str(i),
            "type": "function",
            "function": {"name": "propose_add_to_shopping", "arguments": '{"name": "x"}'},
        }
        for i in range(4)
    ]
    fake = FakeAI(
        [
            {"role": "assistant", "content": None, "tool_calls": calls},
            {"role": "assistant", "content": None, "tool_calls": calls},
            tool_call("propose_plan_meal", {"recipe": "Noget", "day": yesterday}),
            "ok",
        ]
    )
    install(app, fake)
    r = await _chat(env, "Fyld listen")
    assert len(r.json()["proposals"]) == 5
    last_tool = [m for m in fake.requests[3]["messages"] if m["role"] == "tool"][-1]
    assert "between today" in last_tool["content"]
