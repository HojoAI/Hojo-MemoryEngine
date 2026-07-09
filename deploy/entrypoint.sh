#!/bin/bash
set -euo pipefail

role="${MEMORY_ENGINE_ROLE:-api}"

VENV_BIN="/app/.venv/bin"

case "${role}" in
  api)
    exec /app/run_server.sh
    ;;
  worker)
    if [[ -x "${VENV_BIN}/memory-engine-worker" ]]; then
      exec "${VENV_BIN}/memory-engine-worker"
    fi
    exec "${VENV_BIN}/python" -m memory_engine.temporal.worker
    ;;
  dashboard)
    python3 - <<'PY'
import json
import os

config = {
    "VITE_API_BASE_URL": os.environ.get("VITE_API_BASE_URL", ""),
    "VITE_APISIX_URL": os.environ.get("VITE_APISIX_URL", ""),
}
path = "/usr/share/nginx/html/runtime-config.js"
with open(path, "w", encoding="utf-8") as f:
    f.write("window.__RUNTIME_CONFIG__ = ")
    json.dump(config, f, ensure_ascii=False)
    f.write(";\n")
PY
    exec nginx -g 'daemon off;'
    ;;
  *)
    echo "Unknown MEMORY_ENGINE_ROLE: ${role} (expected api|worker|dashboard)" >&2
    exit 1
    ;;
esac
