# Seed catalogue (Open Food Facts, Denmark)

`off_dk.jsonl.gz`: first line `{"_meta": ...}`, then one JSON product per line (metadata only,
**no images**): `code` (GTIN-14), `name`, `brand`, `package_size`, `package_unit`, `category_hint`,
`allergens`, `countries`, `updated` (OFF `last_modified_t`).

* Source: Open Food Facts official Parquet export, Hugging Face dataset
  `openfoodfacts/product-database`, file `food.parquet`
  (<https://huggingface.co/datasets/openfoodfacts/product-database/resolve/main/food.parquet>).
* Dataset version: `off-2026-10-19-79fc2d7d1e5b` (HF commit `79fc2d7d1e5b...`); built 2026-10-19.
* Filter: `countries_tags` contains `en:denmark`, not obsolete, valid GTIN check digit, non-empty
  name (Danish, then English, then main-language name), in-store codes (EAN prefix 2x) excluded.
* Counts: 22,687 source rows, 19,814 products kept (1,593 without name, 1,280 invalid or in-store
  codes dropped), 0.55 MB gzipped.
* Licence: ODbL 1.0 (database), DbCL 1.0 (contents). Share-alike applies to this derived database.
  Attribution: "Open Food Facts – ODbL" (stored as `source_attribution` on products created from
  the seed). Details: `docs/data-licences.md`.

## Rebuild

```sh
uv run scripts/build_seed_catalogue.py                      # remote query (slow, can take an hour)
# faster: download once (~8 GB), build locally, delete the file afterwards
curl -L -C - -o /tmp/food.parquet \
  https://huggingface.co/datasets/openfoodfacts/product-database/resolve/main/food.parquet
uv run scripts/build_seed_catalogue.py --source /tmp/food.parquet
```

Import into the database (idempotent upsert; `install.sh` runs it with `--if-changed`):
`pantrynanny-admin import-seed [--file PATH] [--if-changed]`.
