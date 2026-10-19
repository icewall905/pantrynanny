"""Product lookup pipeline: providers (HTTP mocked with respx), cache, locking, worker, media."""

import io
import json
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
import respx
from PIL import Image
from sqlalchemy import select, text, update

from pantrynanny.config import Settings
from pantrynanny.models import EnrichmentQueue, LookupAttempt, LookupCache
from pantrynanny.services.lookup import runtime
from pantrynanny.services.lookup.parsing import map_category, parse_quantity, provider_code
from pantrynanny.services.lookup.ratelimit import TokenBucket, reset_buckets
from pantrynanny.worker import claim, run_once

from .conftest import TEST_DB_URL

FIXTURES = Path(__file__).parent / "fixtures"
OFF_JSON = json.loads((FIXTURES / "off_arla_letmaelk.json").read_text())
CODE = "5705830010018"
OFF_URL = f"https://world.openfoodfacts.org/api/v2/product/{CODE}.json"
IMG_URL = OFF_JSON["product"]["image_front_url"]


def png_bytes(size=(40, 30), exif=False) -> bytes:
    img = Image.new("RGB", size, (200, 30, 30))
    buf = io.BytesIO()
    if exif:
        ex = Image.Exif()
        ex[0x010F] = "SecretCameraMaker"
        img.save(buf, "JPEG", exif=ex.tobytes())
    else:
        img.save(buf, "PNG")
    return buf.getvalue()


@pytest_asyncio.fixture
async def lookup_on(tmp_path):
    cfg = Settings(
        database_url=TEST_DB_URL,
        off_enabled=True,
        upload_dir=str(tmp_path),
        lookup_timeout_s=2.0,
        off_rate_per_min=600,
        off_worker_rate_per_min=600,
        eansearch_token="",
    )
    runtime.set_settings(cfg)
    reset_buckets()
    await runtime.close_client()
    yield cfg
    runtime.set_settings(None)
    await runtime.close_client()
    reset_buckets()


@pytest.fixture
def off():
    with respx.mock(assert_all_called=False) as m:
        route = m.get(OFF_URL).mock(return_value=httpx.Response(200, json=OFF_JSON))
        img = m.get(IMG_URL).mock(
            return_value=httpx.Response(
                200, content=png_bytes(), headers={"content-type": "image/png"}
            )
        )
        m.route_off = route
        m.route_img = img
        yield m


async def by_barcode(env, code=CODE, **params):
    r = await env.client.get(f"/api/products/by-barcode/{code}", params=params, headers=env.member)
    assert r.status_code == 200, r.text
    return r.json()


# --------------------------------------------------------------------------- pure helpers


@pytest.mark.parametrize(
    ("text_in", "expected"),
    [
        ("1 l", (1, "l", None)),
        ("500 g", (500, "g", None)),
        ("1,5 L", (1.5, "l", None)),
        ("330ml", (330, "ml", None)),
        ("33 cl", (33, "cl", None)),
        ("6 x 33 cl", (1.98, "l", "6 × 33 cl")),
        ("4 x 125 g", (500, "g", "4 × 125 g")),
        ("8 x 250 g", (2, "kg", "8 × 250 g")),
        ("750 g (3 x 250 g)", (750, "g", "3 × 250 g")),
        ("12 stk", (12, "pcs", None)),
        ("16 oz", (453.592, "g", None)),
        ("lidt", (None, None, None)),
        ("", (None, None, None)),
        (None, (None, None, None)),
    ],
)
def test_parse_quantity(text_in, expected):
    size, unit, note = parse_quantity(text_in)
    assert (unit, note) == (expected[1], expected[2])
    assert size == pytest.approx(expected[0]) if expected[0] else size is None


def test_provider_code_and_category():
    assert provider_code("05705830010018") == "5705830010018"
    assert provider_code("00000096385074") == "96385074"  # EAN-8
    assert provider_code("local:abc") is None
    assert map_category(["en:dairies", "en:milks"]) == "Mejeri"
    assert map_category(["en:frozen-foods", "en:meats"]) == "Frost"
    assert map_category(["en:unknown-tag"]) is None


