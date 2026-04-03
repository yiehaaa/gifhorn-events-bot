#!/usr/bin/env bash
# Railway CLI deploy für gifhorn-dashboard: Nixpacks liest root railway.json —
# kurz auf railway-dashboard.json (Uvicorn) umschalten, dann zurück.
set -euo pipefail
if [ -x /opt/homebrew/bin/railway ]; then RAILWAY=/opt/homebrew/bin/railway
elif [ -x /usr/local/bin/railway ]; then RAILWAY=/usr/local/bin/railway
else RAILWAY=railway; fi
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
WORKER_JSON="$ROOT/railway.json"
DASH_JSON="$ROOT/railway-dashboard.json"
BAK="$(mktemp)"
trap 'mv "$BAK" "$WORKER_JSON"' EXIT
cp "$WORKER_JSON" "$BAK"
cp "$DASH_JSON" "$WORKER_JSON"
"$RAILWAY" up -s gifhorn-dashboard -c -m "${1:-dashboard: uvicorn}"
