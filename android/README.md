# PantryNanny for Android

Native Kotlin / Jetpack Compose client for the PantryNanny household inventory server.
It is built around fast, offline-first barcode scanning (CameraX + ML Kit) with a Room
database and a persistent operation queue that is synchronised in the background.

* Package: `dk.pantrynanny.app`, min SDK 26 (Android 8.0), compile/target SDK 37
* Default language Danish (`values/`), English in `values-en/`
* API contract: [`../docs/api-contract.md`](../docs/api-contract.md)

## Build

Requirements: JDK 17 or newer (21 recommended) and the Android SDK (Android Studio installs both).

```sh
cd android
./gradlew testDebugUnitTest      # JVM unit tests
./gradlew assembleDebug          # app/build/outputs/apk/debug/app-debug.apk
./gradlew lintDebug              # lint (non-fatal)
```

Or open the `android/` directory in Android Studio (latest stable) and press Run.
The Gradle wrapper is pinned (Gradle 9.6.1); dependency versions live in `gradle/libs.versions.toml`.

The debug build uses the application id `dk.pantrynanny.app.debug` so it can be installed next to a
release build. Debug builds allow cleartext `http://` server URLs (for LAN testing); release builds
require `https://`.

## CI build artefact

`.github/workflows/android.yml` runs unit tests, builds the debug APK and runs lint on every push / PR
that touches `android/**` (and on manual dispatch). Download the APK from the workflow run page under
**Artifacts -> `pantrynanny-debug-apk`**. Test and lint reports are uploaded as well when something fails.

## Install

The easiest way: open the web app on the phone, then **Indstillinger -> Android-app -> Hent APK** (also
linked from the login page). `deployment/deploy.sh` builds that APK from the deployed commit when the
Android SDK is available on the deploying machine (signed release if `keystore.properties` exists,
otherwise debug) and gives it an increasing `versionCode`, so a new download installs as an update.
A debug and a release build have different application ids (`.debug` suffix) and install side by side.

```sh
adb install -r app-debug.apk
```

Or copy the APK to the phone and open it (allow "install unknown apps" for the file manager / browser
you use). On first launch grant the camera permission.

## Configure the server

On the login screen enter the **Server address** (e.g. `https://pantry.example.com`), your username and
password. The app exchanges them for a device token (`POST /api/auth/token`), which is stored encrypted
with an Android Keystore AES-GCM key; the password is never stored. After login a full snapshot is
downloaded; afterwards only changes are pulled. To switch server: Settings -> Log out, then log in
again with the new address. Logging out with unsynchronised operations asks for confirmation because
those operations would be lost.

For a LAN test server over plain HTTP use a debug build (`http://192.168.x.y:8000`).

## How scanning works

* Camera analysis runs on its own thread with `STRATEGY_KEEP_ONLY_LATEST` at about 1280x720; ML Kit is
  restricted to EAN-13, EAN-8, UPC-A, UPC-E, Code 128 and ITF.
* `ScanDeduplicator` implements section 4 of the API contract (a barcode held in view is counted once;
  it must be absent for `scan_rearm_ms` before it counts again; mode switches clear the state).
* A counted scan is stored in one Room transaction as a pending op plus a history row; the displayed
  quantity is `server total + sum(pending deltas)`, so the UI updates without any network call.
* Unknown barcodes are still queued and scanning continues. The server names the product from the
  bundled seed catalogue when it can, otherwise it creates a placeholder. The notice then offers
  **Registrer** (also on the last-scan card and on unknown rows in the history): it opens the product
  in edit mode with an empty name field, and saving makes the barcode known for every later scan, on
  every device. Offline, the item waits under Lager -> Ukendte varer.
* Product photos: on the product screen (and while registering) **Tag billede** uses the phone's
  camera app and **Vælg billede** the system photo picker. The image is scaled to 1600 px, rotated per
  EXIF and uploaded (`POST /api/products/{id}/photo`, needs a connection). Images show on the product
  screen, the last-scan card and in the inventory list, and are cached on disk for offline use.
