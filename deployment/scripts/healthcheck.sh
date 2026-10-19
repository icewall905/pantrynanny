#!/usr/bin/env bash
# Restart the API after two consecutive failed health checks (hung process protection).
set -uo pipefail
STATE=/run/pantrynanny-healthcheck.failures
if curl -fsS -m 10 http://127.0.0.1:8734/api/health >/dev/null; then
  rm -f "$STATE"; exit 0
fi
n=$(( $(cat "$STATE" 2>/dev/null || echo 0) + 1 ))
echo "$n" >"$STATE"
echo "health check failed ($n consecutive)"
if (( n >= 2 )); then
  echo "restarting pantrynanny-api"
  systemctl restart pantrynanny-api
  rm -f "$STATE"
fi
