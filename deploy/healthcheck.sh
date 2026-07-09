#!/bin/bash
set -euo pipefail

role="${MEMORY_ENGINE_ROLE:-api}"

case "${role}" in
  api)
    curl -fsS "http://127.0.0.1:${PORT:-6030}/health" >/dev/null
    ;;
  dashboard)
    curl -fsS http://127.0.0.1/health >/dev/null
    ;;
  worker)
    # Temporal worker 无 HTTP 探针；由 K8s 进程存活策略或外部监控
    exit 0
    ;;
  *)
    exit 1
    ;;
esac
