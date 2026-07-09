"""Tests for parse-rule LLM config resolution."""

from memory_engine.services.memory_parse import (
    _resolve_parse_llm,
    apply_parse_prompt_template,
    normalize_llm_parse_output,
    parse_output_format,
    parse_result_is_empty,
    parse_system_message,
)


def test_apply_parse_prompt_template_allows_json_braces() -> None:
    template = (
        "抽取「{field}」，输出 JSON：{\"value\": \"男\"}。\n用户输入：{text}"
    )
    out = apply_parse_prompt_template(
        template,
        field="用户性别",
        text="我是男的",
    )
    assert '{"value": "男"}' in out
    assert "用户性别" in out
    assert "我是男的" in out
    assert "{field}" not in out


def test_resolve_llm_model_string() -> None:
    model, base, key, params = _resolve_parse_llm(
        {
            "llm": "qwen-max-2025-01-25",
            "llm_params": {"temperature": 0.2, "top_p": 0.8},
        }
    )
    assert model == "qwen-max-2025-01-25"
    assert base is None
    assert key is None
    assert params == {"temperature": 0.2, "top_p": 0.8}


def test_parse_result_is_empty_null_value() -> None:
    assert parse_result_is_empty({"value": None}) is True
    assert parse_result_is_empty({"value": "null"}) is True
    assert parse_result_is_empty({"value": ""}) is True
    assert parse_result_is_empty({"value": "男"}) is False
    assert parse_result_is_empty({"value": "未知"}) is True
    assert parse_result_is_empty({"has_memory": False, "value": ""}) is True


def test_parse_result_is_empty_llm_empty_markers() -> None:
    assert parse_result_is_empty('""') is True
    assert parse_result_is_empty("''") is True
    assert parse_result_is_empty('  ""  ') is True


def test_parse_result_is_empty_query_fallback() -> None:
    assert parse_result_is_empty({"query": "hi", "extra": {}}) is True
    assert parse_result_is_empty({"query": "hi", "parsed_text": "{bad"}) is True


def test_parse_output_format_defaults_and_override() -> None:
    assert parse_output_format({}) == "json"
    assert parse_output_format({"output_format": "text"}) == "text"
    assert parse_output_format({"output_format": "invalid"}) == "json"


def test_parse_system_message_text_mode_no_default_json() -> None:
    assert parse_system_message({}, output_format="text") == ""
    assert parse_system_message({"system": "自定义"}, output_format="text") == "自定义"
    assert "JSON" in parse_system_message({}, output_format="json")


def test_normalize_llm_parse_output_text_mode() -> None:
    assert normalize_llm_parse_output("32", output_format="text", raw_query="q") == "32"
    assert normalize_llm_parse_output("  ", output_format="text", raw_query="q") is None
    assert normalize_llm_parse_output('""', output_format="text", raw_query="q") is None
    assert (
        normalize_llm_parse_output(
            '{"has_memory": false, "value": ""}', output_format="text", raw_query="q"
        )
        is None
    )
    assert (
        normalize_llm_parse_output('{"value": ""}', output_format="text", raw_query="q")
        is None
    )
    assert (
        normalize_llm_parse_output('{"value": 32}', output_format="text", raw_query="q")
        == '{"value": 32}'
    )


def test_normalize_llm_parse_output_json_mode() -> None:
    assert normalize_llm_parse_output(
        '{"value": "男"}', output_format="json", raw_query="q"
    ) == {"value": "男"}
    assert normalize_llm_parse_output('""', output_format="json", raw_query="q") is None
    fallback = normalize_llm_parse_output("纯文本", output_format="json", raw_query="hi")
    assert fallback["parsed_text"] == "纯文本"
    assert fallback["query"] == "hi"


def test_parse_result_is_empty_scalar_text() -> None:
    assert parse_result_is_empty("32") is False
    assert parse_result_is_empty("") is True


def test_resolve_llm_legacy_dict() -> None:
    model, base, key, params = _resolve_parse_llm(
        {
            "llm": {"model_name": "gpt-4o", "base_url": "https://x/v1", "api_key": "sk-1"},
        }
    )
    assert model == "gpt-4o"
    assert base == "https://x/v1"
    assert key == "sk-1"
    assert params == {}
