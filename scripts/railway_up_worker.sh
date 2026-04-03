#!/usr/bin/env bash
# Railway CLI deploy für gifhorn-worker. Root railway.json ist das Dashboard (uvicorn);
# kurz auf railway-worker.json umschalten.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
DEFAULT_JSON="$ROOT/railway.json"
WORKER_JSON="$ROOT/railway-worker.json"
BAK="$(mktemp)"
trap 'mv "$BAK" "$DEFAULT_JSON"' EXIT
cp "$DEFAULT_JSON" "$BAK"
cp "$WORKER_JSON" "$DEFAULT_JSON"
railway up -s gifhorn-worker -c -m "${1:-worker: cron post}"
