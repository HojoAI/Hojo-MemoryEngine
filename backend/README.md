# Memory Engine Backend

## 启动

```bash
cd backend
uv sync
cp ../.env.example ../.env   # 配置 MySQL / Redis / Mongo / Qdrant / OpenAI
uv run uvicorn memory_engine.main:app --reload --host 0.0.0.0 --port 6030
```

默认 `APP_DISABLE_AUTH=false`，使用 API Key：

```bash
export MOS_API_KEY=mos_devtest00001ab
curl -s -H "Authorization: Bearer $MOS_API_KEY" http://127.0.0.1:6030/api/v1/schema/list
```

## Temporal Worker

```bash
cd infra/docker-compose && docker compose up -d temporal temporal-ui
cd backend && uv run memory-engine-worker
```

- Schema 编排：`POST /api/v1/schema/upsert?wait=true`
- Dreaming 触发：`POST /api/v1/governance/dreaming/jobs/1/runs?wait=true`

## 数据库迁移与种子

```bash
# 全量 DDL（空库首次）
mysql -h ... -u ... -p memory_engine < migrations/mysql/001_initial_schema.sql
# 开发租户 tenant_id=1
mysql -h ... -u ... -p memory_engine < migrations/mysql/002_seed_dev.sql
```

- 开发 API Key：`mos_devtest00001ab`（`Authorization: Bearer ...`）
- Redis 缓存键前缀：`memory_engine`（见 `REDIS_KEY_PREFIX`）

## 测试

```bash
uv run pytest
```

## V2 会议记忆与 AML 适配

先执行 `migrations/mysql/005_memory_claim_v2.sql`，再按需启用 `MEMORY_V1_DUAL_WRITE_ENABLED=true`。V2 的 `/api/v2/memory/ingest`、`retrieve`、`call` 接口可独立使用；Claim 以 MongoDB 为事实源，Qdrant 用作可重建索引。迁移和权限说明见 [Memory Claims V2](./docs/MEMORY_CLAIMS_V2.md)，会议检索策略见 [Meeting Retrieval Profiles](./docs/MEETING_RETRIEVAL_PROFILES.md)。

`/aml/add`、`/aml/search` 和 `/aml/clear` 提供 Agent Memory Leaderboard 证据接口，详见 [AML 适配说明](../docs/AML.md)。详细记忆值日志默认关闭，仅在受控调试环境中设置 `MEMORY_RUNTIME_MONITOR_ENABLED=true`。

## 端到端联调

先启动 API、Temporal（`docker compose up -d temporal`）与 Worker（`uv run memory-engine-worker`），再执行：

```bash
# 仓库根目录
export MOS_API_KEY=mos_devtest00001ab
./backend/scripts/run_e2e.sh

# 仅测 API（跳过 Temporal 工作流）
E2E_SKIP_TEMPORAL=1 E2E_SKIP_DREAMING=1 ./backend/scripts/run_e2e.sh

# 或
cd backend && uv run python scripts/e2e_smoke.py --help
```

脚本步骤：`/health` → 无 Key 403 → 有 Key `schema/list` → `schema/create` → `schema/get` → `schema/upsert?wait=true` → `dreaming/jobs/1/runs` → `billing/events`。
