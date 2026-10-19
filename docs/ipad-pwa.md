# iPad / iPadOS Safari scanning station

Findings for the wall-mounted iPad (`/scan`), plus the setup guide. Research date 2026-10-19. Items marked
**verify on device** could not be confirmed from documentation alone and must be tested on the real iPad
(iPadOS version, model and camera differ).

## 1. Platform findings

| Capability | iPadOS Safari status | What PantryNanny does |
|---|---|---|
| `getUserMedia` in a standalone Home-Screen PWA | Works on iOS/iPadOS 13.4+ in standalone mode (earlier versions only worked in the Safari tab). Needs HTTPS (secure context) and a user-visible permission grant; Safari re-asks per origin/session unless "Allow" is chosen under Website Settings. Standalone apps keep their own permission state, so the first launch from the Home Screen prompts again. Camera is killed when the app is backgrounded/locked. | `Camera.open()` uses `facingMode: {ideal:'environment'}` 1280x720; re-opens the stream on `visibilitychange`/`pageshow`, when the track ends, and when no video frames arrive for 4 s (watchdog). `muted` + `playsinline` + `autoplay` on the `<video>`. |
| `BarcodeDetector` | **Not available** in Safari or any iOS browser (all use WebKit). Shape Detection exists only behind a Technical-Preview flag and is reported broken in iOS 18. ([Apple dev forum](https://developer.apple.com/forums/thread/767761), [overview](https://eringen.substack.com/p/barcode-scanning-on-ios-the-missing)) | Feature-detected: native detector only if `getSupportedFormats()` contains `ean_13`; otherwise ZXing. On the iPad this means **ZXing always**. |
| Decoder choice | `@zxing/library` `MultiFormatReader`, formats restricted to EAN-13/EAN-8/UPC-A/UPC-E/Code 128/ITF, TRY_HARDER off (on for every 4th frame to catch rotated codes). Runs in a module Web Worker (Safari 15+) fed with a downscaled (≤800 px) centre-crop luminance buffer at ~12 fps; falls back to the main thread if the worker fails. | Measured in headless Chromium: ~3 ms decode per frame in the worker; UI latency 25-90 ms. **Verify on device** (iPad CPU/thermal behaviour over hours). |
| Screen Wake Lock | Safari 16.4+ in the browser. In installed Home-Screen web apps it did **not** work until iOS 18.4 ([WebKit bug 254545](https://bugs.webkit.org/show_bug.cgi?id=254545), [summary](https://progressier.com/pwa-capabilities/screen-wake-lock)). The lock is released when the page is hidden and may be refused on low battery. | Acquired on the "Start scanning" tap, re-acquired on `visibilitychange`. If unsupported/failed an on-screen hint recommends Auto-Lock "Never". **The documented fallback (Auto-Lock Never + Guided Access) is the primary mechanism, the wake lock is a bonus.** |
| Torch / `ImageCapture` / `focusMode` | iOS Safari exposes neither `torch` nor `focusMode` capabilities (`getCapabilities()` is sparse or empty); autofocus is continuous by default in the system camera pipeline. Torch is Chromium-on-Android only. | Feature-detected through `getCapabilities()`: continuous focus is applied and the torch button is shown only when supported (so it is hidden on iPad). |
| `AudioContext` | Starts `suspended`; may only be resumed from a user gesture. WebKit also uses a non-standard `interrupted` state (phone call, Siren, app switch, lock) that does **not** recover on its own. The hardware silent switch does not mute Web Audio on iPad but media volume does. | One `AudioContext` is created and resumed inside the "Start scanning" tap (plus a silent blip). Because `state !== 'running'` is treated as "needs resume" (covers `suspended` and `interrupted`), `beep()` retries on every beep, `visibilitychange` re-resumes, and passive document `pointerdown`/`touchend` listeners call `unlockAudio()` again. After an automatic resume (see below) sound starts at the next touch. Distinct tones: rising = add, falling = remove, low double square = unknown, long low = error. |
| `navigator.vibrate` | Not implemented on iOS/iPadOS. | Called behind a feature check (no-op on iPad); visual + audio feedback carry the confirmation. |
| Service worker / Background Sync | SW works in standalone and Safari; **no Background Sync / Periodic Sync**; a SW is not kept alive in the background. Storage can be evicted after ~7 days of non-use in the Safari tab, but not for installed Home-Screen apps. | Sync is entirely foreground-driven (online event, visibility, 30 s push, 60 s pull). Background Sync is registered only where present. `navigator.storage.persist()` is requested once. |
| Orientation | `screen.orientation.lock()` is not supported on iPad Safari. | Layout adapts to landscape and portrait; the manifest says `orientation: any`. |

Sources: MDN Screen Wake Lock / Barcode Detection pages, WebKit bugs linked above, Apple Developer Forums. MDN's
compatibility tables could not be fetched in this session, so the version numbers above for getUserMedia-in-standalone
come from prior knowledge of WebKit release notes (13.4) - **verify on device**.

## 2. Wall-mount setup guide

### One-time iPad setup

1. **Update** iPadOS (18.4 or later strongly preferred for the Wake Lock fix).
2. Open `https://<your-pantrynanny-host>/scan` in **Safari** (HTTPS is mandatory for the camera).
3. **Install**: Share button › *Add to Home Screen* › *Open as Web App* on › *Add*. Launch PantryNanny from the Home
   Screen icon (standalone, no browser chrome).
4. **Camera permission**: tap *Start scanning* and choose *Allow*. If you previously denied it: Settings › Apps › Safari
   › Camera › Ask/Allow (or `aA` › Website Settings › Camera › Allow while in Safari). For the Home-Screen app you may
   need to delete and re-add the icon after changing the setting.
5. **Keep the screen on**: Settings › Display & Brightness › Auto-Lock › **Never** (only while charging - see below).
6. **Brightness**: set manually (about 50-70 %) and disable *Auto-Brightness* (Settings › Accessibility › Display & Text
   Size) so the bright, tinted ADD/REMOVE screen is not dimmed in a dark kitchen.
7. **Do Not Disturb / Focus**: enable a Focus that silences notifications; banners would otherwise cover the screen.
8. **Sound**: set the media volume; the app's beeps use Web Audio (follows media volume).
9. **Guided Access** (locks the iPad into PantryNanny, prevents leaving by accident): Settings › Accessibility › Guided
   Access › On, set a passcode, enable *Accessibility Shortcut* (triple-click Side/Home button). Open PantryNanny, triple-click,
   *Options*: disable Touch only if you want to block taps entirely (the ADD/REMOVE control needs touch), keep the
   Side button off, set *Time Limit* off, then *Start*.
10. Keep the iPad **on its charger** permanently (Auto-Lock Never + screen on drains the battery quickly). Enable
    *Optimised Battery Charging* so the battery is not held at 100 % all day.

### Kiosk pairing (no repeated logins)

1. An admin opens PantryNanny › Indstillinger › Enheder › *Ny scanner-kode* (`POST /api/devices/kiosk-codes`). An 8-character
   code is shown, valid for 15 minutes, single use.
2. On the iPad open `/scan`; enter the code (or sign in with a user and "remember", 180 days). The server sets a 365-day
   `pn_session` cookie bound to a *kiosk* principal that can only scan, read products/stock and upload sync ops.
3. Tap **Start scanning** once. From then on no further taps are needed for recognised products.
4. Revoke a lost/changed iPad under Indstillinger › Enheder (`DELETE /api/devices/{id}`).

### Mounting angle and lighting

* Mount the iPad about 120-140 cm above the floor (eye/chest height), tilted 10-20 degrees back so glare from ceiling lights does
  not reflect into the lens; items are presented to the screen at about 15-25 cm distance.
* The **rear** camera is used (autofocus, higher resolution), so mount the iPad with a small standoff from the wall
  (arm, stand or bracket with a gap) so the lens at the back is free and looks at the area where items are held.
  A tablet mounted flat against the wall blocks the rear camera.
* Even, diffuse light (no strong light straight behind the item). Avoid a window directly behind the scanning area.
* Present the barcode flat, bars vertical or horizontal, inside the framed rectangle, about 15-25 cm from the lens; hold for ~0.3 s.
* Matte/dark background behind the scan area improves contrast.

#### Known limitation: rear camera only

The scanner requests `facingMode: environment`. If the browser reports only a front camera it will be used, but there is
no front/rear toggle and front cameras focus poorly at 15-25 cm. **Verify on device** which camera and field of view suit
your mount.

## 3. Safety behaviours implemented

* REMOVE mode reverts to ADD after `remove_mode_timeout_min` (default 10) idle minutes and on every page reload.
* Mode switch clears the duplicate-suppression state (an item still in view is not counted twice in the new mode).
* Whole-screen tint (green = ADD, tomato = REMOVE), giant label and segmented control.
* A scan is only confirmed (beep, card) after it was written to IndexedDB; if that write fails the user gets an error
  tone and a red toast that stays until tapped. A dead IndexedDB connection is reopened and the operation retried once.
* Undo: a scan that was **never uploaded** is removed from the queue. As soon as an upload was attempted (even if the
  response was lost) the server may have applied it, so undo sends a compensating `undo` op instead. Both choices are
  made atomically with the "sent" marker.
* Rejected ops are never dropped: they are listed in the red "afvist" banner (retry or dismiss; an op whose scan was
  undone meanwhile is not resurrected).
* Logging out keeps unsent ops for the same household. Signing in to a **different household** deletes all local data
  including unsent scans of the previous household (they would be applied to the wrong stock); the Start screen shows
  a warning with the number of discarded scans.

## 4. Hidden debug overlay

Tap the connection pill 5 times: shows decoder (`zxing-worker`, `zxing-main`, `native`), fps, decode ms,
frame→UI latency of recent scans and the number of pending ops.

## 5. Reloads and auto-resume

After a service-worker update (hourly `registration.update()`) the page reloads. If scanning was active and
`navigator.permissions.query({name:'camera'})` reports `granted`, `/scan` goes straight back to scanning (camera, no
tap). Audio and the wake lock need a user gesture on iOS, so they come back on the first touch. If Safari does not
support the camera permission query, the Start screen is shown and one tap is needed. **Verify on device.**
