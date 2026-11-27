# Changelog

## 2026-11-27 – every cookable recipe, live search, Mealie photos and categories

- **"What can we cook?" shows every match**, not the first 20: `GET /recipes/suggest` returns all matches unless
  `limit` is given, and takes `q`. Web pages 24 cards at a time, Android 20, with a page count.
- **Live filter** on "What can we cook?" (web and Android): every word must appear in the title, tags, categories,
  course, ingredients, description, source or what it uses up; `#tag` works too. On Android, other saved recipes
  that match (but miss more) are listed below.
- **Mealie import** (`pantrynanny-admin import-mealie`, [docs/mealie-import.md](docs/mealie-import.md)): re-runnable,
  matches recipes from an earlier import, copies photos into PantryNanny's own storage, and brings categories and
  tags. Recipes have a new `categories` list (migration 0012, also `external_id`), filter `category=` on
  `/recipes` and `/recipes/suggest`.
- Recipe cards show the photo and categories; a category picker sits next to the other filters (web) or as chips
  (Android).

## 2026-10-25 – recipes and stock data good enough for a diet coach

- **Matching recipe lines to products** (measured with the new `scripts/match_eval.py` on a hand-checked golden set
  of 317 ingredient names, `backend/tests/fixtures/match_golden.json`): precision 0.869 → 1.000, recall 0.521 →
  0.982.
  - Danish adjective endings (finvalset = finvalsede), the main product name before " - variant", ", variant",
    "(…)", pack size or percentage ("Boo Chopped Tomatoes - Herbs" is chopped tomatoes), unit words the parser left
    ("c. tahini", "can black beans") and Korean/other-script labels are handled.
  - Synonyms moved to a data file, `backend/pantrynanny/recipes/synonyms.txt`, applied to both sides, with
    "kind of" rules (sunflower oil is a neutral oil, cannellini beans are white beans).
  - New traps: a colour the recipe names must be the product's ("sorte bønner" ≠ "hvide bønner", brown rice ≠
    jasmine rice), "tamari" ≠ Tamarind, vanilla sugar ≠ sugar, "tomatoes" ≠ canned chopped tomatoes,
    "flour" ≠ whole-wheat flour, "ice" ≠ juice, a bare "sauce" ≠ Gochujang Sauce.
- **Staples are a household list** (Admin → Indstillinger; `GET/PATCH /settings` `staples`), seeded with salt,
  pepper, water, oil, olive oil, sugar, wheat flour, baking powder, bicarbonate and common dried spices.
  "salt og friskkværnet peber", "kosher salt", "flagesalt", "water or broth" now count. A staple the household keeps
  as a product is reported from stock like any product. On the real data, staple lines went from 4.6 % to 19.7 %
  and missing lines from 84 % to 64 %.
- **Courses and ranking.** Recipes have a `course` (breakfast, lunch, dinner, side, dessert, baking, drink, snack,
  condiment) from the page's category, else the title, else the ingredients; editable. `/recipes` and
  `/recipes/suggest` take `course`, `exclude_course`, `tag`, `min_ingredients` and `include=summary` (flat rows for
  machine clients). Ranking uses smoothed coverage `have / (required + 2)`, so a two-line sweet no longer beats a
  real dish.
- **Cooking times.** Imports read schema.org microdata when there is no JSON-LD (valdemarsro.dk), and use the total
  time when it is longer than prep + cook. An admin job (`POST /admin/recipes/backfill`,
  `pantrynanny-admin backfill-recipes`) re-reads source pages for recipes without time or course: safe fetcher,
  one page every 2 s, resumable.
