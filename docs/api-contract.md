# PantryNanny API contract (v1)

This document is the shared contract between the backend, the web/PWA client and the
Android client. If an implementation needs to deviate, update this file in the same commit.

All endpoints live under `/api`. JSON bodies, UTF-8. Timestamps are ISO-8601 with timezone
(UTC from the server). IDs are UUIDs (v4 server-generated, or client-generated where stated).
Quantities are decimal numbers serialised as JSON numbers (server stores `NUMERIC(12,3)`).

## 1. Authentication

Two token kinds, both opaque random strings (32 bytes, url-safe base64), stored server-side
**hashed (SHA-256)** in `sessions`:

* **Browser session** – `POST /api/auth/login {username, password, remember: bool}` sets an
  `HttpOnly; SameSite=Lax; Path=/` cookie `pn_session` (`Secure` when the request is HTTPS,
  including `X-Forwarded-Proto: https` from a trusted proxy). `remember=true` → 180 days sliding,
  else 12 h. Response body: `Me` (below). Cookie-authenticated **unsafe** requests (POST/PUT/
  PATCH/DELETE) must carry header `X-PN-CSRF: 1` (custom header ⇒ CORS-preflighted ⇒ CSRF-safe).
* **Device token** – for Android and kiosk iPad. `Authorization: Bearer <token>`. Obtained via
  `POST /api/auth/token {username, password, device_name, platform}` → `{token, me}` (role of
  the user; 365 days sliding), or via kiosk pairing (below). Bearer requests do not need CSRF
  header.
* `POST /api/auth/logout` revokes current session/token. `GET /api/auth/me` → `Me`.
* **Kiosk pairing**: an admin calls `POST /api/devices/kiosk-codes {name}` → `{code, expires_at}`
  (8-char code, valid 15 min, single use). The iPad opens `/scan`, enters the code →
  `POST /api/auth/kiosk {code}` → sets the `pn_session` cookie (365 days) bound to a
  **kiosk** principal. Kiosk scope: read products/inventory/locations/categories/shopping,
  `POST /api/sync/ops`, `GET /api/sync/*`, `GET /api/products/by-barcode/*`,
  `POST /api/products/{id}/photo` (unknown-product photo), nothing else (403).
* `GET /api/devices` / `DELETE /api/devices/{id}` (admin): list/revoke sessions & devices.

`Me = {user: {id, username, display_name, role}, household: {id, name}, kiosk: bool, settings: HouseholdSettings}`

Roles: `owner` > `admin` > `member`; `kiosk` principal is a session flag, not a user role.
Members can do all inventory/shopping/product edits; admins additionally manage users,
devices, locations/categories deletion, providers and settings.

Errors: `{"detail": "message", "code": "machine_code"}` with proper HTTP status. 401 when
unauthenticated, 403 when forbidden, 404 when not found **or belongs to another household**,
409 on version conflict, 422 validation.

Login is rate limited (10 attempts / 5 min per IP+username → 429).

## 2. Core resources

```
Location   {id, name, icon, sort_order, is_default, deleted_at|null}
Category   {id, name, icon, color, sort_order, deleted_at|null}
Product    {id, version, name, brand, category_id|null, default_location_id|null,
            image_url|null,            # served via /api/media/... or null
            package_size|null, package_unit|null,   # contents of ONE package, e.g. 1, "l"
            stock_unit,                # unit of inventory counting; default "pcs"
            min_stock|null,            # threshold in stock_unit
            ingredients|null, allergens: [str], nutrition: {..}|null, description|null,
            countries: [str], barcodes: [Barcode], aliases: [str],
            status: "known"|"unknown"|"needs_review",
            source: "user"|"openfoodfacts"|...|"placeholder", source_attribution|null,
            lookup_confidence: 0..1|null, locked_fields: [str],
            created_at, updated_at, deleted_at|null}
Barcode    {code (normalised GTIN-14 or "local:<raw>"), raw, symbology|null}
StockBatch {id, product_id, location_id, quantity, expires_at (date)|null, opened_at|null,
            created_at, updated_at}
InventoryItem {product: Product, total_quantity, batches: [StockBatch],
               next_expiry|null, low_stock: bool}
Transaction {id, client_op_id, product_id, batch_id|null, type, quantity_delta,
             location_id|null, to_location_id|null, reason|null, undoes_id|null,
             undone: bool, user_id|null, device_name|null, occurred_at, created_at}
ShoppingItem {id, version, product_id|null, name, quantity, unit|null, category_id|null,
              note|null, checked: bool, checked_at|null, source: "manual"|"low_stock"|"inventory",
              created_at, updated_at}
HouseholdSettings {locale: "da"|"en", allow_negative_stock: false, expiry_soon_days: 3,
                   auto_shopping_low_stock: true, remove_mode_timeout_min: 10,
                   scan_rearm_ms: 600}
```

