# Changelog

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
