"""AI endpoint settings in the admin UI, the connectivity test, and reasoning-model robustness."""

import json

import httpx
import pytest

from pantrynanny.ai.client import AIClient, clean_content
from pantrynanny.config import Settings
from pantrynanny.routers.ai import ai_limiter

from .conftest import TEST_DB_URL


@pytest.fixture(autouse=True)
def _reset(app):
    ai_limiter.reset()
    yield
    ai_limiter.reset()
    if hasattr(app.state, "ai_client"):
        del app.state.ai_client


class ReasoningAI:
    """Behaves like llama.cpp serving a thinking model: with thinking on, the token budget is used
    up by reasoning_content and content stays empty; with enable_thinking=false it answers."""

    def __init__(self, answer="Hej! Mælken står i køleskabet.", vision=True, always_empty=False):
        self.answer, self.vision, self.always_empty = answer, vision, always_empty
        self.requests: list[dict] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": "qwen3-vl", "object": "model"}]})
        body = json.loads(request.content)
        self.requests.append(body)
        no_think = (body.get("chat_template_kwargs") or {}).get("enable_thinking") is False
        content = body["messages"][-1]["content"]
        if isinstance(content, list) and not self.vision:
            return httpx.Response(400, json={"error": {"message": "image input is not supported"}})
        if self.always_empty or not no_think:
            msg = {
                "role": "assistant",
                "content": "",
                "reasoning_content": "Hmm, let me think " * 200,
            }
            return httpx.Response(
                200, json={"choices": [{"message": msg, "finish_reason": "length"}]}
            )
        text = "Red and blue" if isinstance(content, list) else self.answer
        if "exactly one word" in str(content):
            text = "OK"
        msg = {"role": "assistant", "content": text}
        return httpx.Response(200, json={"choices": [{"message": msg, "finish_reason": "stop"}]})


def install(app, fake, **kw):
    cfg = Settings(database_url=TEST_DB_URL, ai_base_url="http://ai.test/v1", **kw)
    app.state.ai_client = AIClient(cfg, transport=httpx.MockTransport(fake.handler))
    return app.state.ai_client


def test_clean_content_drops_open_think_blocks():
    assert clean_content("<think>a</think> Svar") == "Svar"
    assert clean_content("<think>cut off by the token limit") == ""
    assert clean_content(None) == ""


async def test_empty_reasoning_answer_is_retried_without_thinking(env, app):
    fake = ReasoningAI()
    install(app, fake)
    r = await env.client.post(
        "/api/ai/chat",
        headers=env.member,
        json={"messages": [{"role": "user", "content": "Hvor er mælken?"}]},
    )
    assert r.status_code == 200, r.text
    assert "køleskabet" in r.json()["reply"]
    assert any(
        (b.get("chat_template_kwargs") or {}).get("enable_thinking") is False for b in fake.requests
    )


async def test_still_empty_gives_actionable_error(env, app):
    install(app, ReasoningAI(always_empty=True))
    r = await env.client.post(
        "/api/ai/chat",
        headers=env.member,
        json={"messages": [{"role": "user", "content": "hej"}]},
    )
    assert r.status_code == 502
    assert r.json()["code"] == "ai_empty_response"
    assert "reasoning" in r.json()["detail"] and "Admin" in r.json()["detail"]


async def test_admin_can_set_endpoint_and_member_cannot(env, app):
    fake = ReasoningAI()
    install(app, fake)  # env default endpoint; the UI overrides it
    c = env.client
    assert (await c.get("/api/admin/ai", headers=env.member)).status_code == 403
    r = await c.patch(
        "/api/admin/ai",
        headers=env.admin,
        json={
            "base_url": "http://10.0.10.23:8080/v1/",
            "api_key": "sk-local-secret-123456",
            "model": "qwen3-vl",
            "timeout_s": 180,
            "disable_thinking": True,
            "features": {"recipes": False},
        },
    )
    assert r.status_code == 200, r.text
    cfg = r.json()["config"]
    assert cfg["base_url"] == "http://10.0.10.23:8080/v1"
    assert cfg["api_key"] is None and cfg["has_api_key"] is True  # never echoed
    assert cfg["timeout_s"] == 180 and cfg["disable_thinking"] is True
    assert cfg["features"] == {"chat": True, "recipes": False, "photo": True}
    assert "sk-local" not in r.text

    # the setting is used straight away: the recipes feature is off, chat sends no-thinking
    status = (await c.get("/api/ai/status", headers=env.member)).json()
    assert status["features"]["recipes"] is False
    r = await c.post("/api/ai/recipes", headers=env.member, json={"prompt": "pasta"})
    assert r.status_code == 503 and "turned off" in r.json()["detail"]

    # clearing a field falls back to the environment value
    r = await c.patch("/api/admin/ai", headers=env.admin, json={"base_url": None, "api_key": ""})
    assert r.json()["config"]["base_url"] == "http://ai.test/v1"
    assert r.json()["config"]["has_api_key"] is False

    r = await c.patch("/api/admin/ai", headers=env.admin, json={"base_url": "ftp://x"})
    assert r.status_code == 422


async def test_connectivity_test_reports_each_step(env, app):
    install(app, ReasoningAI())
    r = await env.client.post("/api/admin/ai/test", headers=env.admin)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["model"] == "qwen3-vl"
    assert out["steps"]["models"]["ok"] and out["steps"]["models"]["models"] == ["qwen3-vl"]
    text = out["steps"]["text"]
    assert text["ok"] and text["answer"] == "OK" and text["retried_without_thinking"] is True
    assert out["steps"]["vision"]["ok"] and out["steps"]["vision"]["looks_right"] is True


async def test_connectivity_test_explains_missing_vision(env, app):
    install(app, ReasoningAI(vision=False), ai_timeout_s=30)
    r = await env.client.post(
        "/api/admin/ai/test", headers=env.admin, json={"disable_thinking": True}
    )
    out = r.json()
    assert out["steps"]["text"]["ok"] is True
    vision = out["steps"]["vision"]
    assert vision["ok"] is False and "not supported" in vision["error"]
    # testing unsaved values did not store them
    saved = (await env.client.get("/api/admin/ai", headers=env.admin)).json()
    assert saved["config"]["disable_thinking"] is False
