# Memory Engine HTTP API 参考

本文档描述面向 **H5 / App WebView** 的用户记忆数据管理接口（查询、清空、邮件导出当前登录用户的全部记忆条目）。完整用户指南与 SDK 说明见 [user-guide.md](./user-guide.md)。

**Base URL**

| 环境 | 示例 |
|------|------|
| 本地 | `http://127.0.0.1:6030/api/v1` |
| 生产 | 以运维提供的域名为准，例如 `https://api.memory-engine.example.com/api/v1` |

**通用响应信封**

与常见 H5 用户侧接口一致，业务数据在 **`resContent`** 中：

```json
{
  "resCode": "OK",
  "resMessage": "请求成功",
  "resContent": { }
}
```

| 字段 | 说明 |
|------|------|
| `resCode` | 业务码；成功一般为 `OK`（与 `ResponseStatusBasic.OK` 一致） |
| `resMessage` | 提示文案；失败时含可读原因（如缺少 `X-User-Id`） |
| `resContent` | 成功时的业务载荷；失败时通常为 `null` 或省略 |

- 判定成功：`resCode === "OK"`。
- HTTP 4xx/5xx 或 `resCode` 非 `OK` 表示失败。

---

## 用户记忆数据接口（`/data/user/*`）

按 **Mongo/Qdrant 分区** 查询或软删除**当前登录用户**的全部记忆数据（`memory_data` 集合与向量索引），**不**操作 Schema（`memory_field` 等 MySQL 元数据）。

协议说明：使用请求头 `X-User-Id` 标识用户，GET 查询、POST 变更；本组接口采用相同鉴权与响应结构。

### 与其它 `user_id` 的区别

| 名称 | 含义 |
|------|------|
| **`memory_user_id`（分区键）** | Mongo 字段 `memory_data.user_id`、Qdrant `payload.user_id`。由服务端根据鉴权后的 `X-User-Id` 与租户配置解析，**客户端无需也不应传** `memory_user_id`。 |
| **MySQL `app_user.id`** | 平台账号表主键；与请求头 `X-User-Id` 一致时用于解析上述分区键。 |

租户隔离由网关/服务端注入的 `tenant_id`、`org_id` 与库内字段共同保证（H5 一般无需传 `X-Tenant-Id`）。

### 鉴权（H5 用户 Token）

与 `mos_` **API Key** 不同，面向终端用户，使用 H5 登录态（网关或客户端拦截器附加）：

| 请求头 | 必填 | 说明 |
|--------|------|------|
| `X-User-Id` | 是 | 用户 ID；缺失时 `resCode` 为错误码，`resMessage` 如「缺少请求头 X-User-Id」 |
| `X-User-Token` | 是 | 用户登录 Token；由网关校验，无效/过期时拒绝请求 |
| `X-Platform-Type` | 否 | 平台类型（H5 拦截器按域名自动附加） |
| `X-Environment-Region` | 否 | 海外等区域标识；国内可不传（与 `AccountRegionHelper.HEADER` 一致） |

> **说明**：`X-User-Id` 须与 Token 对应用户一致；服务端以 Token 校验结果为准，不信任客户端伪造的其它用户 ID。

### 删除语义（软删除）

| 存储 | 删除操作 | 删除后 |
|------|----------|--------|
| MongoDB | `memory_data.deleted = 1` | 文档保留；`list-all` / `GET /data/get` 等仅查 `deleted=0`，**不可再列出或精确读取** |
| Qdrant | `payload.deleted = 1` | 向量点保留；语义检索过滤 `deleted=0`，**不可再被检索引用** |

不进行物理删除（Mongo 不 `drop`，Qdrant 不 `delete` 点）。

### curl 速查（三个核心接口）

先设置公共变量（本地 `http://127.0.0.1:6030/api/v1`；生产使用 `https://`，例如 `https://api.memory-engine.example.com/api/v1`）：

```bash
export MEMORY_ENGINE_API_BASE="https://api.memory-engine.example.com/api/v1"
export X_USER_ID='1373848652186972160'
export X_USER_TOKEN='从 H5 登录后浏览器请求里复制的真实 Token'
```