Units (closed set): `pcs, pkg, g, kg, ml, cl, dl, l`.
Transaction types: `add, remove, adjust, move, undo`.

### Endpoints

| Method & path | Notes |
|---|---|
| `GET /api/health` | unauthenticated: `{status:"ok", db:"ok", version, ai:"ok"\|"down"\|"disabled"}`; 503 if DB down |
| `GET/POST /api/locations`, `PATCH/DELETE /api/locations/{id}` | delete = soft |
| `GET/POST /api/categories`, `PATCH/DELETE /api/categories/{id}` | delete = soft |
| `GET /api/products?q=&status=&category_id=&limit=&offset=` | forgiving search (name, brand, alias, category name, barcode, unaccented + trigram) |
| `POST /api/products` | manual creation (`barcodes: [raw]` optional) |
| `GET /api/products/{id}` | |
| `PATCH /api/products/{id}` | header `If-Match: <version>` required; 409 returns current Product. Every field edited here is added to `locked_fields` (provider refreshes never overwrite). |
| `DELETE /api/products/{id}` | soft delete |
| `POST /api/products/{id}/barcodes {raw}` / `DELETE /api/products/{id}/barcodes/{code}` | |
| `POST /api/products/{id}/photo` | multipart `file` (jpeg/png/webp ≤ 8 MB, re-encoded server-side to webp, EXIF stripped) |
| `POST /api/products/{id}/refresh` | re-run external lookup (respects locked_fields) |
| `POST /api/products/{id}/merge {into_id}` | duplicate resolution: moves barcodes, batches, txns |
| `GET /api/products/by-barcode/{raw}?lookup=true&symbology=` | **read-only w.r.t. stock**. Returns `{status:"found"\|"created_placeholder"\|"not_found", product\|null, source}`. `lookup=true` (default) may call external providers synchronously with a 3 s budget; on miss/timeout it creates an `unknown` placeholder and enqueues background enrichment. `lookup=false` only checks the DB. |
| `GET /api/inventory?location_id=&category_id=&q=&sort=name\|quantity\|expiry\|updated&include_empty=false` | `[InventoryItem]` |
| `GET /api/inventory/{product_id}` | InventoryItem + last 50 transactions |
| `PATCH /api/batches/{id}` | `{expires_at, opened_at}` (metadata only, no stock change) |
| `GET /api/transactions?product_id=&limit=&before=` | history |
| `POST /api/transactions/{id}/undo {client_op_id}` | creates compensating `undo` txn; idempotent on client_op_id; undoing twice → 409 |
| `GET /api/dashboard` | `{totals:{products_in_stock, items}, low_stock:[InventoryItem], expiring_soon:[...], expired:[...], recently_added:[Transaction+product], recently_consumed:[...], unknown_count, shopping_open_count, by_location:[{location, item_count}]}` |
| `GET/POST /api/shopping`, `PATCH/DELETE /api/shopping/{id}` | POST with same open `product_id` merges quantity (no duplicates) |
| `POST /api/shopping/clear-checked` | |
| `GET /api/shopping/suggestions` | low-stock products not already on list |
| `GET /api/export/{inventory\|shopping\|expiring\|products\|transactions}.{csv\|json}` | CSV: UTF-8 **with BOM**, `;` separator (Danish Excel), RFC-4180 quoting |
| `GET /api/stats?days=30` | top added/consumed, daily add/remove counts, per-product quantity series |
| `GET/PATCH /api/settings` | household settings (admin for PATCH) |
| `GET/POST /api/users`, `PATCH/DELETE /api/users/{id}` | admin |
| `GET /api/admin/catalogue` | counts by status/source, failed lookups, duplicate candidates, lookup stats (hit rate) |
| `GET /api/admin/lookups?status=` | lookup attempt log |
| `GET/PATCH /api/admin/providers` | enable/disable providers, keys stored server-side, never returned (masked) |
| `GET /api/media/{path}` | served by nginx in production from uploads dir |
| `GET /api/ha/summary` | read-only Home Assistant-friendly summary (bearer token) |
| `POST /api/ai/chat`, `POST /api/ai/recipes`, `GET /api/ai/status`, `POST /api/ai/identify-photo` | see §5 |

