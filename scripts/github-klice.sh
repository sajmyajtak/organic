#!/usr/bin/env bash
# Přenese klíče z .env do GitHub Secrets, aby publikace běžela z GitHubu
# (Mac nemusí být zapnutý). Hodnoty nikde nevypisuje.
#   bash scripts/github-klice.sh
set -euo pipefail
cd "$(dirname "$0")/.."
REPO="sajmyajtak/organic"

value() {  # hodnota z .env přes stejný načítač jako igbot (umí komentáře a uvozovky)
  .venv/bin/python -c "import os, sys, igbot.config; sys.stdout.write(os.environ.get('$1', ''))"
}

missing=0
for key in IG_ACCESS_TOKEN AIRTABLE_TOKEN; do
  v="$(value "$key")"
  if [ -z "$v" ]; then
    echo "✗ $key v .env chybí"
    missing=1
    continue
  fi
  printf '%s' "$v" | gh secret set "$key" -R "$REPO"
  echo "✓ $key je na GitHubu"
done

if [ "$missing" = 1 ]; then
  echo "Doplň chybějící klíče do .env a spusť skript znovu. Publikace zatím zůstává vypnutá."
  exit 1
fi
# Až teď: podle IG_USER_ID workflow pozná, že je účet připojený, a začne publikovat.
gh secret set IG_USER_ID -R "$REPO" -b "$(value IG_USER_ID)"
echo "✓ IG_USER_ID je na GitHubu – automat od příštího běhu publikuje schválené posty."
