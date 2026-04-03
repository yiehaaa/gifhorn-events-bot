#!/usr/bin/env bash
# Setzt DATABASE_URL auf beiden App-Services (Worker + Dashboard).
# Wert nie ins Git committen — nur Railway-Variablen oder lokale .env (gitignored).
#
# Nutzung:
#   DATABASE_URL='postgresql://…' ./scripts/sync_railway_database_url.sh
#   echo -n 'postgresql://…' | ./scripts/sync_railway_database_url.sh
#
# Optional: Deploys unterdrücken, dann manuell redeployen:
#   SKIP_DEPLOY=1 DATABASE_URL='…' ./scripts/sync_railway_database_url.sh

set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

URL="${DATABASE_URL:-}"
if [[ -z "$URL" ]]; then
  if [[ -t 0 ]]; then
    echo "Usage: DATABASE_URL='postgresql://…' $0" >&2
    echo "   or: echo -n 'postgresql://…' | $0" >&2
    exit 1
  fi
  URL=$(cat)
fi

if [[ "$URL" != postgresql://* && "$URL" != postgres://* ]]; then
  echo "DATABASE_URL muss mit postgresql:// oder postgres:// beginnen." >&2
  exit 1
fi

for svc in gifhorn-worker gifhorn-dashboard; do
  if [[ "${SKIP_DEPLOY:-}" == "1" ]]; then
    printf '%s' "$URL" | railway variable set DATABASE_URL --stdin --skip-deploys -s "$svc"
  else
    printf '%s' "$URL" | railway variable set DATABASE_URL --stdin -s "$svc"
  fi
  echo "OK: DATABASE_URL gesetzt für $svc"
done

echo "Fertig. Bei Bedarf: railway redeploy -s gifhorn-worker -y && railway redeploy -s gifhorn-dashboard -y"
