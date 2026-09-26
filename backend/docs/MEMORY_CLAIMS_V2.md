# Memory Claims V2（P0/P1）

V2 将整段可变文本记忆拆成可版本化、可追溯的原子 Claim，并在检索前执行硬权限过滤。V1 API 保持兼容；V2 双写默认关闭，完成迁移与验证后可通过 `MEMORY_V1_DUAL_WRITE_ENABLED=true` 开启。

## 核心边界

- `namespace.type + namespace.id` 是硬隔离键。融资项目、产品项目之间不能串用记忆。
- 每个 Claim 都保存 `claim_key`、结构化 `value`、事实状态、置信度、有效期、来源证据和使用策略。
- 更新动作固定为 `ADD / CONFIRM / UPDATE / SUPERSEDE / CONFLICT / REJECT`，冲突数据不会自动进入检索。
- 检索顺序为：权限与 namespace 过滤 → scope/模块/场景/角色/敏感度过滤 → 向量或词法召回 → 可选 LLM 重排 → 阈值与 token 预算 → 生成审计 bundle。
- LLM 只能重排已经通过权限检查的 Claim，只能返回候选 `claim_id`；合法的空选择会返回空结果，不会随机回退到第一条记忆。
- `/call` 只接受 `/retrieve` 产生的短期 bundle，且 bundle 锁定会议模块并有过期时间。

## API

- `POST /api/v1/memory/candidates/extract`：将直接传入的文本，或从受控 OSS URL 下载并解析的 Markdown/PDF/TXT 文档，拆成“认识一下你 / 项目 / 偏好 / 名词”四类候选记忆，并标注敏感度；`source.ossUrl` 非空时优先读取 OSS，否则使用 `source.text`，只返回预览，不写入记忆。
- `POST /api/v1/memory/candidates/compare`：将单条候选与该用户、指定 namespace 下的有效记忆比较，返回 `NEW / DUPLICATE / MERGE / CONFLICT / REJECT`；只返回判定和合并预览，不修改记忆。
- `POST /api/v2/memory/ingest`：写入 source event 与原子 Claim。
- `POST /api/v2/memory/retrieve`：按使用上下文返回授权后的 Memory Bundle；`method=LLM` 可启用大模型检索重排。
- `POST /api/v2/memory/call`：消费已审计 bundle，避免调用方绕过检索策略自行拼接全量记忆。
- `GET /api/v2/memory/claims/{claim_id}/history`：查看版本和来源历史。
- `POST /api/v2/memory/claims/{claim_id}/revoke`：撤回 Claim。
- `POST /api/v2/memory/claims/{claim_id}/resolve`：人工接受或拒绝冲突 Claim。

## 权限

- `memory:claim:write`
- `memory:claim:review`
- `memory:retrieve:self`
- `memory:retrieve:cross`
- `memory:retrieve:sensitive`
- `memory:policy:manage`

API Key 可使用 `memory:*`。数据级策略仍会继续限制 module、scenario、scope、caller role、sensitivity 和 `allow_llm`。

候选提取和比较接口使用 `data:read`，供 management 在“添加记忆”的预览阶段调用。调用方确认候选后，再通过写入接口持久化。

候选提取的 `source` 支持两种输入：

```json
{"type": "manual_text", "text": "我是 Acme 产品负责人……"}
```

```json
{"type": "import_file", "ossUrl": "https://bucket.oss-cn-shanghai.aliyuncs.com/a.pdf?..."}
```

OSS 输入只接受 HTTPS。默认允许阿里云 OSS 域名；自定义 OSS CNAME 通过 `MEMORY_CANDIDATE_OSS_ALLOWED_HOSTS` 配置，多个域名用逗号分隔。默认下载超时 15 秒、文件上限 20 MiB，可分别通过 `MEMORY_CANDIDATE_OSS_TIMEOUT_SECONDS` 和 `MEMORY_CANDIDATE_OSS_MAX_BYTES` 调整。支持 Markdown、TXT 和含文本层的 PDF；PDF 最多 500 页，解析后的正文最多 200000 字符。扫描 PDF 当前不做 OCR。预签名 URL 仅用于下载，不会传给 LLM。

`source.ossUrl` 和 `source.text` 可以同时传入。`ossUrl` 去除首尾空白后非空时，服务忽略 `text` 并使用 OSS 文档；`ossUrl` 缺失或为空白字符串时，服务回退使用 `text`。两者都为空时返回 422。

## 上线顺序

1. 执行 MySQL migration `005_memory_claim_v2.sql`。
2. 发布服务但先按需关闭 V1 双写，确认 MongoDB 可建立 `memory_source_event`、`memory_claim`、`memory_claim_head`、`memory_bundle_audit` 索引。
3. 为目标记忆维度配置 JSON Schema、更新策略和访问/检索策略。
4. 开启 V1 双写，观察 `CONFLICT/REJECT` 比率、双写错误日志和 Qdrant 索引积压。
5. 对单个会议模块灰度切换到 V2 retrieve/call，禁止调用方直接拼接全部历史记忆。
6. 验证 namespace 串项目率为 0、无权限引用率为 0，再逐模块扩大流量。

MongoDB 的 Claim 是事实源，Qdrant 仅作为可重建的检索索引。Qdrant 或 embedding 不可用时，写入仍成功，检索降级为词法评分；不会放宽权限或 namespace。
