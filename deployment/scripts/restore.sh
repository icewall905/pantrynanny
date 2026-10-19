#!/usr/bin/env bash
# Restore a PantryNanny backup created by backup.sh.
#
#   restore.sh <backup-dir> [--target-db NAME] [--yes]
#
# Without --target-db the live database is replaced (services are stopped first).
# With --target-db a separate database is created for verification (services untouched).
set -euo pipefail
SRC="${1:?usage: restore.sh <backup-dir> [--target-db NAME] [--yes]}"; shift
TARGET=""; YES=0
while (($#)); do case $1 in --target-db) TARGET=$2; shift 2;; --yes) YES=1; shift;; *) echo "unknown arg $1"; exit 2;; esac; done
set -a; . /etc/pantrynanny/pantrynanny.env; set +a
LIVE_DB="$(sed -E 's#^.*/([^/?]+)(\?.*)?$#\1#' <<<"$PN_DATABASE_URL")"
DB_USER="$(sed -E 's#^.*://([^:]+):.*$#\1#' <<<"$PN_DATABASE_URL")"
(cd "$SRC" && sha256sum -c --quiet SHA256SUMS)
psql_su() { runuser -u postgres -- psql -v ON_ERROR_STOP=1 -qtA "$@"; }

if [[ -n $TARGET ]]; then
  [[ $TARGET != "$LIVE_DB" ]] || { echo "target equals live DB; omit --target-db instead"; exit 2; }
  psql_su -c "DROP DATABASE IF EXISTS \"$TARGET\""
  psql_su -c "CREATE DATABASE \"$TARGET\" OWNER \"$DB_USER\" TEMPLATE template0 ENCODING 'UTF8'"
  runuser -u postgres -- pg_restore --no-owner --role="$DB_USER" -d "$TARGET" <"$SRC/pantrynanny.dump"
  echo "restored into $TARGET"
  exit 0
fi

if ((YES == 0)); then
  read -r -p "This REPLACES the live PantryNanny database and uploads. Type 'restore' to continue: " a
  [[ $a == restore ]] || exit 1
fi
systemctl stop pantrynanny-api pantrynanny-worker
psql_su -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='$LIVE_DB' AND pid<>pg_backend_pid()" >/dev/null
psql_su -c "DROP DATABASE IF EXISTS \"$LIVE_DB\""
psql_su -c "CREATE DATABASE \"$LIVE_DB\" OWNER \"$DB_USER\" TEMPLATE template0 ENCODING 'UTF8'"
runuser -u postgres -- pg_restore --no-owner --role="$DB_USER" -d "$LIVE_DB" <"$SRC/pantrynanny.dump"
if [[ -f $SRC/uploads.tar.gz ]]; then
  rm -rf /var/lib/pantrynanny/uploads.restore-old
  [[ -d /var/lib/pantrynanny/uploads ]] && mv /var/lib/pantrynanny/uploads /var/lib/pantrynanny/uploads.restore-old
  tar -C /var/lib/pantrynanny -xzf "$SRC/uploads.tar.gz"
  chown -R pantrynanny:pantrynanny /var/lib/pantrynanny/uploads
fi
systemctl start pantrynanny-api pantrynanny-worker
sleep 3
curl -fsS http://127.0.0.1:8734/api/health && echo && echo "restore complete"