> **不要**把文档占位符 `your-h5-user-token` 或中文说明「你的 H5 登录 Token」原样写入 `X_USER_TOKEN`；服务端会校验失败。  
> `/data/user/*` **不使用** `MEMORY_ENGINE_SERVICE_BEARER_TOKEN`、`MEMORY_ENGINE_TENANT_ID` 等 SDK 变量（那些用于 `mos_` API Key 接口）。

**1）查询全部记忆（分页）** — `GET /data/user/list-all`

```bash
curl -s -G "${MEMORY_ENGINE_API_BASE}/data/user/list-all" \
  -H "X-User-Id: ${X_USER_ID}" \
  -H "X-User-Token: ${X_USER_TOKEN}" \
  --data-urlencode "offset=0" \
  --data-urlencode "limit=200"
```

**2）软删除全部记忆** — `POST /data/user/delete-all`

```bash
curl -s -X POST "${MEMORY_ENGINE_API_BASE}/data/user/delete-all" \
  -H "X-User-Id: ${X_USER_ID}" \
  -H "X-User-Token: ${X_USER_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{}'
```

**3）导出记忆到邮箱** — `POST /data/user/export-email`

```bash
curl -s -X POST "${MEMORY_ENGINE_API_BASE}/data/user/export-email" \
  -H "X-User-Id: ${X_USER_ID}" \
  -H "X-User-Token: ${X_USER_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{
    "email": "you@example.com",
    "offset": 0
  }'
```

> 可选：在 `export-email` 的 JSON 中增加 `"limit": 100` 做分页导出；省略 `limit` 时导出全部未删数据（上限见 `MEMORY_EXPORT_EMAIL_MAX_ITEMS`）。

### curl 无输出 / 排查

`curl -s` 只隐藏进度条，**错误仍在 stderr**；若 stdout 完全空白，先去掉 `-s` 并看状态码：

```bash
# 1）连通性（应返回 {"status":"ok"} 或类似 JSON）
curl -v "https://api.memory-engine.example.com/health"

# 2）业务接口（应总有 JSON，含 resCode / resMessage）
curl -v -G "${MEMORY_ENGINE_API_BASE}/data/user/list-all" \
  -H "X-User-Id: ${X_USER_ID}" \
  -H "X-User-Token: ${X_USER_TOKEN}" \
  --data-urlencode "offset=0" \
  --data-urlencode "limit=10"
```

| 现象 | 常见原因 |
|------|----------|
| 立刻回到提示符、stdout 为空 | 用了 `http://` 而 Ingress 仅 TLS；或域名/网络不可达（看 `curl -v` 的 `Could not resolve` / `Connection refused`） |
| 有 JSON 且 `resCode` 非 `OK` | `X_USER_TOKEN` 无效/过期，或 PRE 未配置 Redis/账户校验 URL |
| `resMessage` 含「用户 Token 校验未配置」 | 集群需配置 `USER_TOKEN_REDIS_KEY_TEMPLATE` 或 `USER_ACCOUNT_VALIDATE_URL`（联调可临时 `USER_TOKEN_SKIP_VALIDATE=true`，生产勿开） |

**获取真实 `X-User-Token`**：H5 登录后，浏览器开发者工具 → Network → 复制带 `X-User-Token` 请求头中的 Token 值。

---

## 1. 查询用户全部记忆数据

列出当前用户、当前租户/组织内**未软删**的全部记忆条目（分页）。

### 请求

| 项 | 值 |
|----|-----|
| **Method** | `GET` |
| **Path** | `/data/user/list-all` |

**Query**

| 参数 | 类型 | 必填 | 默认 | 说明 |
|------|------|------|------|------|
| `offset` | int | 否 | `0` | 分页偏移，≥ 0 |
| `limit` | int | 否 | `200` | 每页条数，1–1000 |

### 响应 `resContent`

| 字段 | 类型 | 说明 |
|------|------|------|
| `memory_user_id` | string | 服务端解析的 Mongo/Qdrant 分区 ID |
| `items` | array | 记忆条目列表 |
| `items[].user_id` | string | 与 Mongo 字段一致（值同 `memory_user_id`） |
| `items[].memory_field_name` | string | 记忆字段名 |
| `items[].value` | any | 记忆值 |
| `items[].deleted` | int | 列表中均为 `0`（仅返回未删数据） |
| `total` | int | 符合条件的总条数 |
| `offset` | int | 本次偏移 |
| `limit` | int | 本次 limit |