## 3. Synchronisation (offline-first)

### 3.1 Client operation

Clients never send absolute quantities for scans. They queue **operations** locally and
upload them:

```json
POST /api/sync/ops
{
  "device_id": "uuid (stable per install)",
  "ops": [
    {
      "client_op_id": "uuid v4 generated on the device at scan time",
      "type": "add" | "remove" | "adjust" | "move" | "undo",
      "barcode": "5701234567892",          // raw scanned value, OR
      "symbology": "ean_13|null",          // decoder format hint (see §6)
      "product_id": "uuid",                // when known locally
      "quantity": 1,                       // positive magnitude; adjust: signed delta
      "location_id": "uuid|null",          // null → product default → household default
      "to_location_id": "uuid|null",       // move only
      "expires_at": "2026-11-01|null",     // add only, optional
      "undoes_client_op_id": "uuid|null",  // undo only
      "occurred_at": "2026-10-19T12:00:00Z"
    }
  ]
}
```

Response (always 200 if the batch was parsed; per-op status):

```json
{
  "results": [
    {"client_op_id": "...", "status": "applied" | "duplicate" | "rejected",
     "error": null | "message", "transaction_id": "uuid|null",
     "product": Product, "total_quantity": 3}
  ],
  "server_time": "..."
}
```

Rules:

* Each op is applied in its own DB transaction, serialised per product with
  `SELECT ... FOR UPDATE` on the product row. `(household_id, client_op_id)` is UNIQUE in
  `stock_transactions`; a replay returns `duplicate` with the original result → **exactly
  once**.
* Unknown barcode in an `add`/`remove` op: server resolves via DB; if not found it creates an
  `unknown` placeholder product immediately (no external call inside the request) and enqueues
  enrichment. The op is still applied.
* `remove` consumes batches FIFO by `expires_at` (nulls last) at the target location, then
  others. If stock would go negative and `allow_negative_stock=false`, the removal is clamped
  to available stock; the txn records the actual delta and `status` is `applied` with
  `error:"clamped"`.
* `undo` references the original op's `client_op_id`; idempotent like any op.
* Batch limit 500 ops. Ops are applied in array order.

### 3.2 Pulling state

`GET /api/sync/snapshot` → full household catalogue + stock for cold start:
`{cursor, products:[Product], inventory:[{product_id, total_quantity, batches}], locations, categories, settings}`

`GET /api/sync/changes?since=<cursor>` → `{cursor, products:[...changed incl. deleted], inventory:[...changed product totals], locations, categories, full_resync_required: bool}`.
Cursor = opaque string; clients store and echo it verbatim and must never parse it. The server
issues `x1.<database oid>.<oldest in-progress transaction id>`: rows are stamped with the writing
transaction id, so a pull returns every row written by a transaction that was still open at the
previous pull (never skipping a slow writer; rows may repeat, so upsert). A cursor that does not
start with `x1.` (legacy), names another database (restore / re-create), or lies in the future
yields `full_resync_required: true` with empty lists: discard local catalogue state and call
`/sync/snapshot`.

### 3.3 Conflict strategy

