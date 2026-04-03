#!/usr/bin/env bash
# Railway CLI deploy für gifhorn-worker. Root railway.json wird kurz auf Worker-Start ersetzt.
set -euo pipefail
if [ -x /opt/homebrew/bin/railway ]; then RAILWAY=/opt/homebrew/bin/railway
elif [ -x /usr/local/bin/railway ]; then RAILWAY=/usr/local/bin/railway
else RAILWAY=railway; fi
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
DEFAULT_JSON="$ROOT/railway.json"
WORKER_JSON="$ROOT/railway-worker.json"
BAK="$(mktemp)"
trap 'mv "$BAK" "$DEFAULT_JSON"' EXIT
cp "$DEFAULT_JSON" "$BAK"
cp "$WORKER_JSON" "$DEFAULT_JSON"
"$RAILWAY" up -s gifhorn-worker -c -m "${1:-worker: cron post}"
