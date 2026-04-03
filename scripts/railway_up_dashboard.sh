#!/bin/bash
# Railway CLI deploy für gifhorn-dashboard: Nixpacks liest root railway.json —
# kurz auf railway-dashboard.json (Uvicorn) umschalten, dann zurück.
set -euo pipefail
if [ -x /opt/homebrew/bin/railway ]; then RAILWAY=/opt/homebrew/bin/railway
elif [ -x /usr/local/bin/railway ]; then RAILWAY=/usr/local/bin/railway
elif PATH_CMD="$(type -P railway 2>/dev/null || true)" && [ -n "$PATH_CMD" ]; then RAILWAY=$PATH_CMD
else
  echo "railway: kein ausführbares Binary gefunden (Homebrew-Pfad prüfen; Zsh-Funktion 'railway' entfernen)." >&2
  exit 1
fi
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
WORKER_JSON="$ROOT/railway.json"
DASH_JSON="$ROOT/railway-dashboard.json"
BAK="$(mktemp)"
trap 'mv -f "$BAK" "$WORKER_JSON"' EXIT
cp "$WORKER_JSON" "$BAK"
cp "$DASH_JSON" "$WORKER_JSON"
MSG="${1:-dashboard deploy}"
MSG="${MSG:0:100}"
"$RAILWAY" up -s gifhorn-dashboard -c -m "$MSG"
