"""PRE 环境 SDK 联调：Schema + LLM parse + Data 主路径。

LLM 网关与 API Key 由 PRE API 服务环境变量 OPENAI_* 提供；
解析规则里只配置 model 名、prompt、llm_params（temperature 等）。

运行前：
  cd sdk/python && uv pip install -e .
  export MEMORY_ENGINE_API_BASE=http://127.0.0.1:6030/api/v1
  export MEMORY_ENGINE_API_KEY=mos_xxx          # 申请 Key 时一次性展示的完整密钥（必填）
  # export MEMORY_ENGINE_API_KEY_PREFIX=mos_xxx # 可选；不设置则从完整 Key 自动推导
  export MEMORY_ENGINE_TENANT_ID=2
  export MEMORY_ENGINE_ORG_ID=2
  # export MEMORY_ENGINE_USER_ID=end_user_123   # 可选；非空时覆盖 Key 的 memory_user_id（Mongo/Qdrant 分区）
"""
import os

from memory_engine_sdk import WRITERULE

"""
os.environ.setdefault("MEMORY_ENGINE_API_BASE", "http://127.0.0.1:6030/api/v1")
os.environ.setdefault("MEMORY_ENGINE_API_KEY", "mos_替换为你的Key")
os.environ.setdefault("MEMORY_ENGINE_TENANT_ID", "2")
os.environ.setdefault("MEMORY_ENGINE_ORG_ID", "2")
"""

import httpx

from memory_engine_sdk import Data, MemoryEngineConfigError, ParseInput, Schema, SEARCHENUM, RetrieveRule, RETRIEVEENUM

# LLM 模式：SCHEMA 为自然语言描述，服务端列出 deleted=0 的字段名并由大模型选语义完全相同的一项
# EXACT 用完整字段名；REGEX/SEMANTIC 的 name 为匹配模式/查询句
SCHEMA = os.environ.get("MEMORY_ENGINE_SCHEMA_NAME", "居住地")
SCHEMA_LOOKUP_MODE = os.environ.get("MEMORY_ENGINE_SCHEMA_LOOKUP_MODE", "LLM")
# Data.get：EXACT 走 GET /data/get；SEMANTIC/REGEX/LLM 走 POST /data/retrieve（SEMANTIC 需 Qdrant）
RETRIEVE_MODE = os.environ.get("MEMORY_ENGINE_RETRIEVE_MODE", "EXACT")
# 非空时作为 Mongo/Qdrant user_id，替代 MEMORY_ENGINE_API_KEY 关联的 memory_user_id
MEMORY_ENGINE_USER_ID = os.environ.get("MEMORY_ENGINE_USER_ID", "").strip() or None
PARSE_RULE_NAME = "location"

# 与服务端默认 OPENAI_MODEL 一致；None 表示完全使用服务端默认模型
LLM_MODEL = os.environ.get("MEMORY_ENGINE_LLM_MODEL", "qwen-max-2025-01-25")

GENDER_EXTRACT_PROMPT = (
    "从用户输入中抽取「{field}」，只输出具体地址，不要输出json："
    "无法判断则返回空。\n\n"
    "用户输入：{text}"
)

LLM_PARAMS = {
    "temperature": 0.1,
    "top_p": 0.9,
}


def step(name: str) -> None:
    print(f"\n=== {name} ===")


def _retrieve_mode() -> RETRIEVEENUM:
    try:
        return RETRIEVEENUM[RETRIEVE_MODE.upper()]
    except KeyError:
        raise SystemExit(
            f"无效 MEMORY_ENGINE_RETRIEVE_MODE={RETRIEVE_MODE!r}，"
            "可选 EXACT / REGEX / SEMANTIC / LLM"
        ) from None


def _schema_lookup_mode() -> SEARCHENUM:
    try:
        return SEARCHENUM[SCHEMA_LOOKUP_MODE.upper()]
    except KeyError:
        raise SystemExit(
            f"无效 MEMORY_ENGINE_SCHEMA_LOOKUP_MODE={SCHEMA_LOOKUP_MODE!r}，"
            "可选 EXACT / REGEX / SEMANTIC / LLM"
        ) from None


