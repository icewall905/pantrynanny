#!/usr/bin/env bash
# PantryNanny installer / updater. Runs as root INSIDE the container.
#
#   install.sh <release-dir>
#
# <release-dir> is an unpacked release (backend/, web/ (built), deployment/, requirements.txt).
# Idempotent: safe to run repeatedly. Never overwrites existing secrets or data.
set -euo pipefail

RELEASE_DIR="$(readlink -f "${1:?usage: install.sh <release-dir>}")"
APP_ROOT=/opt/pantrynanny
ETC=/etc/pantrynanny
ENV_FILE=$ETC/pantrynanny.env
DATA=/var/lib/pantrynanny
BACKUPS=/var/backups/pantrynanny
LISTEN_PORT=8734
KEEP_RELEASES=3

log() { printf '\033[1;32m[pantrynanny]\033[0m %s\n' "$*"; }
die() { printf '\033[1;31m[pantrynanny] ERROR:\033[0m %s\n' "$*" >&2; exit 1; }

[[ $EUID -eq 0 ]] || die "must run as root"
[[ -d $RELEASE_DIR/backend && -d $RELEASE_DIR/web ]] || die "$RELEASE_DIR is not a release dir"

# --- 1. OS packages ------------------------------------------------------------
PKGS=(postgresql nginx python3 python3-venv curl ca-certificates jq rsync wireguard-tools)
missing=()
for p in "${PKGS[@]}"; do dpkg -s "$p" >/dev/null 2>&1 || missing+=("$p"); done
if ((${#missing[@]})); then
  log "installing packages: ${missing[*]}"
  DEBIAN_FRONTEND=noninteractive apt-get update -qq
  DEBIAN_FRONTEND=noninteractive apt-get install -y -qq "${missing[@]}"
fi
systemctl enable --now postgresql >/dev/null

# --- 2. user & directories -------------------------------------------------------
id pantrynanny >/dev/null 2>&1 || useradd --system --home-dir $DATA --shell /usr/sbin/nologin pantrynanny
install -d -m 0755 $APP_ROOT $APP_ROOT/releases
install -d -m 0750 -o root -g pantrynanny $ETC
# $DATA is traversable (0751) and uploads world-readable (0755) so nginx (www-data) can serve
# /api/media/ directly; nothing secret lives here (secrets are in /etc/pantrynanny, 0640 root:pantrynanny).
install -d -m 0751 -o pantrynanny -g pantrynanny $DATA
install -d -m 0755 -o pantrynanny -g pantrynanny $DATA/uploads
install -d -m 0700 -o postgres -g postgres $BACKUPS
chown root:root "$RELEASE_DIR"
chmod -R u=rwX,go=rX "$RELEASE_DIR"   # mktemp-based release tarballs carry a 0700 root dir

# --- 3. configuration (created once, never overwritten) --------------------------
if [[ ! -f $ENV_FILE ]]; then
  log "creating $ENV_FILE with a generated database password"
  dbpw="$(head -c 32 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c 32)"
  sed -e "s#^PN_DATABASE_URL=.*#PN_DATABASE_URL=postgresql+asyncpg://pantrynanny:${dbpw}@127.0.0.1:5432/pantrynanny#" \
      -e "s#^PN_UPLOAD_DIR=.*#PN_UPLOAD_DIR=$DATA/uploads#" \
      "$RELEASE_DIR/.env.example" > "$ENV_FILE"
fi
chown root:pantrynanny $ENV_FILE
chmod 0640 $ENV_FILE
# shellcheck disable=SC1090
set -a; . "$ENV_FILE"; set +a

# --- 4. PostgreSQL role/database (local only) ------------------------------------
DB_PW="$(sed -E 's#^.*://[^:]+:([^@]+)@.*$#\1#' <<<"$PN_DATABASE_URL")"
DB_NAME="$(sed -E 's#^.*/([^/?]+)(\?.*)?$#\1#' <<<"$PN_DATABASE_URL")"
DB_USER="$(sed -E 's#^.*://([^:]+):.*$#\1#' <<<"$PN_DATABASE_URL")"
psql_su() { runuser -u postgres -- psql -v ON_ERROR_STOP=1 -qtA "$@"; }
if [[ "$(psql_su -c "SELECT 1 FROM pg_roles WHERE rolname='$DB_USER'")" != 1 ]]; then
  log "creating database role $DB_USER"
  psql_su -c "CREATE ROLE \"$DB_USER\" LOGIN"
fi
psql_su -c "ALTER ROLE \"$DB_USER\" WITH LOGIN PASSWORD '$DB_PW'" >/dev/null
if [[ "$(psql_su -c "SELECT 1 FROM pg_database WHERE datname='$DB_NAME'")" != 1 ]]; then
  log "creating database $DB_NAME"
  psql_su -c "CREATE DATABASE \"$DB_NAME\" OWNER \"$DB_USER\" ENCODING 'UTF8' TEMPLATE template0"
fi
psql_su -d "$DB_NAME" -c "CREATE EXTENSION IF NOT EXISTS pg_trgm; CREATE EXTENSION IF NOT EXISTS unaccent; CREATE EXTENSION IF NOT EXISTS pgcrypto;"
# Postgres must only listen locally.
PGCONF="$(runuser -u postgres -- psql -qtA -c 'SHOW config_file')"
if ! grep -qE "^listen_addresses\s*=\s*'localhost'" "$PGCONF"; then
  sed -i -E "s/^#?listen_addresses\s*=.*/listen_addresses = 'localhost'/" "$PGCONF"
  systemctl restart postgresql
fi

# --- 5. Python environment for this release --------------------------------------
if [[ ! -x $RELEASE_DIR/venv/bin/uvicorn ]]; then
  log "building virtualenv"
  python3 -m venv "$RELEASE_DIR/venv"
  "$RELEASE_DIR/venv/bin/pip" install -q --upgrade pip
  "$RELEASE_DIR/venv/bin/pip" install -q --require-hashes -r "$RELEASE_DIR/requirements.txt"
  "$RELEASE_DIR/venv/bin/pip" install -q --no-deps "$RELEASE_DIR/backend"
fi

# --- 6. migrate, activate, (re)start ---------------------------------------------
# Safety net: every deploy dumps the database before migrating (kept: last 10). A deploy whose
# dump fails stops here, before any schema change. Restore: deployment/scripts/restore.sh <dir>.
PRE_DIR=$BACKUPS/pre-deploy
pre="$PRE_DIR/$(date +%Y%m%d-%H%M%S)-$(basename "$RELEASE_DIR")"
install -d -m 0700 "$PRE_DIR" "$pre"
log "backing up database before migrations -> $pre"
runuser -u postgres -- pg_dump -Fc --no-owner --no-acl -d "$DB_NAME" >"$pre/pantrynanny.dump" \
  || die "pre-deploy database backup failed; nothing was changed"
runuser -u postgres -- pg_restore --list <"$pre/pantrynanny.dump" >/dev/null || die "pre-deploy backup is unreadable"
(cd "$pre" && sha256sum pantrynanny.dump >SHA256SUMS)
find "$PRE_DIR" -mindepth 1 -maxdepth 1 -type d -print0 | sort -z | head -z -n -10 | xargs -0 -r rm -rf

log "running database migrations"
runuser -u pantrynanny -- bash -c "cd '$RELEASE_DIR/backend' && set -a && . '$ENV_FILE' && set +a && exec '$RELEASE_DIR/venv/bin/alembic' -c alembic.ini upgrade head"
log "importing the open-data seed catalogue (skipped when unchanged)"
runuser -u pantrynanny -- bash -c "cd '$RELEASE_DIR/backend' && set -a && . '$ENV_FILE' && set +a && exec '$RELEASE_DIR/venv/bin/pantrynanny-admin' import-seed --if-changed" || log "WARNING: seed catalogue import failed (non-fatal); retry: pantrynanny-admin import-seed"

PREVIOUS="$(readlink -f $APP_ROOT/current 2>/dev/null || true)"
# A release built without the Android SDK carries no APK: keep offering the previous one.
if [[ ! -f $RELEASE_DIR/web/downloads/pantrynanny.apk && -n $PREVIOUS && -f $PREVIOUS/web/downloads/pantrynanny.apk ]]; then
  log "no Android APK in this release: keeping the previous one"
  install -d -m 0755 "$RELEASE_DIR/web/downloads"
  cp -p "$PREVIOUS/web/downloads/pantrynanny.apk" "$RELEASE_DIR/web/downloads/"
  [[ -f $PREVIOUS/web/downloads/android.json ]] && cp -p "$PREVIOUS/web/downloads/android.json" "$RELEASE_DIR/web/downloads/"
fi
# Tabs still running the previous build lazy-load hashed chunks from /assets/. Carry recent ones
# (<=14 days; cp -p keeps the mtime so they age out and growth stays bounded) into the new release.
if [[ -n $PREVIOUS && -d $PREVIOUS/web/assets && $PREVIOUS != "$RELEASE_DIR" ]]; then
  find "$PREVIOUS/web/assets" -maxdepth 1 -type f -mtime -14 -exec cp -n -p -t "$RELEASE_DIR/web/assets/" {} + 2>/dev/null || true
fi
ln -sfn "$RELEASE_DIR" $APP_ROOT/current.new && mv -T $APP_ROOT/current.new $APP_ROOT/current

# nginx
TRUSTED="${PN_TRUSTED_PROXIES:-127.0.0.1}"
real_ip_lines=""; geo_lines=""
IFS=',' read -ra proxies <<<"$TRUSTED"
for p in "${proxies[@]}"; do
  p="$(echo "$p" | xargs)"; [[ -z $p ]] && continue
  real_ip_lines+="set_real_ip_from $p;"$'\n'
  geo_lines+="    $p 1;"$'\n'
done
install -m 0644 "$RELEASE_DIR/deployment/nginx/pantrynanny-headers.conf" /etc/nginx/snippets/pantrynanny-headers.conf
python3 - "$RELEASE_DIR/deployment/nginx/pantrynanny.conf.template" "$real_ip_lines" "$geo_lines" >/etc/nginx/sites-available/pantrynanny.conf <<'PY'
import sys
t = open(sys.argv[1]).read()
print(t.replace('@@REAL_IP_FROM@@', sys.argv[2].rstrip()).replace('@@GEO_TRUSTED@@', sys.argv[3].rstrip()))
PY
ln -sfn /etc/nginx/sites-available/pantrynanny.conf /etc/nginx/sites-enabled/pantrynanny.conf
rm -f /etc/nginx/sites-enabled/default
nginx -t -q

# Admin CLI wrapper: runs as the service user with the production environment.
cat >/usr/local/sbin/pantrynanny-admin <<'WRAP'
#!/usr/bin/env bash
# Usage: pantrynanny-admin <command> [...]   (see --help)
set -euo pipefail
cd /opt/pantrynanny/current/backend
exec runuser -u pantrynanny -- bash -c 'set -a; . /etc/pantrynanny/pantrynanny.env; set +a; exec /opt/pantrynanny/current/venv/bin/pantrynanny-admin "$@"' pantrynanny-admin "$@"
WRAP
chmod 0755 /usr/local/sbin/pantrynanny-admin

# systemd units
for u in "$RELEASE_DIR"/deployment/systemd/*; do install -m 0644 "$u" /etc/systemd/system/; done
chmod 0755 "$RELEASE_DIR"/deployment/scripts/*.sh
systemctl daemon-reload
systemctl enable -q pantrynanny-api pantrynanny-worker pantrynanny-backup.timer pantrynanny-healthcheck.timer nginx
# The periodic health check would count the restart below as a failure: pause it until the
# new release answers (it is started again in every outcome further down).
systemctl stop pantrynanny-healthcheck.timer 2>/dev/null || true
systemctl reload-or-restart nginx
systemctl restart pantrynanny-api pantrynanny-worker
systemctl start pantrynanny-backup.timer

# --- 7. verify, roll back on failure ----------------------------------------------
log "waiting for health check"
ok=0
for _ in $(seq 1 30); do
  if curl -fsS "http://127.0.0.1:$LISTEN_PORT/api/health" >/dev/null 2>&1; then ok=1; break; fi
  sleep 1
done
if ((ok == 0)); then
  if [[ -n $PREVIOUS && -d $PREVIOUS && $PREVIOUS != "$RELEASE_DIR" ]]; then
    log "health check FAILED – rolling back to $PREVIOUS"
    ln -sfn "$PREVIOUS" $APP_ROOT/current.new && mv -T $APP_ROOT/current.new $APP_ROOT/current
    systemctl restart pantrynanny-api pantrynanny-worker
  fi
  systemctl start pantrynanny-healthcheck.timer || true
  journalctl -u pantrynanny-api -n 40 --no-pager || true
  die "new release did not become healthy"
fi

systemctl start pantrynanny-healthcheck.timer

# --- 8. prune old releases ---------------------------------------------------------
current="$(readlink -f $APP_ROOT/current)"
ls -1dt $APP_ROOT/releases/*/ 2>/dev/null | tail -n +$((KEEP_RELEASES + 1)) | while read -r old; do
  [[ "$(readlink -f "$old")" == "$current" ]] || rm -rf "$old"
done

log "PantryNanny $(cat "$RELEASE_DIR/RELEASE" 2>/dev/null || echo '?') is live on 0.0.0.0:$LISTEN_PORT"
curl -fsS "http://127.0.0.1:$LISTEN_PORT/api/health"; echo
