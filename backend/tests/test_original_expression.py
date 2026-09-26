"""Tests for original expression span extraction."""

from memory_engine.services.original_expression import extract_original_expression


def test_extract_prefers_exact_substring() -> None:
    query = "用户说：PRD 里不要堆系统术语，业务同学看不懂。"
    value = "用户厌恶难懂系统术语，偏好业务可读表达。"
    # LCS / clause should land on the quoted-like clause
    span = extract_original_expression(query, value)
    assert span is not None
    assert "系统术语" in span
    assert len(span) <= 120


def test_extract_exact_value_in_query() -> None:
    query = "明天下午开会讨论会员体系方案"
    value = "明天下午开会"
    assert extract_original_expression(query, value) == "明天下午开会"


def test_extract_explicit_overrides() -> None:
    assert (
        extract_original_expression(
            "很长的原文内容……",
            "解析结果",
            explicit="精确原话片段",
        )
        == "精确原话片段"
    )


def test_extract_empty_returns_none() -> None:
    assert extract_original_expression("", "x") is None
    assert extract_original_expression("query", "") is None
