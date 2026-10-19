# Handover: cloud session → local agent (2026-10-19)

This session built most of the P0/P1 parts of the "outstanding product" brief on branch `cc/sleepy-mccarthy-99z4sl`,
which is merged to `main`. Everything was tested in a cloud container with no access to the home network.
**Nothing here has been deployed, and nothing has been tested on real hardware or against the real AI endpoint.**
That is your job.

Infrastructure (from the brief): PantryNanny CT `10.0.10.163`, app port `8734`, public URL https://pantry.tdgs.org
behind Traefik `10.0.10.60`, Proxmox `root@10.0.10.73`, AI endpoint `http://10.0.10.23:8080/v1`.

Ground rules (from the brief, still binding):
- Do not overwrite the database or destroy inventory.
- Do not touch other Proxmox containers.
- Do not change Traefik or WireGuard unless asked.
- Do not commit secrets.
- If a deploy fails, restore the last working version.

## 1. Deploy

```bash
git pull                      # main
deployment/deploy.sh          # target from deployment/site.env, builds web + APK (ANDROID_HOME set)
```

`install.sh` now runs `pg_dump -Fc` **before** migrations. The dump goes to `/var/backups/pantrynanny/pre-deploy/<time>-<release>/`
with a `SHA256SUMS` file, and the dump is checked with `pg_restore --list`. If the dump fails, nothing is changed.
The installer's health check rolls back the code on failure.

Migrations in this release, all additive (new tables or nullable/defaulted columns):

| Rev | Change |
|---|---|
| 0005 | `app_settings` (AI settings edited in the UI) |
| 0006 | `products.favorite` (default false) |
| 0007 | `recipes`, `recipe_ingredients`, `meal_plan_entries` |
| 0008 | `shopping_items.store` (nullable) |

Verify after deploy:
- [ ] A new directory exists under `/var/backups/pantrynanny/pre-deploy/` and `sha256sum -c SHA256SUMS` passes in it.
- [ ] `curl -s http://10.0.10.163:8734/api/health` returns `"status":"ok"`.
- [ ] Inventory counts are unchanged (compare a few products before and after).
- [ ] New pages load: `/kitchen`, `/recipes`, `/plan`, `/activity`, Admin › AI.
- [ ] Emergency restore (only if needed): `deployment/scripts/restore.sh <pre-deploy dir>`. It asks for confirmation.

## 2. AI endpoint ("it doesn't seem to get a response")

Root-cause hypothesis, **not yet confirmed**: llama.cpp serving a thinking model spends the token budget in
`reasoning_content` and returns empty `content`, or a vision request exceeds the 90 s timeout. The client now:
- strips `<think>` blocks;
- retries an empty answer once with `chat_template_kwargs: {enable_thinking: false}` and a larger budget;
- reports timeouts and empty answers with an actionable message.

Steps:
1. Admin › AI: set the base URL to `http://10.0.10.23:8080/v1`, then **Test connection**. The test reports the model
   list, a text answer (with `finish_reason` and reasoning size) and a vision check (red/blue test image).
2. If text is empty or slow, turn on **Disable thinking** and/or raise **Timeout** (180 s) and **Max tokens**
   (e.g. 4096), then test again. Save the values that work.
3. Try the assistant: ask "Hvad kan vi lave?" (should call `what_can_we_cook`), and "Sæt mælk på indkøbslisten"
   (should show a confirm button, and only add the item after the tap).
4. Write down which model and settings work in this file.

## 3. Real-device checks (none were done: do not claim them until done)

- [ ] **Hand scanner**: pair a Bluetooth scanner in keyboard (HID) mode with the iPad and with a desktop browser. On
  `/scan`, scanning must register once. Typing in Settings or search fields must not. If the scanner is slower than
  ~40 ms per character, tune `maxAvgGapMs` in `web/src/scan/hid.ts` (default 40) and report the scanner model.
- [ ] Camera-off mode (Settings › Scanner) on the iPad with only the hand scanner.
- [ ] `+5` button and the session summary on the iPad (Leave scanner → summary → Done).
- [ ] `/kitchen` on a tablet: wake lock, dim mode, a "took one" tap and undo.
- [ ] Android shortcuts: long-press the launcher icon → Scan in / Scan out (scanner opens in that mode) / Shopping list
  (opens the web list).
- [ ] Recipe import from a few real Danish sites (e.g. valdemarsro.dk, arla.dk). Sites without JSON-LD give a clear
  "no recipe data" message. That is expected.
- [ ] "Cook this" on a real recipe: check that the amounts make sense, then undo.

## 4. Obtainium / signed releases

`.github/workflows/android.yml` publishes `android-v0.1.<n>` releases from `main` once these repository secrets exist:
`ANDROID_KEYSTORE_BASE64`, `ANDROID_KEYSTORE_PASSWORD`, `ANDROID_KEY_ALIAS`, `ANDROID_KEY_PASSWORD`. Without them, the
release step is skipped (CI is still green). Use the same keystore as local `deploy.sh` builds, or Android will refuse
to update across the two.

## 5. Not done from the brief (honest list)

Implemented: the scanning upgrades, kitchen mode, recipes, meal plan, run-out forecasts, activity timeline, shops on
the shopping list, AI settings/test, grounded AI with confirmed proposals, and Android shortcuts. Not implemented or
only partial:

- Receipt import, price tracking, supermarket integrations.
- Notifications (push/e-mail digests); Home Assistant beyond the existing summary endpoint.
- Android widgets and an Android shopping screen (the shortcut opens the web list); voice input; QR/NFC location labels.
- Product equivalence/synonym management UI and a product-quality dashboard. Recipe matching uses a built-in
  synonym table plus product aliases.
- Waste tracking (FEFO is shown via expiry and the use-first lists, but there are no waste statistics); leftovers.
- Partial-package UI beyond fractional quantities (cooking deducts e.g. 0.2 of a carton, which the inventory supports).
- Offline support for recipes and the meal plan: they are online-only. Scanning, kitchen taps and cooking deductions
  use the offline op queue.
- Dashboard customisation and personalisation settings.

## 6. Test status at handover

| Suite | Result |
|---|---|
| Backend `uv run pytest` (real PostgreSQL) | 279 passed |
| Web unit `npm test` | 132 passed |
| Web e2e against a real backend (Chromium, desktop + phone) | 21 passed, 3 skipped (scanner specs desktop-only) |
| Android CI (unit tests, debug APK, lint) | green on commit 85d8002 |
