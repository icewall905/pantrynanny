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
* Unknown barcodes are still queued (the server creates a placeholder) and scanning continues.
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

To sign in CI, store the keystore (base64) and passwords as GitHub Actions secrets, write them to
`keystore.properties` and the keystore file in a workflow step, and run `assembleRelease`. The shipped
workflow only builds the debug APK so that it needs no secrets.

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
