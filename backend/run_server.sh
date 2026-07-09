#!/usr/bin/env bash
set -euo pipefail
# MemoryEngine API：单 worker（与 Kafka consumer lifespan 同进程）
export PYTHONPATH="${PYTHONPATH:+$PYTHONPATH:}/app/src"
VENV_BIN="/app/.venv/bin"
LOG_CONFIG="${LOG_CONFIG:-/app/logging.yaml}"
exec "${VENV_BIN}/uvicorn" memory_engine.main:app \
  --host 0.0.0.0 \
  --port "${PORT:-6030}" \
  --workers "${UVICORN_WORKERS:-1}" \
  --log-config "${LOG_CONFIG}" \
  --log-level "${LOG_LEVEL:-info}"