* Stock: additive operations only; never last-write-wins on quantities. Server total is
  authoritative; clients show `server_total + sum(pending local deltas)`.
* Product metadata: optimistic concurrency via `version` / `If-Match`; on 409 the client shows
  the server copy and lets the user re-apply. User edits populate `locked_fields`; provider
  refreshes only fill fields not in `locked_fields`.
* Shopping items: `version` + If-Match as for products; check/uncheck is last-write-wins
  (harmless).

## 4. Scanner duplicate-suppression spec (PWA + Android must both implement)

Per decoded barcode value keep `lastSeenAt`. On each decoded frame result `code` at time `t`:

```
entry = tracked[code]
if entry is None or (t - entry.lastSeenAt) >= REARM_MS:   # absent long enough → new item
    fire(code)                                            # count it
tracked[code].lastSeenAt = t
```

* `REARM_MS` default **600 ms** (household setting `scan_rearm_ms`, clamp 250–3000).
* Frames without detections simply don't update `lastSeenAt`, so a barcode held in view
  (continuously decoded) never re-fires; removing it for ≥ REARM_MS and showing it again fires.
* Different codes are independent → no global cooldown.
* Misread confirmation (Android; runs before the dedupe above): partial left-half decodes can be
  checksum-valid yet wrong, so a code fires only after the identical raw value was decoded in
  ≥ 2 frames within 600 ms (3 if the first sighting was small / near the frame edge) and no
  competing code from an overlapping region has as many reads. Codes touching the frame edge
  are ignored; per frame only the most central code is considered. Checksum validity is
  irrelevant. Default formats: EAN-13/8, UPC-A/E (CODE_128/ITF behind a setting).
* Switching Add/Remove mode clears `tracked` (so the item in view can be counted in the new
  mode only after it is re-presented — avoids an accidental double operation).
* Entries older than 10 s are garbage-collected.

**Never the same item twice in succession (owner rule, applies on top of the frame-level
dedupe above; PWA and Android).** Remember the *last counted scan* `(normalised code, mode,
scan session, op id)`. A fired scan whose normalised code, mode and session equal the last
counted one is **not counted**: no op is created. The UI shows a neutral cue (soft tone, no
success beep) and the hint "Already counted – tap + for more" on that item's card, with the
+1/+2/+5 buttons highlighted; the buttons create their own ops as before. Hand-scanner
(keyboard wedge) input follows the same rule. The memory is cleared when a *different* code is
counted, the mode is switched, the scan session ends or a new one starts, or the last counted
scan is undone (re-scanning then counts again). So A, A = 1; A, B, A = 3; A, undo, A = 2.

## 5. AI assistant

* `GET /api/ai/status` → `{enabled, reachable, model|null}`.
* `POST /api/ai/chat {messages:[{role:"user"|"assistant", content}], locale}` →
  `{reply, tool_calls:[{name, arguments}], model}`. Server runs the tool loop (max 5 rounds)
  with read-only tools: `search_inventory(query)`, `list_inventory_by_location(location)`,
  `list_expiring_products(days)`, `get_product_details(product_id|name)`,
  `get_low_stock_items()`, `get_shopping_list()`. Tool results are wrapped as untrusted data.
* `POST /api/ai/recipes {prompt|null, count}` →
  `{recipes:[{title, description, have:[str], missing:[str], substitutions:[str], steps:[str]}]}`
* `POST /api/ai/identify-photo` multipart `file` → `{name, brand, package_size, package_unit, category_guess, confidence}` suggestions only (vision model).
* All AI endpoints return 503 `{code:"ai_unavailable"}` when disabled/unreachable.

## 6. Barcode normalisation

`normalize(raw, symbology_hint=None) -> {code, symbology, valid}`. Clients pass the decoder's
format as `symbology` (op field / `?symbology=` query param) using the names
`ean_13, ean_8, upc_a, upc_e, code_128, code_39, itf, qr, data_matrix, other`.

