"""Seed catalogue: importer, CLI flags, local provider precedence over HTTP providers."""

import gzip
import json

import httpx
import pytest
import respx
from sqlalchemy import func, select, text

from pantrynanny import cli
from pantrynanny.models import CatalogueSeed, LookupAttempt
from pantrynanny.services.lookup import refresh_product
from pantrynanny.services.seed import import_seed, read_meta, seed_stats
from pantrynanny.worker import run_once

from .test_lookup import CODE, OFF_JSON, OFF_URL, by_barcode, lookup_on, off  # noqa: F401

SEEDED = "05705830010018"  # GTIN-14 of CODE
OTHER = "05711953000110"


def write_seed(path, version="off-test-1", extra=()):
    meta = {
        "_meta": {
            "license": "ODbL 1.0 (database), DbCL 1.0 (contents)",
            "dataset_version": version,
            "count": 2 + len(extra),
        }
    }
    recs = [
        {
            "code": SEEDED,
            "name": "Seed Letmælk",
            "brand": "Arla",
            "package_size": 1,
            "package_unit": "l",
            "category_hint": "Mejeri",
            "allergens": ["mælk"],
            "countries": ["denmark"],
        },
        {"code": OTHER, "name": "Seed Rugbrød", "brand": None, "package_size": None},
        *extra,
    ]
    meta["_meta"]["count"] = len(recs)
    with gzip.open(path, "wt", encoding="utf-8") as f:
        f.write(json.dumps(meta) + "\n")
        for r in recs:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return path


@pytest.fixture
def seed_file(tmp_path):
    return write_seed(tmp_path / "seed.jsonl.gz")


async def test_import_idempotent_and_if_changed(app, seed_file, tmp_path):
    sm = app.state.sessionmaker
    async with sm() as s:
        assert await import_seed(s, seed_file) == ("imported", 2)
    async with sm() as s:
        assert await import_seed(s, seed_file) == ("imported", 2)  # upsert, no duplicates
        assert await s.scalar(select(func.count()).select_from(CatalogueSeed)) == 2
    async with sm() as s:
        assert await import_seed(s, seed_file, if_changed=True) == ("unchanged", 2)
    # new version replaces rows, drops those no longer present
    v2 = write_seed(tmp_path / "v2.jsonl.gz", "off-test-2")
    with gzip.open(v2, "rt") as f:
        lines = f.read().splitlines()
    meta = json.loads(lines[0])
    meta["_meta"]["count"] = 1
    with gzip.open(v2, "wt") as f:
        f.write(json.dumps(meta) + "\n" + lines[1] + "\n")
    async with sm() as s:
        assert await import_seed(s, v2, if_changed=True) == ("imported", 1)
        assert await s.scalar(select(func.count()).select_from(CatalogueSeed)) == 1
        stats = await seed_stats(s)
        assert stats == {"size": 1, "dataset_versions": ["off-test-2"]}
    assert read_meta(v2)["dataset_version"] == "off-test-2"


def test_cli_import_seed(app, seed_file, capsys):
    assert cli.main(["import-seed", "--file", str(seed_file)]) == 0
    assert "imported: 2 rows" in capsys.readouterr().out
    assert cli.main(["import-seed", "--file", str(seed_file), "--if-changed"]) == 0
    assert "unchanged" in capsys.readouterr().out
    assert cli.main(["import-seed", "--file", "/nonexistent.jsonl.gz"]) == 1


@pytest.fixture
async def seeded(app, seed_file):
    async with app.state.sessionmaker() as s:
        await import_seed(s, seed_file)


async def test_seed_hit_resolves_without_http(env, lookup_on, seeded):  # noqa: F811
    with respx.mock(assert_all_called=False) as m:
        route = m.get(OFF_URL).mock(return_value=httpx.Response(200, json=OFF_JSON))
        out = await by_barcode(env)
        assert route.call_count == 0 and len(m.calls) == 0
    assert out["source"] == "catalogue_seed"
    p = out["product"]
    assert p["name"] == "Seed Letmælk" and p["brand"] == "Arla"
    assert p["package_size"] == 1 and p["package_unit"] == "l"
    assert p["category_id"] == env.categories["Mejeri"]
    assert p["allergens"] == ["mælk"]
    assert p["status"] == "known" and p["lookup_confidence"] == 0.8
    assert p["source"] == "catalogue_seed"
    assert p["source_attribution"] == "Open Food Facts – ODbL"
    async with env.app.state.sessionmaker() as s:
        att = (await s.execute(select(LookupAttempt))).scalars().all()
        assert [(a.provider, a.status) for a in att] == [("catalogue_seed", "found")]


async def test_seed_miss_falls_through_to_off(env, lookup_on, seeded, off):  # noqa: F811
    async with env.app.state.sessionmaker() as s, s.begin():
        await s.execute(text("DELETE FROM catalogue_seed WHERE code = :c"), {"c": SEEDED})
    out = await by_barcode(env)
    assert out["source"] == "openfoodfacts" and out["product"]["name"] == "Arla Letmælk"
    assert off.route_off.call_count == 1


async def test_sync_op_for_seeded_code_creates_known_product(env, lookup_on, seeded):  # noqa: F811
    with respx.mock(assert_all_called=False) as m:
        await env.ops(env.op("add", barcode=CODE, symbology="ean_13"))
        assert len(m.calls) == 0
        await run_once(env.app.state.sessionmaker)
        assert len(m.calls) == 0
    r = await env.client.get("/api/products", headers=env.member)
    prods = [p for p in r.json() if p["name"] == "Seed Letmælk"]
    assert len(prods) == 1
    assert prods[0]["status"] == "known" and prods[0]["source"] == "catalogue_seed"


async def test_sync_op_result_carries_seeded_product_without_worker(env, seeded):
    # Android posts scans to /sync/ops (no by-barcode call): the op result itself must name the
    # product, without waiting for the enrichment worker or any network lookup.
    with respx.mock(assert_all_called=False) as m:
        [res] = await env.ops(env.op("add", barcode=CODE, symbology="ean_13"))
        assert len(m.calls) == 0
    assert res["status"] == "applied"
    assert res["product"]["name"] == "Seed Letmælk"
    assert res["product"]["status"] == "known" and res["product"]["source"] == "catalogue_seed"


async def test_sync_op_respects_disabled_seed_provider(env, seeded):
    r = await env.client.patch(
        "/api/admin/providers",
        json={"providers": [{"name": "catalogue_seed", "enabled": False}]},
        headers=env.admin,
    )
    assert r.status_code == 200, r.text
    [res] = await env.ops(env.op("add", barcode=CODE, symbology="ean_13"))
    assert res["product"]["status"] == "unknown"


async def test_enrichment_from_seed_respects_locked_fields(env, lookup_on, seeded):  # noqa: F811
    p = await env.product("Min mælk", barcodes=[CODE])
    r = await env.client.patch(
        f"/api/products/{p['id']}",
        json={"name": "Min mælk 2"},
        headers={**env.member, "If-Match": str(p["version"])},
    )
    assert r.status_code == 200, r.text
    out = await refresh_product(env.app.state.sessionmaker, env.household_id, p["id"])
    assert out.provider == "catalogue_seed"
    r = await env.client.get(f"/api/products/{p['id']}", headers=env.member)
    got = r.json()
    assert got["name"] == "Min mælk 2" and got["brand"] == "Arla"


async def test_catalogue_stats_show_seed_size(env, seeded):  # noqa: F811
    r = await env.client.get("/api/admin/catalogue", headers=env.admin)
    assert r.status_code == 200, r.text
    assert r.json()["seed_catalogue"]["size"] == 2
