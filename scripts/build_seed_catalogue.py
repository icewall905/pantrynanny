#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# dependencies = ["duckdb>=1.1"]
# ///
"""Build the PantryNanny seed catalogue from the Open Food Facts Parquet export.

Reads the official OFF export (Hugging Face dataset ``openfoodfacts/product-database``) remotely
with DuckDB/httpfs: only the needed columns and row groups are fetched (no full download, no
API calls, no scraping). Keeps products marked as sold in Denmark, metadata only (no images).

Data: (c) Open Food Facts contributors, ODbL 1.0 (database) / DbCL 1.0 (contents).

Usage:
  uv run scripts/build_seed_catalogue.py                      # query the remote file (slow)
  curl -L -C - -o /tmp/food.parquet <PARQUET_URL>             # or download once (~8 GB) ...
  uv run scripts/build_seed_catalogue.py --source /tmp/food.parquet   # ... and build locally
Options: [--out PATH] [--country en:denmark ...]
"""

import argparse
import gzip
import importlib.util
import json
import sys
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parent.parent
PKG = ROOT / "backend" / "pantrynanny"
PARQUET_URL = (
    "https://huggingface.co/datasets/openfoodfacts/product-database/resolve/main/food.parquet"
)
DEFAULT_OUT = PKG / "data" / "seed" / "off_dk.jsonl.gz"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


# pure modules, loaded by path so the script needs no project dependencies
barcodes = _load("pn_barcodes", PKG / "services" / "barcodes.py")
parsing = _load("pn_parsing", PKG / "services" / "lookup" / "parsing.py")

QUERY = """
SELECT code, product_name, brands, quantity, categories_tags, allergens_tags,
       countries_tags, last_modified_t
FROM read_parquet(?)
WHERE list_has_any(countries_tags, ?) AND code IS NOT NULL AND coalesce(obsolete, false) = false
"""


def pick_name(names) -> str | None:
    """Danish, then English, then the product's main language (same rule as the OFF provider)."""
    by_lang = {n["lang"]: (n["text"] or "").strip() for n in names or []}
    for lang in ("da", "en", "main"):
        if by_lang.get(lang):
            return by_lang[lang][:200]
    return None


def dataset_info() -> tuple[str, str | None]:
    req = urllib.request.Request(PARQUET_URL, method="HEAD")
    with urllib.request.urlopen(req, timeout=30) as r:  # noqa: S310 - fixed https URL
        commit = r.headers.get("x-repo-commit") or r.headers.get("etag", "").strip('"')
        return commit, r.headers.get("last-modified")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--source", default=PARQUET_URL, help="Parquet URL or local file path")
    ap.add_argument("--country", action="append", default=None, help="countries_tags value")
    args = ap.parse_args()
    countries = args.country or ["en:denmark"]

    commit, last_mod = dataset_info()  # version of the published dataset (HEAD request only)
    con = duckdb.connect()
    con.execute("SET enable_progress_bar=false")
    con.execute("INSTALL httpfs; LOAD httpfs")
    rows = con.execute(QUERY, [args.source, countries]).fetchall()

    products: dict[str, dict] = {}
    skipped = {"no_name": 0, "bad_code": 0, "duplicate": 0}
    for code, names, brands, quantity, cats, allergens, ctry, mod_t in rows:
        name = pick_name(names)
        if not name:
            skipped["no_name"] += 1
            continue
        try:
            n = barcodes.normalize(code)
        except ValueError:
            skipped["bad_code"] += 1
            continue
        # only real GTINs: in-store (prefix 2x) and local codes are not shared identifiers
        if not n.valid or n.code.startswith("instore:"):
            skipped["bad_code"] += 1
            continue
        brand = (brands or "").split(",")[0].strip() or None
        size, unit, _ = parsing.parse_quantity(quantity)
        rec = {
            "code": n.code,
            "name": name,
            "brand": brand[:200] if brand else None,
            "package_size": size,
            "package_unit": unit,
            "category_hint": parsing.map_category(cats),
            "allergens": parsing.allergen_names(allergens),
            "countries": [t.split(":", 1)[-1] for t in (ctry or [])],
            "updated": mod_t,
        }
        old = products.get(n.code)
        if old is not None:
            skipped["duplicate"] += 1
            if (old["updated"] or 0) >= (mod_t or 0):
                continue
        products[n.code] = rec

    built = datetime.now(UTC).strftime("%Y-%m-%d")
    meta = {
        "_meta": {
            "source": "Open Food Facts",
            "url": PARQUET_URL,
            "license": "ODbL 1.0 (database), DbCL 1.0 (contents)",
            "attribution": "Open Food Facts – ODbL",
            "dataset_version": f"off-{built}-{commit[:12]}",
            "dataset_commit": commit,
            "dataset_last_modified": last_mod,
            "built": built,
            "countries_filter": countries,
            "count": len(products),
        }
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with gzip.GzipFile(args.out, "wb", compresslevel=9, mtime=0) as gz:
        gz.write((json.dumps(meta, ensure_ascii=False) + "\n").encode())
        for rec in sorted(products.values(), key=lambda r: r["code"]):
            line = json.dumps(rec, ensure_ascii=False, separators=(",", ":"))
            gz.write((line + "\n").encode())
    print(f"source rows: {len(rows)}  kept: {len(products)}  skipped: {skipped}")
    mb = args.out.stat().st_size / 1e6
    print(f"wrote {args.out} ({mb:.2f} MB), version {meta['_meta']['dataset_version']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