* **Frontkamera / Bagkamera** (top right of the camera view, shown when the phone has both) switches
  the scanning camera; the choice is remembered. Front cameras have no torch and usually fixed focus,
  so hold items a little further away.
* Remove mode reverts to Add on a cold start and after `remove_mode_timeout_min` idle minutes.
* Sync: debounced foreground sync about 1.5 s after the last scan, a unique one-time WorkManager job
  (network constraint, exponential backoff), a 15 minute periodic job, and a trigger when connectivity
  returns. Ops are uploaded in order in batches (`POST /api/sync/ops`); `applied`/`duplicate` ops are
  removed, `rejected` ops stay visible under Settings -> Rejected operations with Retry / Delete.
  Nothing is ever dropped silently.

## Release signing

Release builds are unsigned unless a `keystore.properties` file exists next to `settings.gradle.kts`
(`android/keystore.properties`). Both the properties file and keystores are git-ignored; keep the
keystore **outside** the repository.

1. Create a keystore once and back it up somewhere safe:

   ```sh
   keytool -genkeypair -v -keystore ~/secrets/pantrynanny-release.jks \
       -alias pantrynanny -keyalg RSA -keysize 4096 -validity 10000
   ```

2. Create `android/keystore.properties` (never commit it):

   ```properties
   storeFile=/home/you/secrets/pantrynanny-release.jks
   storePassword=...
   keyAlias=pantrynanny
   keyPassword=...
   ```

   `storeFile` may be absolute or relative to `android/`.

3. Build: `./gradlew assembleRelease` -> `app/build/outputs/apk/release/app-release.apk`
   (minified with R8; keep rules for kotlinx.serialization are in `app/proguard-rules.pro`).

### GitHub Releases / Obtainium

When these four repository secrets exist, every push to `main` that touches `android/` also publishes a
signed release, `android-v0.1.<commit count>`, with `pantrynanny-0.1.<n>.apk` attached. Obtainium can
track and update from it. Without the secrets, the step is skipped and CI only builds the debug APK.

| Secret | Value |
|---|---|
| `ANDROID_KEYSTORE_BASE64` | `base64 -w0 pantrynanny-release.jks` |
| `ANDROID_KEYSTORE_PASSWORD` | keystore password |
| `ANDROID_KEY_ALIAS` | e.g. `pantrynanny` |
| `ANDROID_KEY_PASSWORD` | key password |

Use the **same** keystore in `android/keystore.properties` on the machine that runs `deployment/deploy.sh`.
Then the APK offered by the web app and the GitHub release share one signature and version numbering, so
either can update the other. Never lose the keystore: an app signed with a different key can't update
the installed one, so you would have to uninstall it (and its local queue) first.

Release builds currently ship without R8 minification (`isMinifyEnabled = false`) until a minified build
has been verified on a device.

## Project layout

```
app/src/main/java/dk/pantrynanny/app/
  PantryApp.kt            Application + AppContainer (manual DI), debounced sync trigger
  MainActivity.kt         single activity, bottom navigation (Scan / Lager / Indstillinger)
  domain/                 pure Kotlin: ScanDeduplicator, BarcodeNormalizer, QuantityMath (unit tested)
  data/local/             Room entities, DAOs, database
  data/remote/            kotlinx.serialization DTOs, OkHttp ApiClient
  data/                   SettingsStore (DataStore), TokenStore (Keystore), Scan/Sync/Inventory repositories
  sync/                   WorkManager worker + scheduler
  ui/                     Compose screens and ViewModels
app/src/test/             JVM unit tests (testDebugUnitTest)
```

## Known limitations

* Product edits (PATCH with `If-Match`) need a connection; they are not queued offline.
* No on-device verification has been done by the authors of this scaffold beyond CI: please test the
  scanner on a real device (camera, autofocus, torch, beep/vibration) before relying on it.
