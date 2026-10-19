# Product data sources

Research date: 2026-10-19. PantryNanny keeps its own permanent catalogue; external providers only
*seed* it. Everything fetched is stored locally (with source, attribution and confidence), so a
product stays available when a provider is down or changes its terms.

Lookup order: device cache -> PantryNanny catalogue (PostgreSQL) -> providers by priority ->
placeholder + background enrichment. Provider enable/priority/API keys are editable at
`/api/admin/providers`; defaults come from `PN_*` environment variables.

## Summary

| Source | Status | Why |
|---|---|---|
| Open Food Facts (OFF) | **Implemented, enabled** (priority 10) | Open API, ODbL data, explicit reuse terms |
| Open Beauty / Pet Food / Products Facts | Implemented, **disabled by default** (20-22) | Same software, API and licence as OFF; non-food coverage; off by default to keep scan latency low |
| EAN-Search.org | Implemented, **key-gated, disabled by default** (50) | Official paid REST API with token; enabled only when a token is set |
| GS1 Denmark (Verified by GS1 / GEPIR) | Not implemented | Company-level data, enterprise/contract access only |
| Salling Group developer APIs | Not implemented | No product-by-EAN API found |
| Retailer web shops (Netto, Foetex, Bilka, Coop, REMA 1000, Lidl ...) | Not implemented | No public API; scraping prohibited by project rules |

## Open Food Facts

* Docs: <https://openfoodfacts.github.io/openfoodfacts-server/api/>
* Endpoint used: `GET https://world.openfoodfacts.org/api/v2/product/{code}.json?fields=...`
  (v3 is recommended by OFF for new write integrations; v2 read is stable and what we need).
  We request a field subset only (name da/en, brands, quantity, categories_tags, image_front_url,
  ingredients_text(_da), allergens_tags, nutriments, countries_tags).
* **Rate limits** (published): 15 requests/min/IP for product reads, 10/min for search, 2/min for
  facet queries; abusers may be banned. We never use search. The API process allows 8 reads/min
  (`PN_OFF_RATE_PER_MIN`) and the worker 6/min (`PN_OFF_WORKER_RATE_PER_MIN`), each via an
  in-process token bucket, so the total stays under 15/min. Misses (7 days) and hits (30 days)
  are cached, errors back off exponentially (1 min up to 6 h).
* **User-Agent required**: `AppName/Version (contact)`; set `PN_OFF_USER_AGENT` with a real contact
  address (a placeholder is shipped). OFF asks integrators to also fill in their usage form.
* **Licence**: database under ODbL 1.0, individual contents under the Database Contents Licence,
  product *images* under CC BY-SA (may contain third-party copyright). Obligations: attribute
  ("Open Food Facts"), share-alike for derived databases, keep the licence info. We store
  `source_attribution = "Open Food Facts – ODbL (images CC BY-SA)"` on every imported product and
  only download images from `images|static.openfoodfacts.org` (re-encoded to WebP, EXIF stripped).
  **Redistribution note**: exporting the catalogue (`/api/export/products.*`) includes OFF-derived
  data with its attribution column; publishing such an export publicly would trigger ODbL
  share-alike.
* **Danish coverage**: good for branded FMCG (Arla, Lurpak, Carlsberg, Coop/Salling private label
  such as Änglamark, Coop 365, Netto, REMA 1000 own brands); weaker for fresh/in-store items.
  In-store weighed items (EAN-13 prefixes 20-29) are not in OFF at all; PantryNanny maps them
  to a local `instore:` code instead. Danish names are used when `product_name_da` exists.
* The bundled test fixture is a representative OFF v2 response for a Danish dairy product
  (barcode illustrative), not a live recording.

## Open Beauty Facts, Open Pet Food Facts, Open Products Facts

Sister projects (same API shape, ODbL/CC BY-SA) at `world.openbeautyfacts.org`,
`world.openpetfoodfacts.org`, `world.openproductsfacts.org`. Same rate-limit etiquette applies.
Implemented as subclasses of the OFF adapter, disabled by default; enable them in the admin UI
if household cleaning/cosmetics/pet products matter.

## EAN-Search.org

* <https://www.ean-search.org/ean-database-api.html> - REST API (JSON/XML), ~1.3 billion barcodes,
  token-based, paid tiers (trial 100 queries/month; paid up to 300 000/month).
* Adapter calls `GET https://api.ean-search.org/api?token=...&op=barcode-lookup&ean=...&format=json`
  (endpoint form taken from their public client libraries; verify against your plan's docs).
  Returns name/category/issuing country only: confidence is capped at 0.5, so products land in
  `needs_review`.
* **Terms caveat**: the exact rules on caching/storing results are in their terms of service,
  which I could not retrieve automatically. Because the adapter stores results in the catalogue,
  check the terms of your plan before enabling it. Never enabled without `PN_EANSEARCH_TOKEN`
  (or a key set via the admin API; keys are never returned unmasked).

## GS1 Denmark

* GEPIR was replaced by **Verified by GS1** (end 2023; REST API). It verifies a GTIN against the
  brand owner's registration (company, licence key), it does not provide consumer product
  names/images. Batch and API access is enterprise-level through the national GS1 office
  (<https://gs1.dk>); no self-service key. Not implemented. A future adapter could plug in if
  a household/organisation obtains a contract; GS1 also offers "Validoo"/product data pools to
  suppliers, not to consumers.

## Salling Group (Netto, Foetex, Bilka)

* Developer portal: <https://developer.sallinggroup.dev/> (formerly developer.sallinggroup.com).
  Public APIs cover stores (opening hours, addresses), food-waste offers and similar; I found no
  product catalogue lookup by EAN (the portal pages could not be read in detail, so this is
  "none found", not "confirmed absent"). Not implemented. Coop and REMA 1000 publish no public
  product API either.

## Other options considered

* Wikidata/Wikimedia Commons: barcodes are rare there. Not worth an adapter.
* Commercial UPC databases (UPCitemdb, Barcode Lookup, Go-UPC): US-centric, paid, restrictive
  caching terms. Can be added as key-gated adapters later (`services/lookup/providers.py`).
* Retailer web-shop scraping: explicitly out of scope (no authorisation, bot protections).

## Extending

Add a class in `backend/pantrynanny/services/lookup/providers.py` with `name`, `attribution`,
`license`, `enabled()`, `rate_per_min()` and `async fetch(code, timeout_s)` returning a
`ProviderResult`, then list it in `PROVIDER_CLASSES`. Caching, attempt log, rate limiting, admin
UI entry and locked-field protection come for free.