* Strip whitespace; digits only for GTIN family.
* 8 digits with hint `upc_e` (or 6 digits) → expand UPC-E to UPC-A; otherwise 8 digits = EAN-8.
* EAN-8, UPC-A (12), EAN-13, GTIN-14 with valid mod-10 check → left-pad to 14 digits → `code`.
* EAN-13 with prefix `20–29` (in-store / variable weight, used by Danish supermarkets for
  meat/cheese) → code = `"instore:" + first 7 digits` (item reference, ignoring price/weight
  part) and `valid=true`, so repeated purchases map to one product.
* Anything else (QR, Code128, invalid checksum) → `code = "local:" + raw`, `valid=false`.
* Original raw value is always stored in `Barcode.raw`.

## 7. Implementation notes (backend v1 — these refine the sections above)

1. `Me.user` is `null` for a kiosk principal.
2. 409 `version_conflict` bodies carry the current object: `{detail, code:"version_conflict", product}` (products) or `{..., item}` (shopping). 409 `barcode_exists` carries `product_id`.
3. Every sync `OpResult` also has `error_code` (`clamped`, `already_undone`, `not_found`, `product_not_found`, `invalid_quantity`, `missing_target`, `location_not_found`, `invalid_barcode`, `no_location`, `invalid_op`). Rejected ops are not stored, so a retry is rejected again (deterministic).
4. `GET /api/products/by-barcode/{raw}` additionally returns `barcode: {code, raw, symbology}` and `valid`. A provider hit is stored in the catalogue and returned with `status:"found"` and `source:<provider>`.
5. Kiosk allowlist additionally includes `GET /api/auth/me`, `POST /api/auth/logout`, `GET /api/settings`, `GET /api/shopping/suggestions`, `GET /api/products`, `GET /api/products/{id}`.
6. `GET /api/products` returns a plain JSON array.
7. `PATCH /api/shopping/{id}` requires `If-Match` unless the body only toggles `checked`. Un-checking an item whose product already has an open item merges into it.
8. `move` transactions record the positive moved quantity in `quantity_delta`; consumption statistics use `type in ('add','remove')` only.
9. Per-batch effects are stored in `stock_transaction_lines` so undo restores exactly the batches touched.
10. `GET /api/inventory?location_id=` limits `total_quantity`/`batches` to that location; `low_stock` uses the overall total.
11. `PN_TIMEZONE` (default `Europe/Copenhagen`) defines "today" for expiry. Deleting a product frees its barcodes. Deleting a location is refused (409) if it is the default or holds stock. Deactivating a user revokes all their sessions.
12. `GET /api/sync/changes` may re-send rows already seen (transaction-id based cursor, see §3.2); clients must upsert idempotently. Cursors are versioned (`x1.<db oid>.<xid>`) and tied to the database instance; anything else triggers `full_resync_required`.
12a. `GET /api/transactions?before=` takes an ISO timestamp or the composite `<iso>|<uuid>` cursor returned in the `X-Next-Before` response header (sent when a page is full); ordering is `(created_at, id)` descending, so ties are never skipped. Database outages answer `503 {code:"db_unavailable"}` with `Retry-After`.
13. **Lookup / media / export / stats / admin (T1b).** Sources, limits and licences: `product-data-sources.md`. Provider hits are cached (`lookup_cache`: found 30 d, not_found 7 d, errors with exponential `retry_after`) and every attempt is logged (`lookup_attempts`: `found, not_found, error, rate_limited, cache_hit, cache_negative, cache_error`). Provider data never overwrites `locked_fields`; products with `source:"user"` only get empty fields filled; low confidence (< 0.6) gives `status:"needs_review"`. `POST /products/{id}/photo` adds `"image"` to `locked_fields` (422 `invalid_image`, 413 when > 8 MB). `POST /products/{id}/refresh` returns the Product (kiosk: 403). `GET /media/{name}` is unauthenticated (uuid file names). Exports: CSV = UTF-8 BOM, `;`, CRLF, decimal comma, local-time timestamps, `'`-prefix against formula injection; JSON = pretty array with numeric values; `expiring` takes `?days=`. `GET /stats?days=&product_id=` returns `{days, top_added, top_consumed:[{product_id,name,quantity,count}], daily:[{date,added,removed}], series?:[{date,quantity}]}`. `GET /admin/lookups?status=&limit=&offset=`. `GET/PATCH /admin/providers` use `{providers:[{id,name,enabled,priority,requires_key,has_key,api_key(masked),key_source,license,attribution,rate_limit_per_min}]}`; PATCH items `{name, enabled?, priority?, api_key?}` (`""` clears a stored key). `GET /ha/summary`: see `home-assistant.md` (bearer token only). Migration `0002` adds `provider_settings`. Worker: `python -m pantrynanny.worker`.

