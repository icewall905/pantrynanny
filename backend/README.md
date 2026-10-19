# PantryNanny backend

FastAPI + PostgreSQL (SQLAlchemy 2 async/asyncpg, Alembic). The API contract is
[`../docs/api-contract.md`](../docs/api-contract.md); interactive docs are served at `/api/docs`
(OpenAPI JSON at `/api/openapi.json`).

## Development setup

Requires Python 3.13 (Debian 13 ships `python3.13`; locally `uv python install 3.13`) and PostgreSQL 15+
with the `pg_trgm` and `unaccent` extensions (in the standard contrib package; the migration runs
`CREATE EXTENSION IF NOT EXISTS`, which needs a superuser or a trusted-extension-capable role).

```bash
cd backend
uv sync                              # creates .venv from uv.lock
cp ../.env.example .env              # then edit PN_DATABASE_URL etc. (never commit .env)
uv run alembic upgrade head          # create / migrate the schema
uv run pantrynanny-admin create-user --username anna --display-name Anna   # prompts for password;
                                     # first user becomes owner and creates the household
uv run uvicorn pantrynanny.main:app --reload --port 8000
```

Configuration is read from `PN_*` environment variables and an optional `.env` (see
`pantrynanny/config.py` and `../.env.example`).

### Admin CLI

```
pantrynanny-admin create-household --name "Hjemmet"
pantrynanny-admin create-user --username anna --display-name Anna [--role owner|admin|member] [--password P | --generate]
pantrynanny-admin reset-password --username anna [--password P | --generate]   # also revokes sessions
pantrynanny-admin list-users
pantrynanny-admin create-kiosk-code --name "Kitchen iPad"                      # 15 min, single use
```

Creating the first user creates the household (default locations and categories are seeded;
Spisekammer is the default location). `--generate` prints the password once; `--password` ends up in
shell history, prefer the prompt.

## Production

Run a single worker on loopback behind nginx (rate limiting and cookie state are in-process):

```bash
uvicorn pantrynanny.main:create_app --factory --host 127.0.0.1 --port 8000 --no-access-log
# `pantrynanny.main:app` is an equivalent module-level alias.
```

* `--no-access-log`: the app writes its own structured JSON access log (method, path without query
  string, status, duration, ip, request id). Headers, cookies and tokens are never logged.
* **Proxy headers**: `PN_TRUSTED_PROXIES` (comma separated IPs/CIDRs, or `*`) lists the reverse proxies
  whose `X-Forwarded-For/-Proto` are trusted. The app installs uvicorn's `ProxyHeadersMiddleware` with
  that list, so you do not need `--proxy-headers/--forwarded-allow-ips` (nginx must send
  `X-Forwarded-For` and `X-Forwarded-Proto`). It drives the real client IP (login rate limiting) and the
  `Secure` cookie flag (set when the request scheme is https).
* Run `alembic upgrade head` on every deploy before starting the service.

## Tests

Tests run against a real PostgreSQL and build the schema with `alembic upgrade head` on a fresh
`public` schema (they refuse to run unless the database name ends in `_test`).

```bash
docker run -d --name pn-test-pg -e POSTGRES_PASSWORD=pn -e POSTGRES_DB=pantrynanny_test \
  -p 127.0.0.1:55433:5432 postgres:17
uv run pytest                        # PN_TEST_DATABASE_URL overrides the default
                                     # postgresql+asyncpg://postgres:pn@127.0.0.1:55433/pantrynanny_test
uv run ruff check . && uv run ruff format --check .
```

## Layout

```
pantrynanny/
  main.py        app factory, middleware (proxy headers, access log, body limits, CORS)
  config.py db.py logging.py errors.py security.py (passwords, tokens, CSRF, kiosk scope, roles)
  models.py      SQLAlchemy models (schema source of truth is the Alembic migration)
  schemas/       Pydantic request/response models
  routers/       thin HTTP layer, one module per resource
  services/      business logic: barcodes (pure), products, inventory (apply_op), sync,
                 shopping, dashboard, households, lookup/ (interface for external providers)
  cli.py         pantrynanny-admin
alembic/         async env + 0001_initial_schema (extensions, change_seq trigger, trigram indexes)
tests/
```

## Design notes

* **Stock is transaction based.** Every change is an append-only `stock_transactions` row (unique per
  `(household_id, client_op_id)`) plus `stock_transaction_lines` (per-batch effect, which makes undo exact).
  Each op runs in its own DB transaction with `SELECT ... FOR UPDATE` on the product row.
* **change_seq** is stamped by a `BEFORE INSERT OR UPDATE` trigger from the global sequence
  `change_seq_seq` on products, stock_batches, locations and categories; it also maintains `updated_at`.
  `GET /sync/changes` re-reads a 200-value window below the client cursor to tolerate sequence values
  that commit out of order; clients must upsert.
* Lookups (`GET /products/by-barcode`) never touch stock. External providers plug in via
  `services/lookup/__init__.py` (`lookup_external`, `enqueue_enrichment`).
