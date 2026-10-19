# PantryNanny

Self-hosted kitchen inventory for (Danish) households: scan groceries in and out with a
wall-mounted iPad (PWA) or an Android phone, see what you have, what is expiring and what to buy.

> Status: under active development. Full documentation is being written; see `docs/`.

- `backend/` – FastAPI + PostgreSQL API (product catalogue, stock transactions, offline sync, lookups, optional AI)
- `web/` – React + TypeScript web app and the continuous-scanning PWA (`/scan`)
- `android/` – native Kotlin/Compose scanner app (CameraX + ML Kit, Room, WorkManager)
- `deployment/` – systemd/nginx based install, deploy, backup and restore scripts
- `docs/` – API contract, iPad PWA notes, product brief

Product data from [Open Food Facts](https://world.openfoodfacts.org) is available under the
[Open Database License](https://opendatacommons.org/licenses/odbl/1-0/).
