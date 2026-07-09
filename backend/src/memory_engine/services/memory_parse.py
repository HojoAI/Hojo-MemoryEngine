"""Parse raw input into memory value via parse_rule + LLM."""

from __future__ import annotations

import json
import re
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from memory_engine.config import get_settings
from memory_engine.core.context import RequestContext
from memory_engine.integrations import llm_client
from memory_engine.schemas.memory_field import LLMConfig
from memory_engine.models.schema import CapabilityRegistry
from memory_engine.services import billing_service, rules as rule_service

_PARSE_SYSTEM = (
    "Extract structured memory from user text. Reply JSON only with fields requested "
    "in the task. Use null for unknown fields."
)

# ``text``: store LLM body per user prompt (no JSON coercion). ``json``: legacy JSON parse.
_VALID_OUTPUT_FORMATS = frozenset({"text", "json"})


def _is_nullish_scalar(value: Any) -> bool:
    """True for None, blank string, or literal empty markers from LLM output."""
    if value is None:
        return True
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return True
        lowered = text.lower()
        if lowered in ("null", "none", '""', "''", "n/a", "-", "无", "未知"):
            return True
        if len(text) >= 2 and text[0] == text[-1] and text[0] in ('"', "'"):
            if not text[1:-1].strip():
                return True
    return False


def parse_result_is_empty(value: Any) -> bool:
    """Whether LLM parse produced no storable memory (skip Mongo/Qdrant write)."""
    if _is_nullish_scalar(value):
        return True
    if isinstance(value, dict):
        if not value:
            return True
        if value.get("has_memory") is False:
            return True
        if "value" in value:
            return _is_nullish_scalar(value["value"])
        # Non-JSON LLM output or no parse_rule — wrapped query only.
        keys = set(value.keys())
        if keys <= {"query", "extra"}:
            return True
        if "parsed_text" in keys:
            return True
    if isinstance(value, list):
        return not value or all(parse_result_is_empty(item) for item in value)
    return False


def apply_parse_prompt_template(
    template: str,
    *,
    field: str,
    text: str,
    language: str | None = None,
) -> str:
    """Substitute ``{field}``, ``{text}`` and ``{language}``; leave other braces (e.g. JSON) intact."""
    result = template.replace("{field}", field).replace("{text}", text)
    if language:
        result = result.replace("{language}", language)
    return result


def parse_output_format(cfg: dict) -> str:
    """Resolve ``rule_config_json.output_format`` (default ``json`` for backward compatibility)."""
    fmt = cfg.get("output_format", "json")
    return fmt if fmt in _VALID_OUTPUT_FORMATS else "json"


def parse_system_message(cfg: dict, *, output_format: str) -> str:
    """System prompt: explicit ``system`` in rule; else JSON helper only for ``json`` mode."""
    if "system" in cfg:
        return cfg["system"] or ""
    if output_format == "json":
        return _PARSE_SYSTEM
    return ""


def strip_llm_markdown_fence(text: str) -> str:
    """Remove optional markdown code fences without changing inner content."""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return text.strip()


def normalize_llm_parse_output(
    raw: str,
    *,
    output_format: str,
    raw_query: str,
    extra: dict | None = None,
) -> Any:
    """Turn LLM completion into storable value per ``output_format``."""
    text = strip_llm_markdown_fence(raw)
    if output_format == "text":
        if _is_nullish_scalar(text):
            return None
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                if parsed.get("has_memory") is False:
                    return None
                if "value" in parsed and _is_nullish_scalar(parsed["value"]):
                    return None
        except json.JSONDecodeError:
            pass
        return text
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            if extra:
                parsed.setdefault("extra", {}).update(extra)
            return parsed
        if _is_nullish_scalar(parsed):
            return None
    except json.JSONDecodeError:
        pass
    return {"query": raw_query, "parsed_text": raw, "extra": extra or {}}


