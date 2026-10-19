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
from pantrynanny.models import EnrichmentQueue, LookupAttempt, LookupCache, Product
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
        off_sisters_enabled=False,  # these tests count Open Food Facts calls only
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


def api_calls(m) -> int:
    return sum(1 for c in m.calls if "/api/v2/" in str(c.request.url))


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
    off.get("https://world.openfoodfacts.org/api/v2/product/5705830020017.json").mock(
        return_value=httpx.Response(404, json={"status": 0})
    )
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
    stored = Path(env.app.state.settings.upload_dir) / body["image_url"].rsplit("/", 1)[1]
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


# --------------------------------------------------------------------------- review fixes


def test_name_language_preference():
    from pantrynanny.services.lookup.providers import OpenFoodFactsProvider

    prov = OpenFoodFactsProvider(Settings(database_url=TEST_DB_URL))
    base = {"brands": "Lurpak", "quantity": "250 g"}
    polish = prov.map_product(
        {**base, "product_name": "Duńskie masło lekko solone", "product_name_en": "Danish butter"}
    )
    assert polish.name == "Danish butter"
    da = prov.map_product({**base, "product_name": "Masło", "product_name_da": "Smør"})
    assert da.name == "Smør"
    only = prov.map_product({**base, "product_name": "Masło"})
    assert only.name == "Masło"
    ing = prov.map_product(
        {**base, "product_name": "x", "ingredients_text": "Mleko", "ingredients_text_en": "Milk"}
    )
    assert ing.ingredients == "Milk"
    from pantrynanny.services.lookup.providers import OFF_FIELDS

    assert {"product_name_en", "generic_name_en", "ingredients_text_en"} <= set(
        OFF_FIELDS.split(",")
    )


def _big_png(w, h) -> bytes:
    buf = io.BytesIO()
    Image.new("L", (w, h), 7).save(buf, "PNG")
    return buf.getvalue()


async def test_photo_rejects_huge_resolution_before_decoding(env, lookup_on):
    p = await env.product("Stor")
    big = _big_png(6000, 5000)  # 30 MP, tiny file
    assert len(big) < 1_000_000
    r = await env.client.post(
        f"/api/products/{p['id']}/photo",
        files={"file": ("big.png", big, "image/png")},
        headers=env.member,
    )
    assert r.status_code == 422 and r.json()["code"] == "invalid_image"
    ok = await env.client.post(
        f"/api/products/{p['id']}/photo",
        files={"file": ("ok.png", _big_png(4000, 3000), "image/png")},  # 12 MP is fine
        headers=env.member,
    )
    assert ok.status_code == 200


async def test_rotated_jpeg_is_still_oriented(env, lookup_on):
    img = Image.new("RGB", (300, 100), (10, 200, 10))
    ex = Image.Exif()
    ex[0x0112] = 6  # rotate 90 CW when displayed
    buf = io.BytesIO()
    img.save(buf, "JPEG", exif=ex.tobytes())
    from pantrynanny.services.lookup.media import reencode_webp

    out = Image.open(io.BytesIO(reencode_webp(buf.getvalue())))
    assert out.size == (100, 300)


async def test_token_bucket_wait_interrupted_by_stop():
    import asyncio

    b = TokenBucket(6, burst=1)
    assert await b.acquire(0)
    stop = asyncio.Event()
    asyncio.get_running_loop().call_later(0.05, stop.set)
    t0 = time.monotonic()
    assert not await b.acquire(30, stop)  # would wait ~10 s
    assert time.monotonic() - t0 < 2


async def test_worker_stop_releases_unprocessed_items(env, lookup_on, off):
    import asyncio

    off.get(OFF_URL).mock(return_value=httpx.Response(404, json={"status": 0}))
    await by_barcode(env)
    stop = asyncio.Event()
    stop.set()
    sm = env.app.state.sessionmaker
    assert await run_once(sm, stop=stop) == 1
    async with sm() as s:
        q = (await s.execute(select(EnrichmentQueue))).scalar_one()
        assert q.status == "pending" and q.attempts == 0


