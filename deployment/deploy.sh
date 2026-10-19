#!/usr/bin/env bash
# Build a PantryNanny release on a workstation and install it into the container.
#
#   deployment/deploy.sh          # target from deployment/site.env (gitignored) or the environment
#   PN_DEPLOY_TARGET=ssh:root@pantry-host deployment/deploy.sh
#   PN_DEPLOY_TARGET=pct:root@proxmox-host:220 deployment/deploy.sh   # via Proxmox pct push/exec
#
# Requires locally: git, node/npm (22+), uv. The release contains the committed tree at HEAD
# (uncommitted changes are NOT deployed), the built web app and hashed Python requirements.
set -euo pipefail
cd "$(dirname "$0")/.."
# Site-specific settings (PN_DEPLOY_TARGET, PN_DEPLOY_SSH_OPTS) live in a gitignored file.
[[ -f deployment/site.env ]] && . deployment/site.env
TARGET="${PN_DEPLOY_TARGET:?set PN_DEPLOY_TARGET (see deployment/site.env.example)}"
SSH_OPTS=(${PN_DEPLOY_SSH_OPTS:-})

sha="$(git rev-parse --short HEAD)"
rel="$(date -u +%Y%m%d%H%M%S)-$sha"
[[ -z "$(git status --porcelain)" ]] || echo "warning: working tree has uncommitted changes; deploying HEAD ($sha)" >&2

work="$(mktemp -d)"; trap 'rm -rf "$work"' EXIT
echo "==> exporting $sha"
git archive --format=tar HEAD | tar -x -C "$work"
echo "$rel" >"$work/RELEASE"

echo "==> building web app"
(cd "$work/web" && npm ci --no-audit --no-fund --loglevel=error && npm run build --silent)
mv "$work/web" "$work/web-src" && mv "$work/web-src/dist" "$work/web" && rm -rf "$work/web-src"

echo "==> exporting Python requirements"
(cd "$work/backend" && uv export --frozen --no-dev --no-emit-project --format requirements-txt -o ../requirements.txt -q)
# Android APK, served by the web app at /downloads/pantrynanny.apk (+ android.json with the version).
# Built from the same exported commit. Needs the Android SDK locally (ANDROID_HOME/ANDROID_SDK_ROOT or
# android/local.properties); signed release when android/keystore.properties exists, else debug.
# PN_DEPLOY_APK=0 skips it; without an APK the installer keeps serving the previous release's one.
build_apk() {
  local a="$work/android" variant code name apk sum
  if [[ -z "${ANDROID_HOME:-}${ANDROID_SDK_ROOT:-}" && ! -f android/local.properties ]]; then
    echo "==> skipping Android APK (no Android SDK found; set ANDROID_HOME)"; return 0
  fi
  [[ -f android/local.properties ]] && cp android/local.properties "$a/"
  variant=debug
  if [[ -f android/keystore.properties ]]; then
    variant=release
    # storeFile may be relative to android/: make it absolute for the copy in $work
    awk -v base="$PWD/android" -F= '$1=="storeFile" && $2 !~ /^\// { print "storeFile=" base "/" $2; next } { print }' \
      android/keystore.properties >"$a/keystore.properties"
  fi
  code="$(git rev-list --count HEAD)"
  name="0.1.$code"
  echo "==> building Android APK ($variant, version $name)"
  (cd "$a" && chmod +x gradlew && ./gradlew --no-daemon -q "-PpnVersionCode=$code" "-PpnVersionName=$name" \
    "assemble$([[ $variant == release ]] && echo Release || echo Debug)") || { echo "warning: Android build failed; the previous APK stays online" >&2; return 0; }
  apk="$a/app/build/outputs/apk/$variant/app-$variant.apk"
  [[ -f $apk ]] || { echo "warning: no APK produced at $apk" >&2; return 0; }
  mkdir -p "$work/web/downloads"
  cp "$apk" "$work/web/downloads/pantrynanny.apk"
  sum="$( (sha256sum "$apk" 2>/dev/null || shasum -a 256 "$apk") | cut -d' ' -f1)"
  printf '{"version_name":"%s","version_code":%s,"variant":"%s","commit":"%s","built":"%s","size":%s,"sha256":"%s"}\n' \
    "$name$([[ $variant == debug ]] && echo -debug)" "$code" "$variant" "$sha" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    "$(wc -c <"$apk" | tr -d ' ')" "$sum" >"$work/web/downloads/android.json"
}
[[ "${PN_DEPLOY_APK:-1}" == 0 ]] || build_apk
rm -rf "$work/android"
tarball="$work.tar.gz"; trap 'rm -rf "$work" "$tarball"' EXIT
tar -C "$work" -czf "$tarball" .
echo "==> release $rel ($(du -h "$tarball" | cut -f1))"

remote_install="set -e; d=/opt/pantrynanny/releases/$rel; mkdir -p \$d; tar --no-same-owner -xzf /tmp/pantrynanny-$rel.tar.gz -C \$d; rm /tmp/pantrynanny-$rel.tar.gz; bash \$d/deployment/scripts/install.sh \$d"
case "$TARGET" in
  ssh:*)
    host="${TARGET#ssh:}"
    scp "${SSH_OPTS[@]}" -q "$tarball" "$host:/tmp/pantrynanny-$rel.tar.gz"
    ssh "${SSH_OPTS[@]}" "$host" "$remote_install"
    ;;
  pct:*)
    spec="${TARGET#pct:}"; pve="${spec%:*}"; ctid="${spec##*:}"
    scp "${SSH_OPTS[@]}" -q "$tarball" "$pve:/tmp/pantrynanny-$rel.tar.gz"
    ssh "${SSH_OPTS[@]}" "$pve" "pct push $ctid /tmp/pantrynanny-$rel.tar.gz /tmp/pantrynanny-$rel.tar.gz && rm /tmp/pantrynanny-$rel.tar.gz && pct exec $ctid -- bash -c '$remote_install'"
    ;;
  *) echo "unknown PN_DEPLOY_TARGET $TARGET"; exit 2;;
esac
echo "==> deployed $rel"
