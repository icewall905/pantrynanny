# Performance notes

Measured 2026-10-19 on a development machine: a 4 vCPU cloud container with PostgreSQL 16 and a single
uvicorn worker, calling the API directly on loopback with a device token. There was no nginx/TLS hop and
no Wi-Fi, so expect a few extra milliseconds in production. The database held the 19,814-row seed
catalogue and about 200 household products. **None of these numbers come from a real iPad or Android
phone**; device-side figures are listed separately below.

## Scanning path

Known barcodes need no server round trip at all. The scanner looks the barcode up in the local store
(IndexedDB on the web, Room on Android), queues the operation and updates the displayed quantity
straight away. The server timings below only affect how quickly *other* devices see the change and
how fast unknown barcodes resolve.

| What | p50 | p95 | Notes |
|---|---|---|---|
| `GET /products/by-barcode` – first scan of a seeded barcode (creates the product from the seed) | 17 ms | 23 ms | no network call; the seed is a local table |
| `GET /products/by-barcode` – barcode already in the household catalogue | 8 ms | 11 ms | |
| `POST /sync/ops`, batch of 20 `add` ops | 353 ms | 398 ms | ≈ 17 ms per op: each op is its own transaction with a row lock, so one bad op never fails the batch |
| `GET /sync/changes` with nothing new | 8 ms | 12 ms | the idle poll every client does |
| `GET /sync/snapshot` (≈ 210 products) | 36 ms | 45 ms | only after login or a restore |
| `GET /inventory` (≈ 210 products) | 32 ms | 42 ms | |

For barcodes that are neither in the household catalogue nor in the seed, `by-barcode` may call Open
Food Facts synchronously with a 3 s budget (`PN_LOOKUP_TIMEOUT_S`). On a miss or timeout it creates a
placeholder immediately and leaves the rest to the background worker, so scanning never waits on the
internet.

## Web app (PWA) size

Production build (`npm run build`), gzip sizes:

| What | Size |
|---|---|
| First load (all JS preloaded by `index.html`) | ≈ 149 kB JS + 9 kB CSS |
| Scanner page (`/scan`, lazy-loaded) | 130 kB |
| ZXing decoder worker (lazy-loaded with the scanner) | 118 kB |

Everything is precached by the service worker, so after the first visit the app (including the
scanner) starts without the network.

## Decoder (headless Chromium)

From [ipad-pwa.md](ipad-pwa.md): ZXing in a Web Worker on a ≤ 800 px centre crop at about 12 fps took
about 3 ms per frame, and frame-to-UI latency was 25–90 ms. On the device, the hidden debug overlay
(tap the connection pill 5 times) shows live fps, decode time and frame-to-UI latency.

## Seed catalogue import

`pantrynanny-admin import-seed`: 19,814 rows in 4.4 s, upserted in batches of 2,000. The installer runs
it with `--if-changed`, which skips the import when the same dataset version is already loaded.

## Not measured yet (needs real devices or production traffic)

- Camera responsiveness, decode rate and thermal behaviour on the wall-mounted iPad over hours.
- ML Kit decode latency and time-to-UI on a physical Android phone.
- Lookup cache hit rate. It only means something with real household traffic. Once the system has been
  in use for a while, compute it from the attempt log (`GET /api/admin/lookups`, statuses `cache_hit` /
  `cache_negative` versus `found` / `not_found`).

## Reproducing

Start a backend with the seed imported, create a user, then time calls with any HTTP client against
`/api/auth/token`, `/api/products/by-barcode/{code}`, `/api/sync/ops`, `/api/sync/changes` and
`/api/sync/snapshot`. Bundle sizes: `cd web && npm run build`, then
`gzip -c dist/assets/<file> | wc -c`.
