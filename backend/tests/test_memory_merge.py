"""Unit tests for LLM memory merge helpers."""

import pytest

from memory_engine.core.exceptions import ValidationError
from memory_engine.services.memory_merge import apply_merge_prompt_template, validate_merge_prompt


def test_apply_merge_prompt_template_substitutes_placeholders() -> None:
    template = "field={field}\nold={old_value}\nnew={new_value}"
    out = apply_merge_prompt_template(
        template,
        field="人脉知识",
        old_value="欧姐，产品VP",
        new_value="欧姐负责整个产品团队",
    )
    assert "field=人脉知识" in out
    assert "old=欧姐，产品VP" in out
    assert "new=欧姐负责整个产品团队" in out


def test_validate_merge_prompt_requires_slots() -> None:
    validate_merge_prompt("old={old_value} new={new_value}")
    with pytest.raises(ValidationError):
        validate_merge_prompt("only {old_value}")
    with pytest.raises(ValidationError):
        validate_merge_prompt("only {new_value}")
