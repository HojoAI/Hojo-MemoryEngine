#!/usr/bin/env bash
# MemoryEngine E2E smoke wrapper — loads repo .env and runs e2e_smoke.py
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
BACKEND="$(cd "$(dirname "$0")/.." && pwd)"

# Load .env without breaking on '#' in values (e.g. passwords).
if [[ -f "$ROOT/.env" ]]; then
  set -a
  while IFS= read -r line || [[ -n "$line" ]]; do
    [[ -z "$line" || "$line" =~ ^[[:space:]]*# ]] && continue
    [[ "$line" != *"="* ]] && continue
    key="${line%%=*}"
    value="${line#*=}"
    key="${key#"${key%%[![:space:]]*}"}"
    key="${key%"${key##*[![:space:]]}"}"
    value="${value#"${value%%[![:space:]]*}"}"
    value="${value%"${value##*[![:space:]]}"}"
    value="${value%\"}"; value="${value#\"}"
    value="${value%\'}"; value="${value#\'}"
    export "$key=$value"
  done < "$ROOT/.env"
  set +a
fi

export MOS_API_KEY="${MOS_API_KEY:-mos_devtest00001ab}"
export API_BASE_URL="${API_BASE_URL:-http://127.0.0.1:6030}"

cd "$BACKEND"

if command -v poetry >/dev/null 2>&1; then
  exec poetry run python scripts/e2e_smoke.py "$@"
fi

if ! python3 -c "import httpx" 2>/dev/null; then
  echo "Installing httpx for e2e script..."
  python3 -m pip install -q httpx
fi

exec python3 scripts/e2e_smoke.py "$@"
