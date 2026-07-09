# Memory Engine Python SDK

包名：`memory_engine_sdk`，与后端 `POST /api/v1` 对齐。

## 安装

```bash
cd sdk/python
uv pip install -e .
# 或：pip install -e .
```

## 环境变量

| 变量 | 说明 |
|------|------|
| `MEMORY_ENGINE_API_BASE` | API 根路径，如 `http://127.0.0.1:6030/api/v1` |
| `MEMORY_ENGINE_API_KEY` | 申请 Key 时返回的**完整密钥**（Bearer，**必填**） |
| `MEMORY_ENGINE_API_KEY_PREFIX` | 可选；Dashboard「前缀」列。未设置时由完整 Key 前 16 字符自动推导 |
| `MEMORY_ENGINE_TENANT_ID` / `MEMORY_ENGINE_ORG_ID` | 租户与组织 |
| `MEMORY_ENGINE_HTTP_TIMEOUT` | 非 LLM 请求超时（秒），默认 `30` |
| `MEMORY_ENGINE_PARSE_TIMEOUT` | `Data.parse` 超时（秒）；服务端同步调 LLM，默认 `180` |

### 用户分区（`memory_user_id`）

`Data.parse` / `Data.get(schema_name)` 默认使用当前 Key 对应的 **`memory_user_id`**（等于 `key_prefix`，由 `GET /internal/auth/validate` 返回）作为 Mongo/Qdrant `user_id`，**一般无需再传 `user_id`**。多终端用户可显式传入 `Data.parse(..., user_id="...")`、`Data.get(schema, user_id="...")` 或 `Data.get(schema, rule=..., user_id="...")`（非空时覆盖 Key 分区）。

```python
from memory_engine_sdk import memory_user_id
print(memory_user_id())
```

**完整 Key 丢失**：库中只存哈希，无法找回；请在 Dashboard「设置 → 申请 API Key」重新申请。

### LLM 凭证

解析与 `SEARCHENUM.LLM` 的 Schema 查找使用 **API 服务** 环境变量 `OPENAI_BASE_URL` / `OPENAI_API_KEY` / `OPENAI_MODEL`。**不要在 SDK 的 parse 规则里配置 API Key**；`RetrieveRule` / `Data.call` 仍可通过 `LLM(...)` 按请求覆盖。

## Schema 查询模式

| `SEARCHENUM` | `Schema.get` / `getOrCreate` 的 `name` 含义 |
|--------------|---------------------------------------------|
| `EXACT` | 完整字段名 |
| `REGEX` | 对字段名的正则 |
| `SEMANTIC` | 语义相似度（向量） |
| `LLM` | 自然语言描述；服务端列出 `deleted=0` 字段名，大模型仅在**语义完全相同**时返回一项 |

```python
from memory_engine_sdk import Schema, SEARCHENUM

schema = Schema.getOrCreate("年龄", SEARCHENUM.LLM)  # 或 EXACT 用「用户年龄」
```

## 注册 LLM 解析规则（推荐）

`Schema.llm_parse` 构建 `rule_config_json` 并默认调用 `ensure_parse_rule`：

- 无记录 → `POST /schema/parse/create`（version=1）
- `prompt` / `llm` / `llm_params` 与当前生效行一致 → 跳过
- 任一变更 → 新版本（version+1）

Prompt 模板占位符仅 **`{field}`**、**`{text}`**（其它花括号如 JSON 不会被误替换）。

```python
from memory_engine_sdk import Schema

Schema.llm_parse(
    "用户性别",
    "extract_gender",
    "从用户输入中抽取「{field}」，只输出 JSON：{\"value\": \"男|女|未知\"}。\n\n用户输入：{text}",
    model="qwen-max-2025-01-25",
    llm_params={"temperature": 0.1, "top_p": 0.9},
    system="只输出合法 JSON。",  # 可选
)
```

手动控制注册：

```python
from memory_engine_sdk import ParseRule

rule = ParseRule.llm_parse("extract_gender", "...", model="qwen-max-2025-01-25")
status = Schema.ensure_parse_rule("用户性别", rule)  # "created" | "skipped" | "versioned"
stored = Schema.get_parse_rule("用户性别", "extract_gender")
```