## 8. Additions (October 2026)

All endpoints are household-scoped and need a session or device token like the rest of the API.
None of them change stock except through the normal ops in §3 (`POST /sync/ops`, `/transactions/{id}/undo`).

| Endpoint | Purpose |
|---|---|
| `GET /kitchen/tiles?limit=12` | Favourites first, then most-used products (60 days), with stock. Used by `/kitchen`. |
| `PUT /products/{id}/favorite {favorite}` | Pin/unpin on the kitchen screen. No version bump, no field lock. |
| `GET /activity?limit&before` | Timeline: transactions with product and user name. Keyset cursor in `X-Next-Before`. |
| `GET /stats/runout?days=14[&product_id]` | Run-out forecast from the household's own removals (90-day window). `confidence` is `medium` (≥3 events) or `high` (≥6 events over ≥21 days); products with less history get no forecast. |
| `GET/POST /recipes`, `GET/PUT/DELETE /recipes/{id}` | Recipe CRUD. Ingredients are sent as raw lines and parsed server-side. `PUT` accepts `If-Match`. |
| `POST /recipes/parse {lines}` | Preview how ingredient lines are understood. |
| `POST /recipes/import {url}` | Read a schema.org Recipe (JSON-LD) from a public page. Returns a draft; nothing is saved. See below. |
| `GET /recipes/suggest?max_minutes&servings` | "What can we cook": saved recipes ranked by availability. |
| `GET /recipes/{id}/availability?servings` | Per ingredient: `have`/`low`/`missing`/`staple`/`optional`, matched product, `need` in the product's stock unit. |
| `POST /recipes/{id}/shopping {servings?, ingredient_ids?}` | Add missing ingredients to the shopping list (no duplicate free-text items). |
| `GET /meal-plan?start&days`, `POST /meal-plan`, `PATCH/DELETE /meal-plan/{id}` | Meal plan. `PATCH {cooked}` only stamps the entry. Planning never changes stock. |
| `POST /meal-plan/shopping {start, days}` | Sums the needs of uncooked planned recipes per product, subtracts stock and adds the shortfall. |
| `GET/PATCH /admin/ai`, `POST /admin/ai/test` | Admin-only AI endpoint settings (DB overrides on top of env) and a connectivity/vision test. The API key is never returned. |

Shopping items have an optional `store` (≤60 chars).

**Recipe import safety.** Only `http(s)` on ports 80/443/8080/8443 and no credentials in the URL. Every hop, redirects
included, is resolved first. The request is refused unless all addresses are public: no loopback, private, link-local,
CGNAT, multicast or IPv4-mapped private addresses. The connection is pinned to the checked address, with SNI/Host set
to the real name, so DNS rebinding cannot redirect it. Size is capped at 3 MB and the timeout is 10 s. Page content
is reduced to plain text and never rendered as HTML.

**Cooking.** The client shows the proposed deductions (`need`, capped at stock). Unknown amounts are unticked. After
the user confirms, the client sends one `remove` op per product with `reason: "recipe"`. Undo sends `undo` ops for
exactly those op ids.

**AI tools.** These are read-only in addition to §5: `what_can_we_cook`, `get_meal_plan`, `get_running_out`. The
`propose_add_to_shopping`, `propose_plan_meal` and `propose_use_up` tools only record a suggestion. Each one is
validated and resolved to a real product or recipe (quantity capped at stock, date between today and 60 days ahead,
at most 5). It is returned in `ChatOut.proposals`. The server never executes a proposal. The client runs it through
the normal endpoint when the user taps it.