def main() -> None:
    lookup_mode = _schema_lookup_mode()
    step(f"1. Schema.get（mode={lookup_mode.value}）")
    if lookup_mode == SEARCHENUM.LLM:
        print(
            f"LLM 检索：用户输入={SCHEMA!r}；服务端拉取 deleted=0 字段名并由 OPENAI_* 大模型"
            "选择语义完全相同的一项（无需在 SDK 配置 LLM）。",
            flush=True,
        )
    # schema = Schema.get(SCHEMA, lookup_mode)
    # SEARCHENUM.EXACT | REGEX | LLM
    schema = Schema.getOrCreate(SCHEMA, lookup_mode, match_method="APPEND", storage_type="KV_AND_VECTOR")
    assert schema is not None, (
        f"未找到 Schema：lookup={SCHEMA!r} mode={lookup_mode.value}。"
        "LLM 模式：无语义完全相同的字段时返回空；可改 MEMORY_ENGINE_SCHEMA_NAME 或检查租户下字段列表。"
        "EXACT 时请用完整字段名（如「用户性别」）；REGEX 时 name 为正则。"
    )
    print(schema)
    print(f"解析到的字段名（后续步骤均用此名）: {schema.name!r}")

    step("2. 注册 LLM 解析规则（按 rule_name 版本化）")
    # 无记录 → version=1；prompt/model/llm_params 与库中一致 → 跳过；任一变更 → version+1
    parse_rule = Schema.llm_parse(
        schema.name,
        PARSE_RULE_NAME,
        GENDER_EXTRACT_PROMPT,
        model=LLM_MODEL,
        llm_params=LLM_PARAMS,
        system=""
    )
    stored = Schema.get_parse_rule(schema.name, PARSE_RULE_NAME)
    print(f"parse_rule={PARSE_RULE_NAME} version={stored.get('version') if stored else '?'}")
    print("stored config:", stored.get("rule_config_json") if stored else parse_rule.rule_config_json)

    step("3. Data.parse（按 prompt 约定格式抽取）")
    parse_timeout = os.environ.get("MEMORY_ENGINE_PARSE_TIMEOUT", "180")
    print(
        f"正在 POST /data/create（服务端同步调 LLM，客户端超时 {parse_timeout}s）...",
        flush=True,
    )
    field_name = schema.name
    try:
        # 写入规则用 memory_field.match_method；解析规则取 parse_rule 表 deleted=0 且 version 最大
        mem = Data.parse(
            field_name,
            ParseInput("我是男的，今年32岁，家在北京，今天天气怎么样"),
            parse_rule_name=PARSE_RULE_NAME,
            user_id=MEMORY_ENGINE_USER_ID,
        )
    except httpx.HTTPStatusError as exc:
        body = exc.response.text[:500]
        raise SystemExit(
            f"HTTP {exc.response.status_code} POST /data/create "
            f"memory_field_name={field_name!r}\n{body}\n"
            "404 常见原因：tenant/org 与 Dashboard 不一致、字段已删、或 REGEX 解析到了错误字段名。"
            "建议：MEMORY_ENGINE_SCHEMA_NAME=用户性别 MEMORY_ENGINE_SCHEMA_LOOKUP_MODE=EXACT"
        ) from exc
    except httpx.ReadTimeout as exc:
        raise SystemExit(
            "请求超时（客户端 ReadTimeout）：服务端可能在同步调 LLM。"
            "同时请查 API 日志：若已有 POST /data/create 404，应先修字段名/租户，而非 LLM。\n"
            "Pod 内 curl OPENAI_BASE_URL/chat/completions；"
            "OPENAI_REQUEST_TIMEOUT_SECONDS=60；KAFKA_PUBLISH_ENABLED=false；"
            "或 export MEMORY_ENGINE_PARSE_TIMEOUT=300"
        ) from exc
    print("写入 value:", mem.data)
    if mem.data is None:
        print("未抽取到有效记忆（空）：未写入 MongoDB 与 Qdrant。")
    elif isinstance(mem.data, dict):
        print("抽取结果（JSON 模式）value 字段:", mem.data.get("value"))
    else:
        print("抽取结果（text 模式，按 prompt 原文）:", mem.data)

    retrieve_mode = _retrieve_mode()
    step(f"4. Data.get 读取（{retrieve_mode.value}）")
    # 正确：Data.get(schema_name) — 默认 EXACT，user_id=memory_user_id（Key 前缀）
    # 错误示例（勿用）：
    #   Data.get(name, RETRIEVEENUM.EXACT)     → 第二参是 user_id，会变成 user_id="EXACT"
    #   Data.get(name, rule=RETRIEVEENUM.REGEX) → rule 须为 RetrieveRule，不能是枚举
    if retrieve_mode == RETRIEVEENUM.SEMANTIC:
        print(
            "SEMANTIC 依赖服务端 Qdrant：QDRANT_URL 须为 API 根（如 http://host:6333，勿带 /dashboard）；"
            "字段 storage_type 需 VECTOR 或 KV_AND_VECTOR 才会写入向量索引。",
            flush=True,
        )
    try:
        row = Data.get(
            schema.name,
            rule=RetrieveRule(RETRIEVEENUM.SEMANTIC),
            user_id=MEMORY_ENGINE_USER_ID,
        )
    except httpx.HTTPStatusError as exc:
        body = exc.response.text[:500]
        raise SystemExit(
            f"HTTP {exc.response.status_code} POST /data/retrieve mode={retrieve_mode.value}\n{body}\n"
            "SEMANTIC 500 常见原因：PRE 未配置 QDRANT_URL 或 URL 带 /dashboard 导致 Qdrant 404。"
            "联调建议 MEMORY_ENGINE_RETRIEVE_MODE=EXACT；修 Qdrant 后再试 SEMANTIC。"
        ) from exc
    print(row)
    print("读出 value:", row.data)

    step("5. Data.call 槽位填充（不调 LLM）")
    slot_value = row.data
    if isinstance(slot_value, dict):
        slot_value = slot_value.get("value", slot_value)
    text = Data.call(
        schema.name,
        "请问用户<性别>是否符合参军条件？",
        "<性别>",
        slot_value,
        use_llm=False,
    )
    print("call 结果:", text)

    print("\n全部步骤完成。")


if __name__ == "__main__":
    try:
        main()
    except MemoryEngineConfigError as exc:
        raise SystemExit(str(exc)) from None