## 解析并写入记忆

```python
from memory_engine_sdk import Data, ParseInput, WRITERULE

mem = Data.parse(
    "用户性别",
    ParseInput("我是男的，今天天气怎么样"),
    parse_rule_name="extract_gender",
)
# write_rule 省略 → 使用 memory_field.match_method（OVERWRITE/APPEND/MERGE）
# mem.data 为 None → LLM 未抽到可存储 value，服务端未写 Mongo/Qdrant
```

## MERGE 模式（大模型融合，merge_rule）

`match_method="MERGE"` **即**大模型融合写入策略：须注册 **merge_rule**（含 model、llm_params、prompt；prompt 必须含 `{old_value}`、`{new_value}`）。不存在单独的 `LLM` 写入类型。

```python
from memory_engine_sdk import Schema, SEARCHENUM, MergeRule, Data, ParseInput

MERGE_PROMPT = (
    "字段：{field}\n已有：{old_value}\n新增：{new_value}\n"
    "输出融合后的一句自然语言，不要 JSON。"
)

Schema.getOrCreate(
    "人脉知识",
    SEARCHENUM.EXACT,
    match_method="MERGE",
    storage_type="KV_AND_VECTOR",
    merge_rule=MergeRule.llm_merge(
        "social_knowledge_merge_v1",
        MERGE_PROMPT,
        model="qwen-max-2025-01-25",
        llm_params={"temperature": 0.1, "top_p": 0.9},
    ),
)

mem = Data.parse(
    "人脉知识",
    ParseInput("欧姐是产品VP"),
    parse_rule_name="social_knowledge_v1",
    merge_rule_name="social_knowledge_merge_v1",
)
```

- merge prompt **必须**包含 `{old_value}` 与 `{new_value}`。
- `llm` / `llm_params` 写入 `merge_rule.rule_config_json`；API Key 仍走服务端 `OPENAI_*`。
- 无 merge_rule 时，已有数据的 MERGE 写入会返回 422。

## 读取、检索、引用

```python
from memory_engine_sdk import Data, RetrieveRule, RETRIEVEENUM, LLM, Prompt

row = Data.get("用户性别")  # 默认 memory_user_id 分区
# row = Data.get("用户性别", user_id="end_user_123")
# row = Data.get("用户性别", rule=RetrieveRule(RETRIEVEENUM.SEMANTIC), user_id="end_user_123")

# 显式 LLM 检索（可选在 RetrieveRule 中带 LLM 覆盖）
# mem = Data.get("用户性别", RetrieveRule(RETRIEVEENUM.LLM, LLM(...), Prompt("...")))

text = Data.call(
    "用户性别",
    "用户<性别>是否符合参军？",
    "<性别>",
    row.data if row else {},
    use_llm=False,  # 仅槽位替换
)
```

## `rule_config_json` 形态（parse）

```json
{
  "prompt": "... {field} ... {text}",
  "system": "",
  "output_format": "text",
  "llm": "qwen-max-2025-01-25",
  "llm_params": {"temperature": 0.1, "top_p": 0.9}
}
```

- **`output_format`**：`text`（默认，`Schema.llm_parse`）按 prompt 约定原样存储 LLM 输出，服务端不做 JSON 解析；`json` 用于 `llm_field_extract` 等需 `{"value": ...}` 的场景。
- **`system`**：省略且 `output_format=json` 时使用服务端 JSON 辅助 system；`text` 模式默认空 system。

`llm` 可为模型名字符串，或遗留对象 `{ "model_name": "...", "base_url": "...", "api_key": "..." }`（不推荐在规则中放 Key）。

## 热更新

```python
Schema.enable_hot_reload(poll_interval_ms=2000)  # Canal → changelog 长轮询
Schema.disable_hot_reload()
```

## 完整示例

仓库根目录 [`examples/sdk_pre_llm_parse.py`](../../examples/sdk_pre_llm_parse.py)（PRE 环境变量见文件头注释）。

更多说明：[docs/user-guide.md](../../docs/user-guide.md)、根目录 [README.md](../../README.md)。
