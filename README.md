# PantryNanny

Self-hosted kitchen inventory for (Danish) households. Scan groceries in and out with a wall-mounted
iPad (PWA) or an Android phone, and see what you have, what is about to expire and what to buy.

The design rule: **using PantryNanny must be faster than keeping track by hand.** Known barcodes are
recognised locally and counted immediately, unknown ones never block scanning, and every scan is queued
on the device first and synchronised exactly once.

| Part | What it is |
|---|---|
| [`backend/`](backend/README.md) | FastAPI + PostgreSQL API: product catalogue, append-only stock transactions, offline sync, barcode lookups, exports, optional local AI |
| [`web/`](web/) | React + TypeScript web app and installable PWA, including the continuous scanner at `/scan` (iPad/Safari compatible) |
| [`android/`](android/README.md) | Native Kotlin/Compose scanner app (CameraX + ML Kit, Room, WorkManager) |
| [`deployment/`](deployment/) | One-command deploy, idempotent installer, systemd units, nginx, backup/restore |
| [`docs/`](docs/) | API contract, iPad guide, Home Assistant, data sources and licences, performance |

## Features

- **Continuous scanning** in Add / Remove mode. A barcode held in view counts once; taking it away
  and presenting it again counts again. Remove mode falls back to Add after inactivity, so you can't
  stay in Remove by accident. Every scan can be undone.
- **Offline first.** Scans become operations with a client-generated id, stored in IndexedDB (web) or
  Room (Android) and uploaded when the server is reachable. The server deduplicates on that id, so retries
  are safe. Clients pull changes incrementally with a database-bound cursor.
- **Product recognition**: the household's own catalogue, then a bundled offline seed of 19,814 Danish
  products (Open Food Facts), then Open Food Facts and its sister projects (Beauty / Pet Food / Products
  Facts) online (rate limited, cached), then optional EAN-Search. Unknown barcodes become placeholders,
  are enriched in the background and can be named on the spot ("Registrer"), with a photo, so they are
  known for every later scan.
- **Inventory**: batches with expiry dates, multiple storage locations, minimum stock, a shopping list
  with suggestions, statistics and CSV/JSON exports.
- **Households and users**: owner/admin/member roles, device tokens for Android, single-use pairing codes
  for kiosk iPads.
- **Optional local AI** (any OpenAI-compatible endpoint): identify a product from a photo and an
  inventory assistant chat. Everything else works without it.
- **Home Assistant** summary endpoint ([docs/home-assistant.md](docs/home-assistant.md)).
- Danish UI by default, English available. Dark theme by default, light available (per device).
- **Android app download** from the web app (Settings and login page), built by every deploy.

## Architecture

```
 iPad PWA / browser ──┐                    ┌── nginx :8734 ── static web app (PWA, service worker)
 Android app ─────────┼── HTTPS ─ reverse ─┤
                      │   proxy (TLS)      └── /api ─► uvicorn 127.0.0.1:8000 (FastAPI) ─► PostgreSQL (localhost)
                                                          ▲
                              pantrynanny-worker ─────────┘  background enrichment (Open Food Facts …)
```

- Stock is never stored as a bare number that clients overwrite. Every change is an append-only
  transaction with per-batch lines, which makes undo exact and concurrent devices safe.
- The sync cursor is `x1.<database oid>.<oldest running transaction id>`. Rows are stamped by a trigger
  with the id of the transaction that wrote them, so a pull can't miss a slow writer. A restore
  invalidates every cursor and forces clients to download a full snapshot. Details:
  [docs/api-contract.md §3](docs/api-contract.md).
- Barcodes are normalised the same way on all three clients and the server: GTIN-14 for valid
  EAN/UPC, `instore:` for variable-weight codes, `local:` for everything else. Parity tests cover all
  of them.

## Install (production)

The target is a Debian 13 container, e.g. a Proxmox LXC (the brief sizes it at 2 vCPU, 4 GB RAM and
24 GB disk). The installer adds PostgreSQL, nginx and Python packages. The web app is served on **port 8734**; TLS is
terminated by your reverse proxy (Traefik, Caddy, …).

