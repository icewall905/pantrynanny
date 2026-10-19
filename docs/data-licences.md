# Data licences and attribution

PantryNanny's own code is licensed separately (see the repository licence). This page covers the
**data** that ships with or is fetched by PantryNanny.

## Open Food Facts seed catalogue

* File: `backend/pantrynanny/data/seed/off_dk.jsonl.gz` (product *metadata* only: barcode, name,
  brand, package size, category hint, allergens, countries). **No images** are included.
* Source: Open Food Facts (<https://world.openfoodfacts.org>), official Parquet export published
  as the Hugging Face dataset `openfoodfacts/product-database`. See
  `backend/pantrynanny/data/seed/README.md` for the exact dataset version, build date and counts.
* Licence: the database is available under the **Open Database Licence (ODbL) 1.0**
  (<https://opendatacommons.org/licenses/odbl/1-0/>); individual contents are under the
  **Database Contents Licence (DbCL) 1.0** (<https://opendatacommons.org/licenses/dbcl/1-0/>).
  Product images (not included) are CC BY-SA.
* Attribution: "Contains information from Open Food Facts (c) Open Food Facts contributors,
  available under the Open Database Licence." PantryNanny stores
  `Open Food Facts – ODbL` as the `source_attribution` of every product created from the seed.
* Share-alike: the seed file is a derived database. It is redistributed here under the ODbL 1.0.
  If you publish an adapted version (or an export of your catalogue containing seed-derived
  rows), keep the attribution and offer it under the same licence.
* Rebuild: `uv run scripts/build_seed_catalogue.py` (queries the remote Parquet file with DuckDB;
  no full download, no scraping, no API calls).

## Live lookups

Products fetched at runtime from the Open Food Facts API (and its sister projects) carry the same
ODbL/DbCL terms; images are CC BY-SA. See `docs/product-data-sources.md`.
