# Memory Engine 工程结构 (v0.5)

```
Memory Engine/
├── backend/                 # FastAPI 服务 (uv, Python 3.12+)
│   ├── src/memory_engine/
│   │   ├── api/v1/          # REST API
│   │   ├── models/          # SQLAlchemy ORM
│   │   ├── services/        # 业务逻辑（schema_search、memory_parse、memory_data 等）
│   │   ├── integrations/    # MySQL/Redis/Mongo/Qdrant/LLM/Kafka
│   │   └── main.py
│   ├── migrations/mysql/
│   ├── scripts/             # e2e_smoke、test_all_features、run_e2e.sh
│   ├── tests/
│   └── Dockerfile
├── sdk/python/              # memory_engine_sdk Python SDK
├── sdk/java/                # memory-engine-sdk Java SDK (Java 17)
├── examples/                # 联调示例（如 sdk_pre_llm_parse.py）
├── docs/                    # user-guide.md 等
├── dashboard/               # React 18 + Ant Design Pro + Supabase
├── platform/dreaming/       # Dreaming / 治理编排说明
├── infra/docker-compose/    # Kafka、Temporal 等（本地）
├── deploy/                  # K8s / 镜像部署说明
└── .env.example
```

## 启动

```bash
# Backend
cd backend && uv sync
export APP_DISABLE_AUTH=true   # 开发可跳过 API Key
uv run uvicorn memory_engine.main:app --reload --port 6030

# Temporal Worker（编排 / Dreaming）
cd infra/docker-compose && docker compose up -d temporal
cd backend && uv run memory-engine-worker

# Dashboard
cd dashboard && npm install && npm run dev

# Kafka（schema 热更新 Consumer，可选）
cd infra/docker-compose && docker compose up -d kafka
# 设置 KAFKA_CONSUMERS_ENABLED=true 后随 API 启动
```

环境变量：复制仓库根目录 `.env.example` → `.env`（已 gitignore）。在 `backend/` 下启动时会自动加载 `../.env`。

**LLM 解析联调**（PRE / 本地需配置 `OPENAI_*`）：

```bash
cd sdk/python && uv pip install -e .
export MEMORY_ENGINE_API_BASE=http://127.0.0.1:6030/api/v1
export MEMORY_ENGINE_API_KEY=mos_devtest00001ab
export MEMORY_ENGINE_TENANT_ID=1
export MEMORY_ENGINE_ORG_ID=1
python examples/sdk_pre_llm_parse.py
```

## 联调与开户

| 脚本 / 文档 | 说明 |
|-------------|------|
| `./backend/scripts/run_e2e.sh` | 冒烟（`e2e_smoke.py`） |
| `cd backend && uv run python scripts/test_all_features.py` | 全功能联调 |
| `POST /api/v1/admin/tenants` | 管理开户（头 `X-Admin-Secret`） |
| [docs/user-guide.md](docs/user-guide.md) | 新用户：Dashboard、SDK、FAQ |

开发种子（`tenant_id=1`）：`mysql ... < backend/migrations/mysql/002_seed_dev.sql`  
开发 API Key：`mos_devtest00001ab`

Kafka Consumer：设置 `KAFKA_CONSUMERS_ENABLED=true` 后随 API 启动（schema 缓存失效 + billing 处理）。