def _resolve_parse_llm(cfg: dict) -> tuple[str | None, str | None, str | None, dict[str, Any]]:
    """Resolve model + optional overrides. Credentials default to server ``OPENAI_*`` env.

    ``cfg["llm"]`` may be a model name string (``"qwen-max-2025-01-25"``) or a legacy dict
    with ``model`` / ``model_name`` and optional ``base_url`` / ``api_key``.
    """
    params: dict[str, Any] = dict(cfg.get("llm_params") or {})
    raw = cfg.get("llm")
    if isinstance(raw, str):
        name = raw.strip() or None
        return name, None, None, params
    if isinstance(raw, dict):
        model = raw.get("model_name") or raw.get("model")
        if isinstance(model, str):
            model = model.strip() or None
        return (
            model,
            raw.get("base_url"),
            raw.get("api_key"),
            params,
        )
    return None, None, None, params


def _llm_cfg_from_json(cfg: dict | None) -> LLMConfig | None:
    if not cfg:
        return None
    model, base_url, api_key, _ = _resolve_parse_llm(cfg)
    if not any((model, base_url, api_key)):
        return None
    return LLMConfig(base_url=base_url, api_key=api_key, model_name=model)


# Translate 函数
async def _translate_value(
    value: Any,
    language: str,
    session: AsyncSession,
    ctx: RequestContext,
) -> Any:
    """Translate value to target language via LLM, preserving original data type.

    - str: translate and return str
    - dict/list: translate all text values inside, return same type with same structure
    - int/float/bool/None: return as-is (no language to translate)
    """
    if not value:
        return value

    language = language or "en"

    # 纯字符串翻译
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return value

        settings = get_settings()

        prompt = (
            f"Translate the following text to {language}. "
            f"If the text is already in {language}, output it exactly as provided. "
            f"Output ONLY the translated text, no explanation, no extra formatting.\n\n"
            f"Text: {value}"
        )
        raw, pt, ct = await llm_client.chat_completion(
            prompt,
            system="You are a translator. Output only the translated text, no explanation.",
            model=settings.openai_model,
        )
        await billing_service.emit_llm_completion(
            session, ctx, model_name=settings.openai_model, prompt_tokens=pt, completion_tokens=ct
        )
        translated = raw.strip() if raw else value
        return translated

    # dict / list：Python 保持结构，LLM 只翻译字符串叶子节点
    if isinstance(value, (dict, list)):
        text_items: list[tuple[tuple[Any, ...], str]] = []

        def collect_text_leaves(node: Any, path: tuple[Any, ...] = ()) -> None:
            if isinstance(node, dict):
                for key, child in node.items():
                    collect_text_leaves(child, path + (key,))
                return
            if isinstance(node, list):
                for index, child in enumerate(node):
                    collect_text_leaves(child, path + (index,))
                return
            if isinstance(node, str) and node.strip():
                text_items.append((path, node))

        collect_text_leaves(value)
        if not text_items:
            return value

        payload = [
            {"id": index, "text": text}
            for index, (_, text) in enumerate(text_items)
        ]

        settings = get_settings()
        prompt = (
            f"Translate each item.text in the following JSON array to {language}. "
            f"If item.text is already in {language}, keep it exactly as provided. "
            f"Keep every id unchanged. "
            f"Output ONLY the translated JSON array, no explanation, no markdown fences.\n\n"
            f"JSON:\n{json.dumps(payload, ensure_ascii=False)}"
        )
        raw, pt, ct = await llm_client.chat_completion(
            prompt,
            system=(
                "You are a translator. Output only a JSON array with unchanged ids "
                "and translated text values."
            ),
            model=settings.openai_model,
        )
        await billing_service.emit_llm_completion(
            session, ctx, model_name=settings.openai_model, prompt_tokens=pt, completion_tokens=ct
        )
        translated_text = strip_llm_markdown_fence(raw or "")
        try:
            translated_rows = json.loads(translated_text)
        except json.JSONDecodeError:
            # LLM 返回格式异常时回退到原值
            return value

        if not isinstance(translated_rows, list) or len(translated_rows) != len(text_items):
            return value

        translated_by_id: dict[int, str] = {}
        for row in translated_rows:
            if not isinstance(row, dict):
                return value
            row_id = row.get("id")
            row_text = row.get("text")
            if not isinstance(row_id, int) or not isinstance(row_text, str):
                return value
            translated_by_id[row_id] = row_text

        if set(translated_by_id) != set(range(len(text_items))):
            return value

        translations = {
            path: translated_by_id[index]
            for index, (path, _) in enumerate(text_items)
        }

        def rebuild_with_translations(node: Any, path: tuple[Any, ...] = ()) -> Any:
            if isinstance(node, dict):
                return {
                    key: rebuild_with_translations(child, path + (key,))
                    for key, child in node.items()
                }
            if isinstance(node, list):
                return [
                    rebuild_with_translations(child, path + (index,))
                    for index, child in enumerate(node)
                ]
            translated = translations.get(path)
            return translated if translated is not None else node

        return rebuild_with_translations(value)

    # int/float/bool/None — 无文本可翻译，直接返回
    return value