1. On your workstation (needs `git`, Node 22+ and [`uv`](https://docs.astral.sh/uv/)):

   ```bash
   cp deployment/site.env.example deployment/site.env   # gitignored; set PN_DEPLOY_TARGET
   deployment/deploy.sh
   ```

   `PN_DEPLOY_TARGET` is `ssh:root@<container>` or `pct:root@<proxmox-host>:<ctid>` (push through
   `pct`). With the Android SDK installed (`ANDROID_HOME`) it also builds the Android APK that the web
   app offers at `/downloads/pantrynanny.apk`; `PN_DEPLOY_APK=0` skips that, and the server keeps the
   previous APK. The script builds a release from the committed `HEAD`, copies it over and runs
   [`install.sh`](deployment/scripts/install.sh). That script is idempotent: it creates the system user,
   database, config file (with a generated DB password) and systemd units, runs migrations, imports the
   seed catalogue, switches the `current` symlink, waits for the health check, and rolls back to the
   previous release if the check fails. It never overwrites existing config or data.

2. On the container, edit `/etc/pantrynanny/pantrynanny.env` (see [Configuration](#configuration)).
   At minimum set `PN_PUBLIC_URL`, `PN_TRUSTED_PROXIES` (your reverse proxy's IP) and a contact address
   in `PN_OFF_USER_AGENT`, then run `systemctl restart pantrynanny-api pantrynanny-worker`.

3. Create the first user. They become the owner, and the household is created with default locations
   and categories:

   ```bash
   cd /opt/pantrynanny/current/backend && set -a && . /etc/pantrynanny/pantrynanny.env && set +a
   runuser -u pantrynanny -- /opt/pantrynanny/current/venv/bin/pantrynanny-admin create-user --username anna --display-name Anna
   ```

   Add more people the same way (`--role admin|member`), or in the web app under Admin → Users.

4. Point the reverse proxy at `http://<container-ip>:8734` for your hostname (for example
   `https://pantry.example.com`). It must send `X-Forwarded-For` and `X-Forwarded-Proto`, and its
   IP must be listed in `PN_TRUSTED_PROXIES`, otherwise login rate limiting sees the proxy IP and
   cookies are not marked `Secure`.

Updates are the same `deployment/deploy.sh` command. The last 5 releases are kept in
`/opt/pantrynanny/releases`.

### Devices

- **iPad (wall-mounted)**: open `https://<host>/scan` in Safari, *Share → Add to Home Screen*, then pair it
  as a kiosk so nobody has to log in on it: `pantrynanny-admin create-kiosk-code --name "Kitchen iPad"`
  (single use, valid for 15 min) or under Admin → Devices in the web app. Mounting, lighting and Guided Access:
  [docs/ipad-pwa.md](docs/ipad-pwa.md).
- **Android**: download the `pantrynanny-debug-apk` artefact from the latest green
  [Android workflow](.github/workflows/android.yml) run, or build it yourself, then log in with the
  server address. Release signing and sideloading: [android/README.md](android/README.md).

## Configuration

Everything lives in `/etc/pantrynanny/pantrynanny.env` (mode 0640, root:pantrynanny). It starts as a copy
of [`.env.example`](.env.example), which documents every variable. The important ones:

| Variable | Default | Purpose |
|---|---|---|
| `PN_DATABASE_URL` | generated | asyncpg URL; PostgreSQL only listens on localhost |
| `PN_PUBLIC_URL` | – | external URL, used for CORS and the `Secure` cookie decision |
| `PN_TRUSTED_PROXIES` | `127.0.0.1` | IPs/CIDRs whose `X-Forwarded-*` headers are trusted |
| `PN_TIMEZONE` | `Europe/Copenhagen` | defines "today" for expiry |
| `PN_OFF_ENABLED` / `PN_OFF_USER_AGENT` | `true` / – | Open Food Facts lookups; OFF asks for a contact address in the UA |
| `PN_SEED_ENABLED` | `true` | the bundled offline seed catalogue |
| `PN_OFF_SISTERS_ENABLED` | `true` | Open Beauty / Pet Food / Products Facts after an Open Food Facts miss |
| `PN_OFF_RATE_PER_MIN` / `PN_OFF_WORKER_RATE_PER_MIN` | `8` / `6` | outgoing budget (OFF allows 15 reads/min/IP) |
| `PN_EANSEARCH_TOKEN` | empty | optional commercial fallback |
| `PN_AI_BASE_URL` / `PN_AI_MODEL` / `PN_AI_API_KEY` | empty | OpenAI-compatible endpoint; empty disables AI |

Lookup providers can also be enabled, disabled, reordered and given API keys at runtime under
Admin → Providers.

## Operations

| | |
|---|---|
| Web app | `http://<container>:8734/`, scanner at `/scan` |
| API docs | `/api/docs` (OpenAPI JSON at `/api/openapi.json`) |
| Health | `GET /api/health` → `{"status":"ok","db":"ok","ai":…}` |
| Services | `pantrynanny-api`, `pantrynanny-worker`, `nginx`, `postgresql` |
| Timers | `pantrynanny-backup.timer` (03:15 nightly), `pantrynanny-healthcheck.timer` (restarts a hung API after 2 failed checks) |
| Logs | `journalctl -u pantrynanny-api -u pantrynanny-worker` (structured JSON; tokens, cookies and query strings are never logged) |
| Paths | code `/opt/pantrynanny/current`, data `/var/lib/pantrynanny`, config `/etc/pantrynanny`, backups `/var/backups/pantrynanny` |
| Admin CLI | `pantrynanny-admin create-user / reset-password / list-users / create-kiosk-code / import-seed` |

### Backups and restore

[`backup.sh`](deployment/scripts/backup.sh) runs nightly. It writes a custom-format `pg_dump`, a tarball
of uploaded photos and a copy of the env file, checks that the dump is readable, writes `SHA256SUMS`,
and keeps 14 daily, 8 weekly and 12 monthly copies. Run it by hand with
`systemctl start pantrynanny-backup`. Copy `/var/backups/pantrynanny` off the host as well; a backup on
the same disk doesn't protect against losing that disk.

```bash
# verify a backup into a scratch database (live services untouched)
deployment/scripts/restore.sh /var/backups/pantrynanny/daily/<ts> --target-db pantrynanny_verify
# replace the live database and uploads (asks for confirmation; stops services, restores, restarts)
deployment/scripts/restore.sh /var/backups/pantrynanny/daily/<ts>
```

The database OID changes on a live restore, so every client cursor becomes invalid and devices download
a full snapshot on their next sync. If the backup came from an older release, run `deployment/deploy.sh`
afterwards; the installer applies any pending migrations.

## Development

```bash
# backend (Python 3.13, PostgreSQL 15+ with pg_trgm/unaccent)
cd backend && uv sync && cp ../.env.example .env   # edit PN_DATABASE_URL
uv run alembic upgrade head && uv run pantrynanny-admin create-user --username dev
uv run pantrynanny-admin import-seed               # optional: offline barcode seed
uv run uvicorn pantrynanny.main:app --reload --port 8000
uv run python -m pantrynanny.worker                # optional: background enrichment

# web (Node 22+); proxies /api to :8000 (PN_API_URL overrides)
cd web && npm ci && npm run dev
```

Android needs JDK 21 and the Android SDK; see [android/README.md](android/README.md).

### Tests

| Suite | Command | Last result |
|---|---|---|
| Backend (real PostgreSQL) | `cd backend && uv run pytest` | 240 passed |
| Backend lint | `uv run ruff check . && uv run ruff format --check .` | clean |
| Web unit | `cd web && npm test` | 111 passed |
| Web lint / types | `npm run lint && npm run typecheck` | clean |
| Web e2e (real backend, Chromium) | `PN_E2E_BASE_URL=http://127.0.0.1:4173 PN_E2E_USER=… PN_E2E_PASSWORD=… npx playwright test` | 16 passed, 2 skipped (scanner specs are desktop-only) |
| Android (CI) | `./gradlew testDebugUnitTest assembleDebug lintDebug` | see the Android workflow |

For the e2e run, serve a production build with `npx vite preview --port 4173` in front of a backend on
`:8000`. Set `PN_CHROMIUM` to use an already-installed Chromium. The scanner specs feed a generated
barcode video through Chromium's fake camera. Backend tests refuse to run unless the database name ends
in `_test`.

### What still needs real-device verification

Automated tests run in headless Chromium and on the JVM. These need a real device:

- Camera decoding speed, focus and thermal behaviour on the actual wall-mounted iPad over hours
  ([docs/ipad-pwa.md](docs/ipad-pwa.md)).
- ML Kit scanning, sound/vibration feedback and background sync on a physical Android phone.
- Safari-specific PWA behaviour: storage eviction, Add to Home Screen, Wake Lock.

## Documentation

- [docs/api-contract.md](docs/api-contract.md): REST API, sync protocol, barcode normalisation
- [docs/ipad-pwa.md](docs/ipad-pwa.md): iPad findings, wall-mount setup, kiosk pairing, debug overlay
- [docs/performance.md](docs/performance.md): measured latencies and bundle sizes
- [docs/home-assistant.md](docs/home-assistant.md): sensors via `GET /api/ha/summary`
- [docs/product-data-sources.md](docs/product-data-sources.md): lookup providers, limits, caching
- [docs/data-licences.md](docs/data-licences.md): Open Food Facts ODbL attribution, seed catalogue
- [backend/README.md](backend/README.md): backend layout, admin CLI, design notes
- [docs/product-brief.md](docs/product-brief.md): the original brief

## Data

Product data from [Open Food Facts](https://world.openfoodfacts.org) is available under the
[Open Database License](https://opendatacommons.org/licenses/odbl/1-0/). The bundled barcode seed
catalogue and all data licences are described in [docs/data-licences.md](docs/data-licences.md).
