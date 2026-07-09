# Memory Engine 统一镜像：API / Temporal Worker / Dashboard（Nginx 静态站）
#
# 构建示例：
#   docker build -t memory-engine:latest .                                    # 含 Dashboard（默认 target full）
#   docker build --target api -t memory-engine-api:latest .                   # 仅 API/Worker，跳过前端（CI 推荐）
#   docker build -f docker/Dockerfile.pydeps -t memory-engine-pydeps:latest . # optional deps base image
#
# 运行角色：MEMORY_ENGINE_ROLE=api | worker | dashboard
# syntax=docker/dockerfile:1

# -----------------------------------------------------------------------------
# Python 依赖层（仅随 uv.lock / pyproject 变化而重建；勿与 src 同层）
# -----------------------------------------------------------------------------
FROM python:3.12-slim-bookworm AS python-deps

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=0 \
    UV_LINK_MODE=copy \
    UV_HTTP_TIMEOUT=300 \
    UV_HTTP_RETRIES=8 \
    UV_CONCURRENT_DOWNLOADS=16

ARG UV_INDEX_URL=https://pypi.org/simple/
ARG UV_EXTRA_INDEX_URL=

WORKDIR /app

RUN pip install --no-cache-dir "uv>=0.7.0"

COPY backend/pyproject.toml backend/uv.lock backend/README.md ./

RUN --mount=type=cache,target=/root/.cache/uv,sharing=locked \
    echo ">>> uv sync deps only (--no-install-project)" \
    && uv sync --frozen --no-dev --no-install-project \
    $( [ -n "${UV_INDEX_URL}" ] && echo "--index-url ${UV_INDEX_URL}" || true ) \
    $( [ -n "${UV_EXTRA_INDEX_URL}" ] && echo "--extra-index-url ${UV_EXTRA_INDEX_URL}" || true )

# -----------------------------------------------------------------------------
# Dashboard 前端（target api 会跳过本阶段）
# -----------------------------------------------------------------------------
FROM node:20-bookworm-slim AS dashboard-build

WORKDIR /app

ENV NODE_ENV=development \
    NPM_CONFIG_OMIT_DEV=false \
    NPM_CONFIG_FETCH_RETRIES=8 \
    NPM_CONFIG_FETCH_RETRY_MINTIMEOUT=20000 \
    NPM_CONFIG_FETCH_RETRY_MAXTIMEOUT=120000 \
    NPM_CONFIG_FETCH_TIMEOUT=600000

COPY dashboard/ ./

ARG NPM_REGISTRY=https://registry.npmjs.org

RUN rm -rf node_modules \
    && echo ">>> dashboard npm ci (registry=${NPM_REGISTRY})" \
    && npm config set registry "${NPM_REGISTRY}" \
    && (for n in 1 2 3; do npm ci && exit 0; echo "npm ci attempt ${n} failed, retry in 15s..."; sleep 15; done; exit 1) \
    || (echo ">>> fallback registry.npmjs.org" \
        && npm config set registry https://registry.npmjs.org \
        && npm ci) \
    && test -f node_modules/typescript/lib/tsc.js \
    && echo ">>> dashboard npm ci done"

ARG VITE_SUPABASE_URL=https://your-project.supabase.co
ARG VITE_SUPABASE_ANON_KEY=your-anon-key
ENV VITE_SUPABASE_URL=${VITE_SUPABASE_URL} \
    VITE_SUPABASE_ANON_KEY=${VITE_SUPABASE_ANON_KEY}

RUN npm run build

# -----------------------------------------------------------------------------
# 运行时：复用 python-deps 层，仅在有 src 变更时重装本项目
# -----------------------------------------------------------------------------
FROM python:3.12-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=Asia/Shanghai \
    PORT=6030 \
    MEMORY_ENGINE_ROLE=api \
    UV_COMPILE_BYTECODE=0 \
    UV_LINK_MODE=copy \
    UV_HTTP_TIMEOUT=300 \
    PATH="/app/.venv/bin:${PATH}" \
    PYTHONPATH=/app/src

ARG UV_INDEX_URL=https://pypi.org/simple/
ARG UV_EXTRA_INDEX_URL=

RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    set -eux; \
    if [ -f /etc/apt/sources.list.d/debian.sources ]; then \
      sed -i \
        -e 's|http://deb.debian.org/debian|https://mirrors.aliyun.com/debian|g' \
        -e 's|https://deb.debian.org/debian|https://mirrors.aliyun.com/debian|g' \
        -e 's|http://security.debian.org/debian-security|https://mirrors.aliyun.com/debian-security|g' \
        -e 's|https://security.debian.org/debian-security|https://mirrors.aliyun.com/debian-security|g' \
        /etc/apt/sources.list.d/debian.sources; \
    fi; \
    if [ -f /etc/apt/sources.list ]; then \
      sed -i \
        -e 's|http://deb.debian.org/debian|https://mirrors.aliyun.com/debian|g' \
        -e 's|http://security.debian.org/debian-security|https://mirrors.aliyun.com/debian-security|g' \
        /etc/apt/sources.list; \
    fi; \
    apt-get update; \
    apt-get install -y --no-install-recommends curl nginx \
    && rm -rf /var/lib/apt/lists/* \
    && rm -f /etc/nginx/sites-enabled/default

WORKDIR /app

RUN pip install --no-cache-dir "uv>=0.7.0"

COPY --from=python-deps /app/.venv /app/.venv
COPY --from=python-deps /app/pyproject.toml /app/pyproject.toml
COPY --from=python-deps /app/uv.lock /app/uv.lock
COPY --from=python-deps /app/README.md /app/README.md

COPY backend/src ./src
COPY backend/run_server.sh backend/logging.yaml ./

RUN --mount=type=cache,target=/root/.cache/uv,sharing=locked \
    chmod +x run_server.sh \
    && echo ">>> uv sync project only (deps from python-deps stage)" \
    && uv sync --frozen --no-dev \
    $( [ -n "${UV_INDEX_URL}" ] && echo "--index-url ${UV_INDEX_URL}" || true ) \
    $( [ -n "${UV_EXTRA_INDEX_URL}" ] && echo "--extra-index-url ${UV_EXTRA_INDEX_URL}" || true ) \
    && test -x /app/.venv/bin/uvicorn \
    && test -x /app/.venv/bin/memory-engine-worker \
    && test -f /app/src/memory_engine/services/admin_service.py \
    && test -f /app/src/memory_engine/services/__init__.py

COPY deploy/entrypoint.sh deploy/healthcheck.sh /
RUN chmod +x /entrypoint.sh /healthcheck.sh

# target api：仅 API/Worker（无 Dashboard 静态资源，构建最快）
FROM runtime AS api
EXPOSE 6030
HEALTHCHECK --interval=30s --timeout=10s --start-period=45s --retries=3 \
    CMD ["/healthcheck.sh"]
ENTRYPOINT ["/entrypoint.sh"]

# target full：API + Dashboard（默认）
FROM runtime AS full
COPY deploy/nginx-dashboard.conf /etc/nginx/conf.d/default.conf
COPY --from=dashboard-build /app/dist /usr/share/nginx/html
EXPOSE 6030 80
HEALTHCHECK --interval=30s --timeout=10s --start-period=45s --retries=3 \
    CMD ["/healthcheck.sh"]
ENTRYPOINT ["/entrypoint.sh"]