async def test_token_bucket_rate_limits():
    now = [0.0]
    slept: list[float] = []

    async def fake_sleep(s):
        slept.append(s)
        now[0] += s

    b = TokenBucket(60, burst=2, clock=lambda: now[0], sleep=fake_sleep)  # 1 token / s
    assert await b.acquire(0)
    assert await b.acquire(0)
    assert not await b.acquire(0)  # burst used up, no waiting allowed
    assert await b.acquire(1.5)  # may wait ~1 s
    assert slept == [pytest.approx(1.0)]
    assert not await b.acquire(0.5)
    now[0] += 10
    assert await b.acquire(0)


# --------------------------------------------------------------------------- resolve flow


async def test_known_barcode_no_external_call(env, lookup_on, off):
    p = await env.product("Egen mælk", barcodes=[CODE])
    out = await by_barcode(env)
    assert out["status"] == "found" and out["product"]["id"] == p["id"]
    assert off.route_off.call_count == 0


async def test_external_lookup_creates_product_with_attribution(env, lookup_on, off):
    out = await by_barcode(env)
    assert out["status"] == "found" and out["source"] == "openfoodfacts"
    p = out["product"]
    assert p["name"] == "Arla Letmælk"
    assert p["brand"] == "Arla"
    assert p["package_size"] == 1 and p["package_unit"] == "l"
    assert p["category_id"] == env.categories["Mejeri"]
    assert p["allergens"] == ["mælk"]
    assert p["countries"] == ["Denmark"]
    assert p["nutrition"]["energy_kcal"] == 46
    assert p["status"] == "known"
    assert "ODbL" in p["source_attribution"]
    assert p["lookup_confidence"] >= 0.6
    assert p["locked_fields"] == []
    req = off.route_off.calls.last.request
    assert req.headers["user-agent"].startswith("PantryNanny")
    assert "fields=" in str(req.url)
    # subsequent scan: pure DB
    again = await by_barcode(env)
    assert again["product"]["id"] == p["id"]
    assert off.route_off.call_count == 1


async def test_unknown_barcode_gives_placeholder_and_queue(env, lookup_on, off):
    off.get(OFF_URL).mock(return_value=httpx.Response(404, json={"status": 0}))
    out = await by_barcode(env)
    assert out["status"] == "created_placeholder"
    assert out["product"]["status"] == "unknown"
    async with env.app.state.sessionmaker() as s:
        q = (await s.execute(select(EnrichmentQueue))).scalars().all()
        assert len(q) == 1 and q[0].code == "05705830010018"
        cache = (await s.execute(select(LookupCache))).scalar_one()
        assert cache.status == "not_found"


@pytest.mark.parametrize("failure", ["timeout", "500"])
async def test_provider_down_keeps_scanning_working(env, lookup_on, off, failure):
    if failure == "timeout":
        off.get(OFF_URL).mock(side_effect=httpx.ConnectTimeout("slow"))
    else:
        off.get(OFF_URL).mock(return_value=httpx.Response(503))
    out = await by_barcode(env)
    assert out["status"] == "created_placeholder"
    # the scan itself still works
    res = await env.ops(env.op("add", 1, barcode=CODE))
    assert res[0]["status"] == "applied"
    async with env.app.state.sessionmaker() as s:
        cache = (await s.execute(select(LookupCache))).scalar_one()
        assert cache.status == "error" and cache.retry_after > datetime.now(UTC)
        att = (await s.execute(select(LookupAttempt))).scalars().all()
        assert att and att[0].status == "error"


async def test_error_backoff_prevents_hammering(env, lookup_on, off):
    off.get(OFF_URL).mock(return_value=httpx.Response(500))
    await by_barcode(env, "5705830020017")  # different product, unaffected below
    off.get(f"https://world.openfoodfacts.org/api/v2/product/{CODE}.json").mock(
        return_value=httpx.Response(500)
    )
    await by_barcode(env)
    calls = off.calls.call_count
    await by_barcode(env)  # known placeholder now: DB only
    from pantrynanny.services.lookup import lookup_external

    async with env.app.state.sessionmaker() as s:
        assert await lookup_external(s, env.household_id, "05705830010018") is None
    assert off.calls.call_count == calls  # error cached with retry_after -> no new HTTP call


async def test_cached_lookup_is_reused(env, lookup_on, off):
    from pantrynanny.services.lookup import lookup_external

    async with env.app.state.sessionmaker() as s:
        d1 = await lookup_external(s, env.household_id, "05705830010018")
    async with env.app.state.sessionmaker() as s:
        d2 = await lookup_external(s, env.household_id, "05705830010018")
    assert d1 is not None and d2 is not None and d1.name == d2.name == "Arla Letmælk"
    assert off.route_off.call_count == 1
    async with env.app.state.sessionmaker() as s:
        statuses = [a.status for a in (await s.execute(select(LookupAttempt))).scalars()]
    assert sorted(statuses) == ["cache_hit", "found"]


