"""Merge existing and new memory values via merge_rule + LLM (MERGE match_method)."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from memory_engine.config import get_settings
from memory_engine.core.context import RequestContext
from memory_engine.core.exceptions import ValidationError
from memory_engine.integrations import llm_client
from memory_engine.models.schema import CapabilityRegistry
from memory_engine.services import billing_service, rules as rule_service
from memory_engine.services.memory_parse import (
    _is_nullish_scalar,
    _resolve_parse_llm,
    parse_system_message,
    strip_llm_markdown_fence,
)

MERGE_PROMPT_SLOT_OLD = "{old_value}"
MERGE_PROMPT_SLOT_NEW = "{new_value}"


def validate_merge_prompt(template: str) -> None:
    """Require ``{old_value}`` and ``{new_value}`` placeholders in merge prompt."""
    if MERGE_PROMPT_SLOT_OLD not in template or MERGE_PROMPT_SLOT_NEW not in template:
        raise ValidationError(
            "merge_rule prompt must include "
            f"{MERGE_PROMPT_SLOT_OLD!r} and {MERGE_PROMPT_SLOT_NEW!r} placeholders"
        )


def apply_merge_prompt_template(
    template: str,
    *,
    field: str,
    old_value: str,
    new_value: str,
) -> str:
    """Substitute ``{field}``, ``{old_value}``, ``{new_value}`` in merge prompt."""
    return (
        template.replace("{field}", field)
        .replace(MERGE_PROMPT_SLOT_OLD, old_value)
        .replace(MERGE_PROMPT_SLOT_NEW, new_value)
    )


def normalize_llm_merge_output(raw: str) -> str | None:
    """Turn LLM merge completion into storable text."""
    text = strip_llm_markdown_fence(raw)
    if _is_nullish_scalar(text):
        return None
    return text


def _value_to_merge_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


async def merge_with_rule(
    session: AsyncSession,
    ctx: RequestContext,
    *,
    memory_field_name: str,
    old_value: Any,
    new_value: Any,
    rule_name: str,
) -> Any:
    """Fuse old and new memory via LLM merge rule; fallback to new_value."""
    row = await rule_service.get_active_merge(session, ctx, memory_field_name, rule_name)
    if not row:
        return new_value

    old_text = _value_to_merge_text(old_value)
    new_text = _value_to_merge_text(new_value)
    if not old_text:
        return new_value
    if not new_text:
        return old_value

    cfg = dict(row.rule_config_json or {})
    if row.capability_id:
        cap = await session.get(CapabilityRegistry, row.capability_id)
        if cap and cap.config_json:
            cap_cfg = cap.config_json
            cfg = {**cap_cfg, **cfg}
            if "default_prompt_template" in cap_cfg and "prompt" not in cfg:
                cfg["prompt"] = cap_cfg["default_prompt_template"]

    prompt_template = cfg.get("prompt") or ""
    validate_merge_prompt(prompt_template)
    user_prompt = apply_merge_prompt_template(
        prompt_template,
        field=memory_field_name,
        old_value=old_text,
        new_value=new_text,
    )
    model, base_url, api_key, llm_params = _resolve_parse_llm(cfg)
    settings = get_settings()
    model = model or settings.openai_model
    output_format = cfg.get("output_format", "text")

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

    merged = normalize_llm_merge_output(raw)
    return merged if merged is not None else new_value
