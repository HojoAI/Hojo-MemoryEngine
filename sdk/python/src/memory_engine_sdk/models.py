"""SDK data models."""

from dataclasses import dataclass
from typing import Any

from memory_engine_sdk.enums import RETRIEVEENUM


@dataclass
class LLM:
  base_url: str
  api_key: str
  model_name: str


@dataclass
class Prompt:
  text: str


@dataclass
class ParseRule:
  """Parse rule + optional capability binding."""

  rule_name: str
  capability_name: str | None = None
  module_name: str | None = None
  service_name: str | None = None
  rule_config_json: dict[str, Any] | None = None

  @classmethod
  def llm_parse(
    cls,
    rule_name: str,
    prompt: str,
    *,
    model: str | None = None,
    llm_params: dict[str, Any] | None = None,
    system: str | None = None,
    output_format: str = "text",
  ) -> "ParseRule":
    """Build parse rule config locally (no HTTP).

    To also register on the server, use :meth:`Schema.llm_parse` in ``client``.
    API credentials (``OPENAI_*``) stay on the server; ``prompt`` must include
    ``{field}`` and ``{text}``.

    ``output_format``:
      - ``text`` (default): server stores LLM body as-is per your prompt.
      - ``json``: server parses JSON and uses legacy ``{"value": ...}`` helpers.
    """
    cfg: dict[str, Any] = {
      "prompt": prompt,
      "system": system or "",
      "output_format": output_format,
    }
    if model:
      cfg["llm"] = model
    if llm_params:
      cfg["llm_params"] = llm_params
    return cls(rule_name=rule_name, rule_config_json=cfg)

  @classmethod
  def llm_field_extract(
    cls,
    rule_name: str,
    *,
    llm: "LLM | None" = None,
    model: str | None = None,
    value_key: str = "value",
    extra_prompt: str | None = None,
    llm_params: dict[str, Any] | None = None,
  ) -> "ParseRule":
    """Convenience wrapper around :meth:`llm_parse` with a default prompt template."""
    if llm is not None:
      model = model or llm.model_name
    prompt = extra_prompt or (
      "从用户输入中抽取字段「{field}」，只输出 JSON，格式："
      f'{{"{value_key}": "简短中文值"}}。'
      f"无法判断则 {value_key} 为 null。\n\n用户输入：{{text}}"
    )
    return cls.llm_parse(
      rule_name,
      prompt,
      model=model,
      llm_params=llm_params,
      output_format="json",
    )


@dataclass
class MergeRule:
  """Merge rule for ``match_method=MERGE`` (LLM fusion; slots ``{old_value}``, ``{new_value}``)."""

  rule_name: str
  rule_config_json: dict[str, Any] | None = None

  @classmethod
  def llm_merge(
    cls,
    rule_name: str,
    prompt: str,
    *,
    model: str | None = None,
    llm_params: dict[str, Any] | None = None,
    system: str | None = None,
    output_format: str = "text",
  ) -> "MergeRule":
    """Build merge rule config. ``prompt`` must include ``{old_value}`` and ``{new_value}``."""
    if "{old_value}" not in prompt or "{new_value}" not in prompt:
      raise ValueError("merge prompt must include {old_value} and {new_value}")
    cfg: dict[str, Any] = {
      "prompt": prompt,
      "system": system or "",
      "output_format": output_format,
    }
    if model:
      cfg["llm"] = model
    if llm_params:
      cfg["llm_params"] = llm_params
    return cls(rule_name=rule_name, rule_config_json=cfg)


@dataclass
class ParseInput:
  query: str
  extra: dict[str, Any] | None = None


@dataclass
class RetrieveRule:
  method: RETRIEVEENUM
  llm: LLM | None = None
  prompt: Prompt | None = None


@dataclass
class SchemaModel:
  name: str
  id: int | None = None


@dataclass
class MemoryData:
  user_id: str
  data: Any
  memory_field_name: str | None = None
  retrieve_result: str | None = None