async def test_negative_cache_and_expiry(env, lookup_on, off):
    from pantrynanny.services.lookup import lookup_external

    off.get(OFF_URL).mock(return_value=httpx.Response(404, json={"status": 0}))
    for _ in range(2):
        async with env.app.state.sessionmaker() as s:
            assert await lookup_external(s, env.household_id, "05705830010018") is None
    assert off.calls.call_count == 1
    # after the 7 day TTL it is asked again
    async with env.app.state.sessionmaker() as s, s.begin():
        await s.execute(
            update(LookupCache).values(fetched_at=datetime.now(UTC) - timedelta(days=8))
        )
    async with env.app.state.sessionmaker() as s:
        await lookup_external(s, env.household_id, "05705830010018")
    assert off.calls.call_count == 2


async def test_rate_limited_lookup_skips_http(env, lookup_on, off):
    from pantrynanny.services.lookup import lookup_external

    lookup_on.off_rate_per_min = 1
    reset_buckets()
    async with env.app.state.sessionmaker() as s:
        await lookup_external(s, env.household_id, "05705830020017")  # uses the only token
    async with env.app.state.sessionmaker() as s:
        assert await lookup_external(s, env.household_id, "05705830010018") is None
    assert all("5705830010018" not in str(c.request.url) for c in off.calls)


async def test_disabled_provider_and_admin_override(env, lookup_on, off):
    lookup_on.off_enabled = False
    out = await by_barcode(env)
    assert out["status"] == "created_placeholder" and off.calls.call_count == 0
    r = await env.client.patch(
        "/api/admin/providers",
        json={"providers": [{"name": "openfoodfacts", "enabled": True}]},
        headers=env.admin,
    )
    assert r.status_code == 200
    names = {p["id"]: p for p in r.json()["providers"]}
    assert names["openfoodfacts"]["enabled"] is True


# --------------------------------------------------------------------------- manual precedence


async def test_locked_fields_survive_refresh_and_enrichment(env, lookup_on, off):
    out = await by_barcode(env)
    pid, version = out["product"]["id"], out["product"]["version"]
    r = await env.client.patch(
        f"/api/products/{pid}",
        json={"name": "Min mælk", "brand": None},
        headers={**env.member, "If-Match": str(version)},
    )
    assert r.status_code == 200 and set(r.json()["locked_fields"]) == {"name", "brand"}
    r = await env.client.post(f"/api/products/{pid}/refresh", headers=env.member)
    assert r.status_code == 200, r.text
    p = r.json()
    assert p["name"] == "Min mælk" and p["brand"] is None  # locked, even though provider has them
    assert p["image_url"] and p["image_url"].startswith("/api/media/")  # unlocked: filled
    assert off.route_off.call_count == 2  # refresh bypassed the fresh cache


async def test_user_created_product_only_gets_gaps_filled(env, lookup_on, off):
    p = await env.product("Husets mælk", barcodes=[CODE], brand="Brugerens")
    r = await env.client.post(f"/api/products/{p['id']}/refresh", headers=env.member)
    q = r.json()
    assert q["name"] == "Husets mælk" and q["brand"] == "Brugerens" and q["source"] == "user"
    assert q["ingredients"] == "Letmælk (mælk)"  # empty field filled
    assert "ODbL" in q["source_attribution"]


# --------------------------------------------------------------------------- worker


async def test_worker_upgrades_placeholder(env, lookup_on, off):
    off.get(OFF_URL).mock(return_value=httpx.Response(404, json={"status": 0}))
    out = await by_barcode(env)
    pid = out["product"]["id"]
    off.get(OFF_URL).mock(return_value=httpx.Response(200, json=OFF_JSON))  # now it exists
    async with env.app.state.sessionmaker() as s, s.begin():  # skip negative cache + backoff
        await s.execute(text("DELETE FROM lookup_cache"))
    n = await run_once(env.app.state.sessionmaker)
    assert n == 1
    r = await env.client.get(f"/api/products/{pid}", headers=env.member)
    p = r.json()
    assert p["status"] == "known" and p["name"] == "Arla Letmælk" and p["source"] == "openfoodfacts"
    assert p["image_url"]
    img = Path(lookup_on.upload_dir) / p["image_url"].rsplit("/", 1)[1]
    assert img.is_file() and Image.open(img).format == "WEBP"
    async with env.app.state.sessionmaker() as s:
        assert (await s.execute(select(EnrichmentQueue))).scalar_one().status == "done"


