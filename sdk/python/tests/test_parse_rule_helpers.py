"""Unit tests for SDK parse-rule helpers (no HTTP)."""

from memory_engine_sdk.client import _llm_parse_config_matches, _parse_rule_create_body
from memory_engine_sdk.models import ParseRule


def test_llm_parse_stores_model_string_and_params() -> None:
    rule = ParseRule.llm_parse(
        "extract_gender",
        "prompt {field} {text}",
        model="qwen-max-2025-01-25",
        llm_params={"temperature": 0.1, "top_p": 0.9},
    )
    assert rule.rule_config_json["llm"] == "qwen-max-2025-01-25"
    assert rule.rule_config_json["llm_params"]["temperature"] == 0.1
    assert rule.rule_config_json["output_format"] == "text"
    assert "api_key" not in str(rule.rule_config_json)


def test_llm_field_extract_delegates_to_llm_parse() -> None:
    rule = ParseRule.llm_field_extract(
        "r1",
        model="qwen-max",
        llm_params={"temperature": 0},
    )
    assert rule.rule_config_json["llm"] == "qwen-max"
    assert rule.rule_config_json["output_format"] == "json"
    assert "{field}" in rule.rule_config_json["prompt"]


def test_llm_parse_config_matches_same() -> None:
    desired = ParseRule.llm_parse(
        "extract_gender",
        "prompt {field}",
        model="qwen-max",
        llm_params={"temperature": 0.1},
    )
    existing = {"rule_config_json": desired.rule_config_json, "version": 1}
    assert _llm_parse_config_matches(existing, desired) is True


def test_llm_parse_config_matches_prompt_diff() -> None:
    desired = ParseRule.llm_parse("r", "new prompt", model="qwen-max")
    existing = {
        "rule_config_json": {"prompt": "old prompt", "llm": "qwen-max"},
        "version": 1,
    }
    assert _llm_parse_config_matches(existing, desired) is False


def test_llm_parse_config_matches_params_diff() -> None:
    desired = ParseRule.llm_parse(
        "r",
        "p",
        model="qwen-max",
        llm_params={"temperature": 0.2},
    )
    existing = {
        "rule_config_json": {
            "prompt": "p",
            "llm": "qwen-max",
            "llm_params": {"temperature": 0.1},
        },
    }
    assert _llm_parse_config_matches(existing, desired) is False


def test_parse_rule_create_body() -> None:
    body = _parse_rule_create_body(
        "用户性别",
        ParseRule(
            rule_name="extract_gender",
            rule_config_json={
                "prompt": "hi {text}",
                "llm": "qwen-max",
                "llm_params": {"top_k": 40},
            },
        ),
    )
    assert body["memory_field_name"] == "用户性别"
    assert body["rule_config_json"]["llm"] == "qwen-max"
