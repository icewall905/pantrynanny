#!/usr/bin/env bash
# PantryNanny backup: custom-format pg_dump + uploads tarball.
# Retention: 14 daily, 8 weekly (Sunday copies), 12 monthly (1st of month copies).
set -euo pipefail
BACKUPS=${PN_BACKUP_DIR:-/var/backups/pantrynanny}
ENV_FILE=/etc/pantrynanny/pantrynanny.env
UPLOADS=/var/lib/pantrynanny/uploads
set -a; . "$ENV_FILE"; set +a
DB_NAME="$(sed -E 's#^.*/([^/?]+)(\?.*)?$#\1#' <<<"$PN_DATABASE_URL")"

ts="$(date +%Y%m%d-%H%M%S)"
umask 077
install -d -m 0700 "$BACKUPS"/{daily,weekly,monthly}
dir="$BACKUPS/daily/$ts"
mkdir "$dir"

runuser -u postgres -- pg_dump -Fc --no-owner --no-acl -d "$DB_NAME" >"$dir/pantrynanny.dump"
tar -C "$(dirname "$UPLOADS")" -czf "$dir/uploads.tar.gz" "$(basename "$UPLOADS")"
# verify the dump is readable before trusting it
runuser -u postgres -- pg_restore --list "$dir/pantrynanny.dump" >/dev/null
tar -tzf "$dir/uploads.tar.gz" >/dev/null
(cd "$dir" && sha256sum pantrynanny.dump uploads.tar.gz >SHA256SUMS)
cp /etc/pantrynanny/pantrynanny.env "$dir/pantrynanny.env"   # contains secrets; dir is 0700 root

[[ "$(date +%u)" == 7 ]] && cp -a "$dir" "$BACKUPS/weekly/$ts"
[[ "$(date +%d)" == 01 ]] && cp -a "$dir" "$BACKUPS/monthly/$ts"

prune() { ls -1d "$1"/*/ 2>/dev/null | sort | head -n -"$2" | xargs -r rm -rf; }
prune "$BACKUPS/daily" 14
prune "$BACKUPS/weekly" 8
prune "$BACKUPS/monthly" 12

echo "backup ok: $dir ($(du -sh "$dir" | cut -f1))"