async def test_worker_backoff_when_not_found(env, lookup_on, off):
    off.get(OFF_URL).mock(return_value=httpx.Response(404, json={"status": 0}))
    await by_barcode(env)
    async with env.app.state.sessionmaker() as s, s.begin():
        await s.execute(update(EnrichmentQueue).values(next_attempt_at=datetime.now(UTC)))
    assert await run_once(env.app.state.sessionmaker) == 1
    async with env.app.state.sessionmaker() as s:
        q = (await s.execute(select(EnrichmentQueue))).scalar_one()
        assert q.status == "pending" and q.attempts == 1
        assert q.next_attempt_at > datetime.now(UTC) + timedelta(minutes=30)
    assert await run_once(env.app.state.sessionmaker) == 0  # not due yet


async def test_worker_respects_locked_name_of_placeholder(env, lookup_on, off):
    off.get(OFF_URL).mock(return_value=httpx.Response(404, json={"status": 0}))
    out = await by_barcode(env)
    p = out["product"]
    r = await env.client.patch(
        f"/api/products/{p['id']}",
        json={"name": "Nutella-lignende"},
        headers={**env.member, "If-Match": str(p["version"])},
    )
    assert r.status_code == 200
    off.get(OFF_URL).mock(return_value=httpx.Response(200, json=OFF_JSON))
    async with env.app.state.sessionmaker() as s, s.begin():
        await s.execute(text("DELETE FROM lookup_cache"))
    await run_once(env.app.state.sessionmaker)
    got = (await env.client.get(f"/api/products/{p['id']}", headers=env.member)).json()
    assert got["name"] == "Nutella-lignende"


async def test_claim_skip_locked_allows_concurrent_workers(env, lookup_on, off):
    off.get(OFF_URL).mock(return_value=httpx.Response(404, json={"status": 0}))
    await by_barcode(env)
    sm = env.app.state.sessionmaker
    first = await claim(sm)
    second = await claim(sm)
    assert len(first) == 1 and second == []  # already 'running'


# --------------------------------------------------------------------------- EAN-Search


async def test_eansearch_disabled_without_token_and_enabled_with(env, lookup_on):
    r = await env.client.get("/api/admin/providers", headers=env.admin)
    ean = {p["id"]: p for p in r.json()["providers"]}["eansearch"]
    assert ean["enabled"] is False and ean["has_key"] is False
    r = await env.client.patch(
        "/api/admin/providers",
        json={
            "providers": [{"name": "eansearch", "enabled": True, "api_key": "sekret-token-1234"}]
        },
        headers=env.admin,
    )
    ean = {p["id"]: p for p in r.json()["providers"]}["eansearch"]
    assert ean["enabled"] and ean["has_key"] and "sekret" not in json.dumps(r.json())
    assert ean["api_key"].endswith("1234") and ean["key_source"] == "db"
    lookup_on.off_enabled = False
    with respx.mock() as m:
        route = m.get(url__regex=r"https://api\.ean-search\.org/api.*").mock(
            return_value=httpx.Response(
                200, json=[{"ean": CODE, "name": "Arla Letmælk 1 l", "issuingCountry": "DK"}]
            )
        )
        out = await by_barcode(env)
    assert route.called and out["product"]["name"] == "Arla Letmælk 1 l"
    assert out["product"]["status"] == "needs_review"  # name only -> low confidence
    assert out["product"]["package_unit"] == "l"
    assert out["source"] == "eansearch"


# --------------------------------------------------------------------------- photo / media