# 解析记忆内容
async def parse_with_rule(
    session: AsyncSession,
    ctx: RequestContext,
    *,
    memory_field_name: str,
    rule_name: str | None,
    raw_query: str,
    extra: dict | None = None,
    output_language: str | None = None,
) -> Any:
    """Run LLM parse pipeline when parse_rule exists; else wrap query."""
    
    if not rule_name:
        raw_query = await _translate_value(raw_query, output_language or "en", session, ctx)
        return {"query": raw_query, "extra": extra or {}}

    row = await rule_service.get_active_parse(session, ctx, memory_field_name, rule_name)
    if not row:
        raw_query = await _translate_value(raw_query, output_language or "en", session, ctx)
        return {"query": raw_query, "extra": extra or {}}

    cfg = dict(row.rule_config_json or {})
    if row.capability_id:
        cap = await session.get(CapabilityRegistry, row.capability_id)
        if cap and cap.config_json:
            cap_cfg = cap.config_json
            cfg = {**cap_cfg, **cfg} # 模型的一些配置来自capability，prompt来自rule_config_json，二者合并，rule_config_json优先级高（同名的key根据后者配置）
            if "default_prompt_template" in cap_cfg and "prompt" not in cfg:
                cfg["prompt"] = cap_cfg["default_prompt_template"]
    output_format = parse_output_format(cfg) # 就是从配置里读output_format，决定LLM以什么格式返回结果
    prompt_template = cfg.get(
        "prompt",
        (
            "Extract memory for field '{field}'. User text:\n{text}\nOutput language: {language}"
            if output_format == "text"
            else "Extract memory for field '{field}'. User text:\n{text}\nOutput language: {language}\nReply JSON."
        ),
    )
    # 把模板里的 {field}、{text}、{language} 替换成实际值
    user_prompt = apply_parse_prompt_template(
        prompt_template,
        field=memory_field_name,
        text=raw_query,
        language=output_language or "en",
    )
    
    model, base_url, api_key, llm_params = _resolve_parse_llm(cfg)
    
    settings = get_settings()
    model = model or settings.openai_model
    
    raw, pt, ct = await llm_client.chat_completion(
        user_prompt,
        system=parse_system_message(cfg, output_format=output_format),
        base_url=base_url,
        api_key=api_key,
        model=model,
        llm_params=llm_params,
    )
    
    await billing_service.emit_llm_completion(
        session, ctx, model_name=model, prompt_tokens=pt, completion_tokens=ct
    )
    # 按output_format清洗成可存储的结果
    return normalize_llm_parse_output(
        raw,
        output_format=output_format,
        raw_query=raw_query,
        extra=extra,
    )