async def test_worker_marks_items_of_deleted_products_failed(env, lookup_on, off):
    off.get(OFF_URL).mock(return_value=httpx.Response(404, json={"status": 0}))
    out = await by_barcode(env)
    sm = env.app.state.sessionmaker
    async with sm() as s, s.begin():
        await s.execute(update(Product).values(deleted_at=datetime.now(UTC)))
    n_calls = off.calls.call_count
    await run_once(sm)
    async with sm() as s:
        q = (await s.execute(select(EnrichmentQueue))).scalar_one()
        assert q.status == "failed" and q.last_error == "product gone"
    assert off.calls.call_count == n_calls and out["product"]["status"] == "unknown"


async def test_failed_placeholders_are_retried_weekly(env, lookup_on, off):
    from pantrynanny.worker import maintenance

    off.get(OFF_URL).mock(return_value=httpx.Response(404, json={"status": 0}))
    await by_barcode(env)
    sm = env.app.state.sessionmaker
    async with sm() as s, s.begin():
        await s.execute(
            update(EnrichmentQueue).values(
                status="failed",
                attempts=6,
                last_error="not found by any provider",
                updated_at=datetime.now(UTC) - timedelta(days=8),
            )
        )
    await maintenance(sm)
    async with sm() as s:
        q = (await s.execute(select(EnrichmentQueue))).scalar_one()
        assert q.status == "pending" and q.attempts == 5


async def test_refresh_stale_includes_products_whose_refresh_errored(env, lookup_on, off):
    from pantrynanny.worker import refresh_stale

    out = await by_barcode(env)
    sm = env.app.state.sessionmaker
    off.get(OFF_URL).mock(return_value=httpx.Response(200, json=OFF_JSON))
    async with sm() as s, s.begin():
        await s.execute(
            update(LookupCache).values(
                status="error", retry_after=datetime.now(UTC) - timedelta(minutes=1)
            )
        )
    calls = api_calls(off)
    assert await refresh_stale(sm) == 1
    assert api_calls(off) == calls + 1 and out["product"]["status"] == "known"


async def test_forced_refresh_honours_429_retry_after(env, lookup_on, off):
    out = await by_barcode(env)
    pid = out["product"]["id"]
    off.get(OFF_URL).mock(return_value=httpx.Response(429, headers={"Retry-After": "120"}))
    r = await env.client.post(f"/api/products/{pid}/refresh", headers=env.member)
    assert r.status_code == 200
    n = off.calls.call_count
    r = await env.client.post(f"/api/products/{pid}/refresh", headers=env.member)
    assert r.status_code == 200
    assert off.calls.call_count == n  # blocked by the cached 429 backoff
    async with env.app.state.sessionmaker() as s:
        c = (await s.execute(select(LookupCache))).scalar_one()
        assert c.retry_after > datetime.now(UTC) + timedelta(seconds=100)


async def test_sister_projects_are_asked_after_off_miss(env, lookup_on):
    # Default config: Open Food Facts misses, a sister project (here Open Products Facts) knows it.
    runtime.set_settings(lookup_on.model_copy(update={"off_sisters_enabled": True}))
    sister = {
        "status": 1,
        "product": {"code": CODE, "product_name": "Opvaskemiddel", "brands": "Neutral"},
    }
    with respx.mock(assert_all_called=False) as m:
        m.get(OFF_URL).mock(return_value=httpx.Response(404, json={"status": 0}))
        for host in ("openbeautyfacts", "openpetfoodfacts"):
            m.get(f"https://world.{host}.org/api/v2/product/{CODE}.json").mock(
                return_value=httpx.Response(404, json={"status": 0})
            )
        opf = m.get(f"https://world.openproductsfacts.org/api/v2/product/{CODE}.json").mock(
            return_value=httpx.Response(200, json=sister)
        )
        out = await by_barcode(env)
    assert opf.call_count == 1
    assert out["source"] == "openproductsfacts" and out["product"]["name"] == "Opvaskemiddel"
