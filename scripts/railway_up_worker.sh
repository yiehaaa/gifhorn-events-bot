#!/bin/bash
# Railway CLI deploy für gifhorn-worker. Root railway.json wird kurz auf Worker-Start ersetzt.
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
DEFAULT_JSON="$ROOT/railway.json"
WORKER_JSON="$ROOT/railway-worker.json"
BAK="$(mktemp)"
trap 'mv -f "$BAK" "$DEFAULT_JSON"' EXIT
cp "$DEFAULT_JSON" "$BAK"
cp "$WORKER_JSON" "$DEFAULT_JSON"
MSG="${1:-worker deploy}"
MSG="${MSG:0:100}"
"$RAILWAY" up -s gifhorn-worker -c -m "$MSG"
