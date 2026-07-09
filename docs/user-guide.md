# Memory Engine 用户操作指南

本文档说明**新用户**如何从 0 完成开户、在 Dashboard 中使用系统，以及如何通过 **Python / Java SDK** 或 HTTP API 调用记忆能力。适用于 Kubernetes 部署环境与本地开发环境。

---

## 1. 先理解两套「身份」

| 体系 | 用途 | 获取方式 |
|------|------|----------|
| **Supabase 账号** | 仅用于 **Dashboard 网页登录** | 在 Dashboard `/login` 注册/登录 |
| **Memory Engine API Key** | 调用 **业务 API** 与 **SDK**（Schema、记忆读写等） | 设置页申请、管理员创建租户、或运维种子数据 |

> **重要**：仅登录 Supabase **不能**自动调用 Memory Engine API，必须单独取得 API Key 并配置 `Tenant ID` / `Org ID`。

默认 API 地址：

- 本地：`http://127.0.0.1:6030/api/v1`
- 生产：由运维提供的域名，例如 `https://api.memory-engine.example.com/api/v1`（以实际 Ingress 为准）

健康检查：`GET {API根路径去掉 /api/v1}/health`，例如 `http://127.0.0.1:6030/health`。

---

## 2. 我该走哪条路径？

```text
┌─────────────────────────────────────────────────────────────────┐
│ 我是普通业务用户，要用网页管理 Schema / 记忆数据                  │
│   → 第 3 节：Dashboard 自助申请 API Key                          │
├─────────────────────────────────────────────────────────────────┤
│ 我是平台管理员，要为公司创建独立租户                              │
│   → 第 4 节：Dashboard「创建租户」或 第 6 节 curl 管理接口         │
├─────────────────────────────────────────────────────────────────┤
│ 我是开发者，在本地或生产环境用 Python/Java 集成                     │
│   → 先完成开户（第 3 或 4 节）→ 第 5 节 SDK                      │
├─────────────────────────────────────────────────────────────────┤
│ 我仅在本地跑通 Demo（已有种子数据）                               │
│   → 第 7 节：开发环境快捷方式                                    │
└─────────────────────────────────────────────────────────────────┘
```

---

## 3. Dashboard：普通用户自助开户（推荐）

适用于已部署 **Dashboard + API**，且集群开启自助注册（`ONBOARDING_ALLOW_SELF_REGISTER=true`，默认开启）。

### 3.1 前置条件

