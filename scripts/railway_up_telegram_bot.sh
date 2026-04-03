#!/bin/bash
# Railway CLI deploy für gifhorn-telegram-bot.
# Nixpacks liest root railway.json; daher kurz auf railway-telegram.json umschalten.
#
# Hinweis: Kein „railway“ ohne Pfad — unter Zsh kann eine Funktion namens railway die echte CLI verdecken.
# Optionaler $1 (Deploy-Message) wird auf 100 Zeichen gekürzt (verhindert „command too long“ bei Paste-Fehlern).
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
TG_JSON="$ROOT/railway-telegram.json"
BAK="$(mktemp)"
trap 'mv -f "$BAK" "$WORKER_JSON"' EXIT
cp "$WORKER_JSON" "$BAK"
cp "$TG_JSON" "$WORKER_JSON"
MSG="${1:-telegram-bot deploy}"
MSG="${MSG:0:100}"
"$RAILWAY" up -s gifhorn-telegram-bot -c -m "$MSG"