### curl 示例

见上文 [curl 速查 §1](#curl-速查三个核心接口)。

### 响应示例

```json
{
  "resCode": "OK",
  "resMessage": "请求成功",
  "resContent": {
    "memory_user_id": "mos_Ufzwx1kKITli",
    "items": [
      {
        "user_id": "mos_Ufzwx1kKITli",
        "memory_field_name": "居住地",
        "value": "北京",
        "deleted": 0
      }
    ],
    "total": 1,
    "offset": 0,
    "limit": 200
  }
}
```

### 错误（常见）

| 场景 | `resCode` / HTTP | `resMessage` 示例 |
|------|------------------|-------------------|
| 缺少 `X-User-Id` | 非 `OK` | 缺少请求头 X-User-Id |
| Token 无效或过期 | 非 `OK` / 401 | 以网关/鉴权层为准 |
| 参数不合法 | 非 `OK` / 422 | offset、limit 类型或范围错误 |

---

## 2. 软删除用户全部记忆数据

将当前用户、当前租户/组织内所有**未删**记忆一次性标记为已删除（Mongo + Qdrant），之后无法通过列表、精确读取或语义检索命中。

### 请求

| 项 | 值 |
|----|-----|
| **Method** | `POST` |
| **Path** | `/data/user/delete-all` |

**Body**

无必填字段；请求体可省略或传 `{}`。用户身份仅由请求头 `X-User-Id` + `X-User-Token` 确定（与 `POST /user/memory-settings` 一致）。

| 请求头 | 必填 | 说明 |
|--------|------|------|
| `Content-Type` | 否 | 无 Body 时可省略；有 Body 时为 `application/json` |

### 响应 `resContent`

| 字段 | 类型 | 说明 |
|------|------|------|
| `memory_user_id` | string | 已操作的分区 ID |
| `deleted_count` | int | Mongo 被标记 `deleted=1` 的文档数 |
| `vector_marked_count` | int | Qdrant 被标记 `payload.deleted=1` 的向量数（非物理删除条数） |

成功时 `resMessage` 可为固定文案（如「已清空记忆数据」），以实际实现为准。

### curl 示例

见上文 [curl 速查 §2](#curl-速查三个核心接口)。

### 响应示例

```json
{
  "resCode": "OK",
  "resMessage": "请求成功",
  "resContent": {
    "memory_user_id": "mos_Ufzwx1kKITli",
    "deleted_count": 3,
    "vector_marked_count": 2
  }
}
```

### 验证

删除后再次调用 [§1 查询](#1-查询用户全部记忆数据)，`resContent` 应为 `items: []`、`total: 0`。

### 错误（常见）

| 场景 | 说明 |
|------|------|
| 缺少 `X-User-Id` | 同 list-all |
| Token 无效 | 同 list-all |

即使该用户本无记忆，`deleted_count` / `vector_marked_count` 也可能为 `0`，`resCode` 仍为 `OK`。

---

## 3. 导出记忆数据到邮箱

按 [§1 查询](#1-查询用户全部记忆数据) 相同规则拉取当前用户未软删记忆，生成可读正文后发送到指定邮箱。

### 请求

| 项 | 值 |
|----|-----|
| **Method** | `POST` |
| **Path** | `/data/user/export-email` |

**Body（JSON）**

| 字段 | 类型 | 必填 | 默认 | 说明 |
|------|------|------|------|------|
| `email` | string | 是 | — | 收件邮箱 |
| `offset` | int | 否 | `0` | 与 `list-all` 一致 |
| `limit` | int | 否 | — | 1–1000；**省略**时导出全部未删数据（服务端上限见 `MEMORY_EXPORT_EMAIL_MAX_ITEMS`，默认 5000） |

鉴权头同 §1、§2。

### 响应 `resContent`

| 字段 | 类型 | 说明 |
|------|------|------|
| `email` | string | 实际发送的收件地址 |
| `memory_user_id` | string | 分区 ID |
| `item_count` | int | 邮件中包含的条数 |
| `total` | int | 库内未删总条数（与 list-all 的 `total` 一致） |
| `offset` | int | 请求偏移 |
| `limit` | int | 本次有效导出窗口（分页时为请求的 limit；全量导出时为 `item_count`） |

成功时 `resMessage` 可为「记忆数据已发送至邮箱」。

### curl 示例

见上文 [curl 速查 §3](#curl-速查三个核心接口)。

### 响应示例

```json
{
  "resCode": "OK",
  "resMessage": "记忆数据已发送至邮箱",
  "resContent": {
    "email": "you@example.com",
    "memory_user_id": "mos_Ufzwx1kKITli",
    "item_count": 3,
    "total": 3,
    "offset": 0,
    "limit": 3
  }
}
```

### 错误（常见）

| 场景 | 说明 |
|------|------|
| 缺少/非法 `email` | `resCode` 非 `OK`，如「邮箱格式不合法」 |
| SMTP 未配置 | `resMessage` 提示配置 `SMTP_HOST` 等 |
| 鉴权失败 | 同 list-all |

### 服务端配置

| 环境变量 | 说明 |
|----------|------|
| `SMTP_HOST` | SMTP 主机（必填方可发信） |
| `SMTP_PORT` | 端口，默认 `587` |
| `SMTP_USER` / `SMTP_PASSWORD` | 登录凭据（按服务商要求） |
| `SMTP_FROM` | 发件人地址 |
| `SMTP_USE_TLS` | 默认 `true`；端口 `465` 时使用 SSL |
| `MEMORY_EXPORT_EMAIL_MAX_ITEMS` | 全量导出条数上限，默认 `5000` |

---

## 4. 查询用户是否存在记忆数据

判断当前用户、当前租户/组织内是否存在**未软删**的记忆条目（与 [§1 查询](#1-查询用户全部记忆数据) 相同数据范围，仅返回布尔结果，不拉取明细）。

### 请求

| 项 | 值 |
|----|-----|
| **Method** | `GET` |
| **Path** | `/data/user/has-data` |

无 Query / Body。鉴权头同 §1、§2。

### 响应 `resContent`

| 字段 | 类型 | 说明 |
|------|------|------|
| `memory_user_id` | string | 服务端解析的 Mongo/Qdrant 分区 ID |
| `has_data` | bool | 存在未删记忆时为 `true`，否则为 `false` |

### curl 示例

```bash
curl -s "${MEMORY_ENGINE_API_BASE}/data/user/has-data" \
  -H "X-User-Id: ${X_USER_ID}" \
  -H "X-User-Token: ${X_USER_TOKEN}"
```

### 响应示例

存在记忆：

```json
{
  "resCode": "OK",
  "resMessage": "请求成功",
  "resContent": {
    "memory_user_id": "mos_Ufzwx1kKITli",
    "has_data": true
  }
}
```

不存在记忆：

```json
{
  "resCode": "OK",
  "resMessage": "请求成功",
  "resContent": {
    "memory_user_id": "mos_Ufzwx1kKITli",
    "has_data": false
  }
}
```

### 错误（常见）

| 场景 | 说明 |
|------|------|
| 缺少 `X-User-Id` | 同 list-all |
| Token 无效 | 同 list-all |

---

## 与业务 API 的关系

| 能力 | 接口 | 鉴权 |
|------|------|------|
| 单字段读写/删除 | `POST /data/create`、`GET /data/get`、`POST /data/delete` 等 | `mos_` API Key（Bearer） |
| 用户全量列表/清空/邮件导出/是否存在 | `GET /data/user/list-all`、`POST /data/user/delete-all`、`POST /data/user/export-email`、`GET /data/user/has-data` | H5 用户 Token（`X-User-Id` + `X-User-Token`） |

SDK（`memory_engine_sdk`）当前封装的是 API Key 路径；用户全量列表/清空/邮件导出/是否存在请由 H5 或 BFF 按上表调用。

---

## 相关配置

| 配置项 | 说明 |
|--------|------|
| 网关用户鉴权 | 校验 `X-User-Token` 并注入/校验 `X-User-Id` |
| `SMTP_*` | `export-email` 发信（见 §3） |
| `MONGODB_*` / `QDRANT_URL` | 记忆数据与向量存储 |
| 租户/组织 | 与写入记忆时使用的 `tenant_id`、`org_id` 一致，由服务端按用户绑定解析 |

示例见仓库根目录 `.env.example`。
