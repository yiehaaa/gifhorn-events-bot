#!/usr/bin/env bash
# Railway CLI deploy für gifhorn-dashboard: Nixpacks liest root railway.json —
# die ist für den Worker. Kurz auf railway-dashboard.json umschalten, dann zurück.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
WORKER_JSON="$ROOT/railway.json"
DASH_JSON="$ROOT/railway-dashboard.json"
BAK="$(mktemp)"
trap 'mv "$BAK" "$WORKER_JSON"' EXIT
cp "$WORKER_JSON" "$BAK"
cp "$DASH_JSON" "$WORKER_JSON"
railway up -s gifhorn-dashboard -c -m "${1:-dashboard: uvicorn}"
