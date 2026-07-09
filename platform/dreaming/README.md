# Memory Engine Dreaming Platform

- **LIGHT / REM / DEEP** 任务分层
- **Temporal** 编排：`backend/src/memory_engine/temporal/`（Worker：`poetry run memory-engine-worker`）
- **Spark/Flink**：通过 `OBJECT_STORAGE_*` 等环境变量连接对象存储与计算集群
- 治理提案经 `governance_proposal` → 审核 → `writeback_audit` 回写 Schema/Data API

本地开发可先调用 Backend `POST /api/v1/governance/proposals` 与 `GET /api/v1/governance/dreaming/jobs`。