- **Stock data at scan time** (web and Android): after an add, one-tap expiry chips (+3 d, +1 u, +1 m, +6 m,
  ingen; the category's default highlighted) and location chips (`POST /inventory/place`). Categories remember where
  their things go and have a default shelf life. New **"Ryd op"** screen (`/fix-up`) sets location/expiry for many
  items at once (`POST /batches/fix-up`).
- **Read-only device tokens**: `POST /auth/token {…, "scope": "read"}` can only read.
- Migration 0011 (reversible): `household_settings.staples`, `recipes.course`, `recipes.source_checked_at`,
  `categories.default_expiry_days`, `categories.default_location_id`, `sessions.scope`.

## 2026-10-20 – Android app parity, photos of unknown items

- **Android is now a full app.** It still opens in the scanner. Five tabs: Scan · Lager · Indkøb · Mad · Mere.
  - **Product screen:** nutrition per 100 g, ingredients, allergens, history, run-out forecast and favourite.
    You can take out N, count, move and set expiry (+N days), and add the product to the shopping list.
  - **Native screens:** shopping list (shops, suggestions, put away), recipes ("what can we cook", cook with
    confirmation and undo, missing items to the list, import from a link, editor), week meal plan, overview,
    activity and assistant (suggested actions only on tap).
  - The "Indkøbsliste" launcher shortcut now opens the app's own list.
- **Photos of unknown items.** When a barcode is not recognised, the scanner (web and Android) keeps the camera
  frame and uploads it as the item's photo once its placeholder exists. Offline, it waits until the next sync.
  - It is stored as a *snapshot*: never replaces a real photo, not locked, and replaced automatically when
    Open Food Facts later finds the product (migration 0010 adds `products.image_is_snapshot`).
  - `POST /products/{id}/photo?snapshot=true`.

## 2026-10-20 – server review follow-ups

- **Locations.** Items with no known place now go to the fridge (Køleskab) instead of the pantry. Migration 0009
  only changes households that still have the original seed default. Moving a product's stock to another place
  makes that its place for future scans, and undoing the move undoes that too. The first add with an explicit
  location also sets it.
- **Lookups.** Open Beauty / Pet Food / Products Facts stay enabled, but only the background worker asks them.
  A scan never waits for them, and each has its own rate budget (the docs said "disabled by default"; corrected).
- **Fewer PostgreSQL errors.** Concurrent creation of the same new barcode is serialised with an advisory lock,
  instead of relying on a duplicate-key error caught by a savepoint.
- **Deploys.**
  - nginx answers `503` + `Retry-After` (JSON `code: restarting`) instead of `502` while the API restarts.
    Clients already retry it.
  - The health-check timer is paused during a deploy.
  - Releases leave out sourcemaps and backend tests, and the last 3 releases are kept instead of 5.
- **Logging.** The nginx access log records the forwarded scheme and host, request time and upstream time.
- **Unknown products.**
  - The dashboard nudges when products still need a name.
  - Products you named yourself link to Open Food Facts so you can add them there. Nothing is uploaded
    automatically.
- **Docs.** README documents restoring from a pre-deploy dump.

## 2026-10 – "from functional to outstanding"

Database migrations 0005–0008 only add tables and columns. `install.sh` now takes a verified `pg_dump` into
`/var/backups/pantrynanny/pre-deploy/` before every migration (the last 10 are kept), and the dump can be restored
with `restore.sh`.

### Scanning
- Bluetooth/USB hand scanners in keyboard mode work on `/scan`. A burst of fast keystrokes ending in Enter/Tab is
  treated as a scan. Normal typing, text fields and shortcuts are ignored, and a bounced trigger is debounced.
- A camera-off "hand scanner only" station mode.
- `+1 / +2 / +5` (or `−…`) after a scan, for several identical items. Each tap is its own undoable op.
- Scan sessions start automatically and end after 10 minutes idle or on exit. The summary shows added, removed and
  unknown items, plus a link to name the unknown ones. The last 10 sessions per device are listed under Settings › Scanner.

### Kitchen mode (`/kitchen`)
- A glanceable tablet screen: clock, big Scan in / Scan out / shopping / use-soon actions.
- "Took one" tiles for favourites and most-used products. One tap removes one, with an 8 s undo.
- Use-first and running-low lists, a dim mode, and the screen is kept awake while the page is open.

### Recipes and meal plan
- Recipes with a Danish/English ingredient parser: fractions, ranges, units, notes, and "evt."/"optional".
- Deterministic pantry matching: aliases, an en→da synonym table, and Danish compounds (*letmælk* matches *mælk*) with
  explicit traps (*løg* ≠ *hvidløg*, *mel* ≠ *karamel*). Amounts are converted to stock units (2 dl of a 1 l carton = 0.2).
- "What can we cook?" ranks saved recipes: cookable first, then coverage, then recipes that use up food expiring soon.
  Time filters are available.
- Import from a link (schema.org JSON-LD). The fetch is SSRF-safe, and the draft is reviewed before it is saved.
- "Cook this" shows exactly what will be taken out of stock. You can edit or untick each line, nothing happens until
  you confirm, and there is one-tap undo.
- Missing ingredients go to the shopping list (no duplicates).
- Week meal planner with cooked check-off and "shop for the week". Planning never deducts stock.

### Everyday
- Activity timeline (`/activity`): who changed what, when, with undo.
- Run-out forecasts from your own usage, with a confidence level. There is no forecast when there is too little data.
- Expiry quick dates: +1/+3/+7/+14/+30 days, or no date.
- Shopping list: an optional shop per item, grouping by shop, and "put the shopping away" (ticked items go into stock
  after you confirm).

### Assistant (optional local AI)
- AI endpoint, key, model, timeout, token limit, temperature, "disable thinking" and per-feature switches are editable
  in Admin › AI. A connectivity test checks models, text and vision. Env values stay the defaults.
- Reasoning models that spend the whole budget "thinking" are retried once without thinking. If the answer is still
  empty, the error message says what to change.
- New grounded tools: saved recipes, meal plan and run-out forecasts.
- The assistant can **suggest** actions (shopping, plan a meal, take out of stock). They appear as buttons and only
  happen when you tap them.

### Android
- Launcher shortcuts: Scan in, Scan out, Shopping list.
