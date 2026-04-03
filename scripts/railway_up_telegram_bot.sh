#!/usr/bin/env bash
# Railway CLI deploy für gifhorn-telegram-bot.
# Nixpacks liest root railway.json; daher kurz auf railway-telegram.json umschalten.
set -euo pipefail
if [ -x /opt/homebrew/bin/railway ]; then RAILWAY=/opt/homebrew/bin/railway
elif [ -x /usr/local/bin/railway ]; then RAILWAY=/usr/local/bin/railway
else RAILWAY=railway; fi
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
WORKER_JSON="$ROOT/railway.json"
TG_JSON="$ROOT/railway-telegram.json"
BAK="$(mktemp)"
trap 'mv "$BAK" "$WORKER_JSON"' EXIT
cp "$WORKER_JSON" "$BAK"
cp "$TG_JSON" "$WORKER_JSON"
"$RAILWAY" up -s gifhorn-telegram-bot -c -m "${1:-telegram-bot: always-on polling}"