1. 浏览器能访问 Dashboard 地址（例如 `https://dashboard.memory-engine.example.com`）。
2. 运维已在镜像构建时配置 Supabase（`VITE_SUPABASE_URL`、`VITE_SUPABASE_ANON_KEY`）；API 地址（`VITE_API_BASE_URL`）在 K8s 部署时通过环境变量注入。
3. 已完成 Supabase 注册；若登录提示 **Email not confirmed**：
   - 查收确认邮件（含垃圾箱），或
   - 开发环境：在 [Supabase 控制台](https://supabase.com/dashboard) → **Authentication → Providers → Email** 关闭 **Confirm email**，或手动将用户标为 **Confirmed**。

### 3.2 操作步骤

| 步骤 | 操作 |
|------|------|
| 1 | 打开 Dashboard → **登录**（`/login`），使用 Supabase 邮箱密码 |
| 2 | 进入 **设置**（`/settings`）→ Tab **「申请 API Key」** |
| 3 | 确认邮箱、显示名 → 点击 **「申请 API Key」** |
| 4 | 弹窗中 **复制 Key**（仅显示一次），或点击 **「保存并用于连接」** |
| 5 | 切换到 Tab **「连接设置」**，确认 Tenant ID、Org ID、API Key 已填入 → **保存连接** |
| 6 | 使用左侧菜单：**Schema 管理**、**记忆数据**、**计费** 等 |

**首次申请**时，系统会自动创建个人工作区（租户编码形如 `sb-xxxxxxxxxxxx`），并返回：

- `tenant_id`、`org_id`、`user_id`
- 明文 `api_key`（请立即保存）

**再次申请**会为同一 Supabase 用户签发新的 API Key（旧 Key 仍有效，除非被吊销）。

### 3.3 未登录时仅配置 Key

若暂时不用 Supabase，可直接访问 **`/settings`** → **连接设置**，手工粘贴管理员提供的 Tenant / Org / API Key。

---

## 4. Dashboard：平台管理员创建企业租户

适用于为新团队一次性创建 **租户 + 组织 + 管理员用户 + API Key**。

### 4.1 前置条件

- 集群已配置环境变量 **`ADMIN_BOOTSTRAP_SECRET`**（与后端 `.env` 一致）。
- 你持有该 Secret（**不要**写入 Git 或提交到前端仓库）。

### 4.2 操作步骤

| 步骤 | 操作 |
|------|------|
| 1 | 登录 Dashboard（可选） |
| 2 | **设置** → Tab **「创建租户」** |
| 3 | 填写 **Admin Secret**（仅保存在浏览器 sessionStorage，关闭标签页后需重填） |
| 4 | 填写租户编码、租户名称、组织编码/名称、管理员邮箱等 |
| 5 | 点击 **「创建租户并生成 API Key」** |
| 6 | 将弹窗中的 **API Key、Tenant ID、Org ID** 交给租户管理员（仅展示一次） |

租户管理员在 **连接设置** 中粘贴上述信息即可使用 Dashboard 与 SDK。

---

## 5. 开发者：Python / Java SDK

完成第 3 或 4 节并取得 **API Key** 后，在本地或 CI 中配置环境变量（与 Dashboard「连接设置」一致）。

### 5.1 环境变量

| 变量 | 说明 | 示例 |
|------|------|------|
| `MEMORY_ENGINE_API_BASE` | API 根路径（含 `/api/v1`） | `https://api.memory-engine.example.com/api/v1` |
| `MEMORY_ENGINE_API_KEY` | Bearer Token | `mos_xxxxxxxx` |
| `MEMORY_ENGINE_TENANT_ID` | 租户 ID | `2` |
| `MEMORY_ENGINE_ORG_ID` | 组织 ID | `1` |
| `MEMORY_ENGINE_API_KEY_PREFIX` | 可选；未设置时由完整 Key 自动推导 | — |
| `MEMORY_ENGINE_HTTP_TIMEOUT` | 非 LLM 请求超时（秒） | `30` |
| `MEMORY_ENGINE_PARSE_TIMEOUT` | `Data.parse` 超时（秒，服务端同步 LLM） | `180` |
| `MEMORY_ENGINE_USER_ID` | 可选；**Python SDK 默认用 Key 的 `memory_user_id`，一般不必设置** | — |

远程调用时，本机需能访问 API 域名（公网或 VPN）。

**Python 用户分区**：登录后 SDK 通过 `GET /internal/auth/validate` 取得 `memory_user_id`（等于该 Key 的 `key_prefix`），作为 Mongo 中 `user_id`。同一 Key 下的 `Data.parse` / `Data.get(字段名)` 无需再传业务用户 ID。

### 5.2 安装 SDK

**Python**

```bash
cd sdk/python
pip install -e .
# 或：poetry install
```

**Java**

```bash
cd sdk/java
mvn install
```

详见 [sdk/java/README.md](../sdk/java/README.md)。

### 5.3 最小示例（Python）

```python
import os

os.environ.setdefault("MEMORY_ENGINE_API_BASE", "http://127.0.0.1:6030/api/v1")
os.environ.setdefault("MEMORY_ENGINE_API_KEY", "mos_你的Key")
os.environ.setdefault("MEMORY_ENGINE_TENANT_ID", "2")
os.environ.setdefault("MEMORY_ENGINE_ORG_ID", "1")

from memory_engine_sdk import Data, Schema, SEARCHENUM, ParseInput

# 1. 获取或创建 Schema（EXACT 用完整字段名；LLM 用自然语言，见 5.6）
schema = Schema.getOrCreate("用户年龄", SEARCHENUM.EXACT)

# 2. 解析并写入（默认 user_id = 当前 Key 的 memory_user_id）
mem = Data.parse(schema.name, ParseInput("我今年25岁"))
print("value:", mem.data)

# 3. 读取记忆
row = Data.get(schema.name)
print("get:", row.data if row else None)

# 4. 引用（槽位填充，不调用 LLM）
text = Data.call(
    schema.name,
    "用户<年龄>岁，能否考驾照？",
    "<年龄>",
    mem.data,
    use_llm=False,
)
print("call:", text)
```

### 5.6 LLM 解析规则（Python，推荐）

1. 在 API 服务配置 `OPENAI_BASE_URL` / `OPENAI_API_KEY` / `OPENAI_MODEL`（不要在 SDK 规则里写 Key）。
2. 注册解析规则（按 `rule_name` 版本化；配置不变则跳过）：

```python
from memory_engine_sdk import Schema, Data, ParseInput

Schema.llm_parse(
    "用户性别",
    "extract_gender",
    "从用户输入中抽取「{field}」，只输出 JSON：{\"value\": \"男|女|未知\"}。\n\n用户输入：{text}",
    model="qwen-max-2025-01-25",
    llm_params={"temperature": 0.1},
)

mem = Data.parse(
    "用户性别",
    ParseInput("我是男的，今天天气怎么样"),
    parse_rule_name="extract_gender",
)
```

3. 若 `mem.data` 为 `None`，表示 LLM 未抽到可存储内容，**不会写入** Mongo/Qdrant。
4. `write_rule` 可省略，默认使用 MySQL 中该字段的 `match_method`（OVERWRITE / APPEND / MERGE）。
5. 完整联调脚本：仓库根目录 `examples/sdk_pre_llm_parse.py`（支持 `MEMORY_ENGINE_SCHEMA_LOOKUP_MODE=LLM` 等环境变量）。

超时：同步 LLM 较慢时可 `export MEMORY_ENGINE_PARSE_TIMEOUT=300`。

### 5.4 最小示例（Java）

```java
import com.memoryengine.MemoryEngine;
import com.memoryengine.enums.SearchEnum;
import com.memoryengine.enums.WriteRule;
import com.memoryengine.model.ParseInput;

public class Demo {
  public static void main(String[] args) throws Exception {
    MemoryEngine mos = MemoryEngine.create(
        System.getenv("MEMORY_ENGINE_API_BASE"),
        System.getenv("MEMORY_ENGINE_API_KEY"),
        Long.parseLong(System.getenv("MEMORY_ENGINE_TENANT_ID")));

    var schema = mos.schema().getOrCreate("用户年龄", SearchEnum.SEMANTIC, null);
    var mem = mos.data().parse(
        schema.name(), "user-001", new ParseInput("我今年25岁"), WriteRule.OVERWRITE);
    System.out.println(mem.data());
  }
}
```

### 5.5 高阶能力说明（Python）

| SDK 方法 | 作用 |
|----------|------|
| `Schema.get` / `Schema.getOrCreate` | 查询或创建记忆 Schema；`mode=LLM` 时用自然语言匹配字段名 |
| `Schema.llm_parse` / `Schema.ensure_parse_rule` | 注册 LLM 解析规则（版本化） |
| `Schema.get_parse_rule` | 查询当前生效解析规则元数据 |
| `Data.parse` | 解析自然语言并写入；默认 `user_id`=Key 前缀；可传 `parse_rule_name` |
| `Data.get(schema)` | 按字段读取 KV 记忆（默认分区） |
| `Data.get(schema, user_id)` | 显式指定用户分区 |
| `Data.get` + `RetrieveRule` | LLM/向量等检索（服务端需配置 `OPENAI_*`） |
| `Data.call(..., use_llm=False)` | 槽位替换；`False` 时不调 LLM |
| `Schema.enable_hot_reload` | 订阅 Schema 变更（Canal/changelog） |
| `memory_user_id()` | 当前 Key 对应的 Mongo 分区 ID |

更多 API 语义见根目录 [README.md](../README.md)、[sdk/python/README.md](../sdk/python/README.md)。

---

## 6. HTTP API 开户（无 Dashboard）

### 6.1 自助申请（与 Dashboard 等价）

需请求头 **`X-Supabase-User-Id`**（Supabase 用户 UUID，Dashboard 登录后写入 `localStorage` 的 `MOS_SUPABASE_USER_ID`）。

```bash
export API=https://api.memory-engine.example.com/api/v1
export SUPABASE_UID=你的-supabase-user-uuid

curl -sS -X POST "$API/onboarding/api-key/apply" \
  -H "Content-Type: application/json" \
  -H "X-Supabase-User-Id: $SUPABASE_UID" \
  -d '{
    "email": "you@example.com",
    "display_name": "Your Name",
    "name": "cli"
  }'
```

响应 `data.api_key`、`data.tenant_id`、`data.org_id` 仅首次需保存。

查询已绑定账号（不返回明文 Key）：

```bash
curl -sS "$API/onboarding/me" \
  -H "X-Supabase-User-Id: $SUPABASE_UID"
```

### 6.2 管理员创建租户

```bash
curl -sS -X POST "$API/onboarding/tenant" \
  -H "Content-Type: application/json" \
  -H "X-Admin-Secret: $ADMIN_BOOTSTRAP_SECRET" \
  -d '{
    "tenant_code": "acme",
    "tenant_name": "Acme Corp",
    "org_code": "default",
    "org_name": "Default Org",
    "email": "admin@acme.com",
    "display_name": "Admin",
    "api_key_name": "default"
  }'
```

与 `POST /api/v1/admin/tenants` 行为相同。

### 6.3 已有 Key 时调用业务 API

```bash
export MOS_API_KEY=mos_xxxxxxxx
export TENANT_ID=2
export ORG_ID=1

curl -sS "$API/schema/list" \
  -H "Authorization: Bearer $MOS_API_KEY" \
  -H "X-Tenant-Id: $TENANT_ID" \
  -H "X-Org-Id: $ORG_ID"
```

---

## 7. 本地开发环境快捷方式

无需 Supabase，适合后端/ SDK 联调。

### 7.1 启动依赖与 API

```bash
# 根目录
cp .env.example .env   # 配置 MySQL / Redis / Mongo / Qdrant 等

cd backend && poetry install
poetry run uvicorn memory_engine.main:app --reload --port 6030

# 可选：Temporal、Kafka
cd infra/docker-compose && docker compose up -d temporal kafka
cd backend && poetry run memory-engine-worker
```

### 7.2 导入开发种子（tenant_id = 1）

```bash
mysql -h 127.0.0.1 -u root -p memory_engine \
  < backend/migrations/mysql/002_seed_dev.sql
```

开发用 API Key（Bearer）：

```text
mos_devtest00001ab
```

环境变量示例：

```bash
export MEMORY_ENGINE_API_BASE=http://127.0.0.1:6030/api/v1
export MEMORY_ENGINE_API_KEY=mos_devtest00001ab
export MEMORY_ENGINE_TENANT_ID=1
export MEMORY_ENGINE_ORG_ID=1
```

### 7.3 启动 Dashboard（本地）

```bash
cd dashboard
cp .env.example .env.local
# 编辑 VITE_API_BASE_URL=http://127.0.0.1:6030
npm install && npm run dev
```

在 **设置 → 连接设置** 填入上述 Tenant / Key，或配置 Supabase 后走 **申请 API Key**。

### 7.4 端到端冒烟

```bash
export MOS_API_KEY=mos_devtest00001ab
./backend/scripts/run_e2e.sh
```

---

## 8. 生产部署场景检查清单

| 检查项 | 说明 |
|--------|------|
| API Ingress | `curl https://<API域名>/health` 返回 ok |
| Dashboard Ingress | 能打开登录页，静态资源正常 |
| `VITE_API_BASE_URL` | Dashboard Pod 环境变量，指向 API 根地址（不含 `/api/v1`，前端会自动拼接） |
| `ADMIN_BOOTSTRAP_SECRET` | API Pod 环境变量已配置，供「创建租户」使用 |
| `ONBOARDING_ALLOW_SELF_REGISTER` | 生产若关闭自助注册，用户只能由管理员发 Key |
| MySQL 迁移 | 已执行 `backend/migrations/mysql/*.sql` |
| Temporal Worker | **不在 K8s 部署**；本地调试见 `backend/README.md` |
| LLM | 解析/LLM 检索需配置 `OPENAI_API_KEY` 等 |

部署细节见 [deploy/README.md](../deploy/README.md)。

---

## 9. 常见问题（FAQ）

### Q1：登录 Dashboard 后仍无法访问 Schema 页？

在 **设置 → 连接设置** 中配置有效的 **API Key、Tenant ID、Org ID** 并保存。Supabase 登录与 API 鉴权相互独立。

### Q2：申请 API Key 报错或收不到 Supabase 邮件？

- API 报错：确认 `ONBOARDING_ALLOW_SELF_REGISTER=true`，且 `X-Supabase-User-Id` 已随 Dashboard 登录写入。
- 邮件：见第 3.1 节 Supabase 邮箱确认说明。

### Q3：API Key 丢失怎么办？

明文 Key **无法找回**。在 **申请 API Key** 中再次申请，或由管理员在 **创建租户** 流程中为新 Key（需新用户记录或数据库运维）。

### Q4：本地 SDK 连远程 API 报 401/403？

- 401/403：检查 Key 是否过期/吊销，`X-Tenant-Id` / `X-Org-Id` 是否与 Key 所属租户一致。
- 网络：确认本机能访问生产域名。

### Q5：`Data.parse` / LLM 检索失败？

- 服务端需配置可用的 **OpenAI 兼容** 接口（`OPENAI_BASE_URL`、`OPENAI_API_KEY`、`OPENAI_MODEL`）。仅 KV 读写可不依赖 LLM。
- `Data.parse` 为同步 LLM：客户端默认超时 180s，可设 `MEMORY_ENGINE_PARSE_TIMEOUT`；同时查看 API Pod 日志与 `OPENAI_REQUEST_TIMEOUT_SECONDS`。
- 返回 `value: null` 且未写入：多为 prompt 未抽到有效 JSON，属预期行为，非 HTTP 错误。
- `Schema.get(..., LLM)` 找不到字段：候选列表中无语义**完全相同**的字段名时会返回空，请改用 `EXACT` 或调整描述。
- 404 on `POST /data/create`：常见为 `memory_field_name` 与租户不一致，或 LLM/REGEX 解析到了错误字段名；建议 `MEMORY_ENGINE_SCHEMA_LOOKUP_MODE=EXACT` 并用完整字段名。

### Q6：Dashboard 与 SDK 的 Supabase 用户会同步到 MySQL 吗？

自助申请时会创建/关联 `app_user` 并写入 `supabase_user_id`。未申请 Key 前，仅 Supabase 登录不会产生业务用户记录。

---

## 10. 相关文档索引

| 文档 | 内容 |
|------|------|
| [README.md](../README.md) | 系统能力、API 列表、架构 |
| [PROJECT_STRUCTURE.md](../PROJECT_STRUCTURE.md) | 仓库结构、本地启动 |
| [backend/README.md](../backend/README.md) | 后端、迁移、e2e |
| [deploy/README.md](../deploy/README.md) | 镜像、K8s 部署 |
| [sdk/java/README.md](../sdk/java/README.md) | Java SDK |
| [dashboard/.env.example](../dashboard/.env.example) | Dashboard 前端环境变量 |

---

## 11. Onboarding API 速查

| 方法 | 路径 | 鉴权 | 说明 |
|------|------|------|------|
| GET | `/onboarding/me` | `X-Supabase-User-Id` | 当前用户 profile + Key 前缀列表 |
| POST | `/onboarding/api-key/apply` | `X-Supabase-User-Id` + body | 自助申请 Key |
| GET | `/onboarding/api-keys` | Bearer + `api_key:manage` | 列出 Key |
| POST | `/onboarding/api-keys` | Bearer + `api_key:manage` | 新建 Key |
| POST | `/onboarding/tenant` | `X-Admin-Secret` | 管理员创建租户 |
| POST | `/admin/tenants` | `X-Admin-Secret` | 同上（管理接口） |

---

*文档版本：与 Memory Engine v0.5 功能对齐（含 LLM Schema 查找、解析规则版本化、空解析跳过写入、Python `memory_user_id` 默认分区）。若 UI 或接口有变更，以代码与 [README.md](../README.md) 为准。*