async def test_photo_upload_reencodes_and_strips_exif(env, lookup_on):
    p = await env.product("Foto")
    data = png_bytes((3000, 2000), exif=True)
    assert b"SecretCameraMaker" in data
    r = await env.client.post(
        f"/api/products/{p['id']}/photo",
        files={"file": ("x.jpg", data, "image/jpeg")},
        headers=env.member,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["image_url"].startswith("/api/media/") and "image" in body["locked_fields"]
    stored = Path(lookup_on.upload_dir) / body["image_url"].rsplit("/", 1)[1]
    raw = stored.read_bytes()
    assert b"SecretCameraMaker" not in raw
    with Image.open(stored) as im:
        assert im.format == "WEBP" and max(im.size) == 1600
        assert not im.getexif()
    served = await env.client.get(body["image_url"])
    assert served.status_code == 200 and served.headers["content-type"] == "image/webp"
    # replacing removes the old file
    r2 = await env.client.post(
        f"/api/products/{p['id']}/photo",
        files={"file": ("y.png", png_bytes(), "image/png")},
        headers=env.member,
    )
    assert r2.status_code == 200
    assert not stored.exists()


async def test_photo_rejects_garbage_and_oversize(env, lookup_on):
    p = await env.product("Foto")
    url = f"/api/products/{p['id']}/photo"
    r = await env.client.post(
        url,
        files={"file": ("a.jpg", b"<html>not an image</html>", "image/jpeg")},
        headers=env.member,
    )
    assert r.status_code == 422 and r.json()["code"] == "invalid_image"
    svg = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'
    r = await env.client.post(
        url, files={"file": ("a.svg", svg, "image/svg+xml")}, headers=env.member
    )
    assert r.status_code == 422
    big = b"\xff\xd8\xff" + b"0" * (8 * 1024 * 1024 + 10)
    r = await env.client.post(
        url, files={"file": ("big.jpg", big, "image/jpeg")}, headers=env.member
    )
    assert r.status_code == 413
    r = await env.client.post(
        f"/api/products/{uuid.uuid4()}/photo",
        files={"file": ("a.png", png_bytes(), "image/png")},
        headers=env.member,
    )
    assert r.status_code == 404


async def test_media_path_safety(env, lookup_on):
    for bad in ["..%2Fsecret", "x.webp", "../../etc/passwd", "A" * 32 + ".webp"]:
        r = await env.client.get(f"/api/media/{bad}")
        assert r.status_code == 404


async def test_image_download_only_from_open_facts(env, lookup_on):
    from pantrynanny.services.lookup.media import download_image

    assert await download_image("https://evil.example.com/a.png") is None
    assert await download_image("http://images.openfoodfacts.org/a.png") is None
    with respx.mock() as m:
        m.get("https://images.openfoodfacts.org/a.png").mock(
            return_value=httpx.Response(200, content=b"x", headers={"content-type": "text/html"})
        )
        m.get("https://images.openfoodfacts.org/b.png").mock(
            return_value=httpx.Response(
                200, content=b"x" * 10, headers={"content-type": "image/png"}
            )
        )
        assert await download_image("https://images.openfoodfacts.org/a.png") is None
        assert (
            await download_image("https://images.openfoodfacts.org/b.png") is None
        )  # not decodable


async def test_kiosk_new_endpoint_restrictions(env, lookup_on):
    r = await env.client.post("/api/devices/kiosk-codes", json={"name": "ipad"}, headers=env.admin)
    code = r.json()["code"]
    r = await env.client.post("/api/auth/kiosk", json={"code": code})
    assert r.status_code == 200, r.text
    cookies = {"pn_session": r.cookies["pn_session"]}
    p = await env.product("Kiosk-foto")
    kc = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=env.app), base_url="http://test", cookies=cookies
    )
    async with kc:
        h = {"X-PN-CSRF": "1"}
        ok = await kc.post(
            f"/api/products/{p['id']}/photo",
            files={"file": ("a.png", png_bytes(), "image/png")},
            headers=h,
        )
        assert ok.status_code == 200
        for method, path in [
            ("POST", f"/api/products/{p['id']}/refresh"),
            ("GET", "/api/export/products.csv"),
            ("GET", "/api/stats"),
            ("GET", "/api/admin/catalogue"),
            ("GET", "/api/admin/providers"),
            ("GET", "/api/ha/summary"),
        ]:
            r = await kc.request(method, path, headers=h)
            assert r.status_code == 403, (path, r.status_code)


async def test_time_budget_is_respected(env, lookup_on, off):
    async def slow(request):
        raise httpx.ReadTimeout("slow")

    off.get(OFF_URL).mock(side_effect=slow)
    t0 = time.monotonic()
    out = await by_barcode(env)
    assert out["status"] == "created_placeholder"
    assert time.monotonic() - t0 < 5
