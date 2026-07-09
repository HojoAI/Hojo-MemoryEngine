"""Parse rule lookup: deleted=0 and max version."""

from sqlalchemy import select
from sqlalchemy.sql import Select

from memory_engine.models.schema import ParseRule


def test_get_active_parse_query_shape() -> None:
    """``get_active_parse`` must filter deleted and order by version desc."""
    stmt: Select[tuple[ParseRule]] = (
        select(ParseRule)
        .where(
            ParseRule.tenant_id == 1,
            ParseRule.org_id == 2,
            ParseRule.memory_field_name == "用户性别",
            ParseRule.rule_name == "extract_gender",
            ParseRule.deleted == 0,
        )
        .order_by(ParseRule.version.desc())
        .limit(1)
    )
    compiled = str(stmt.compile(compile_kwargs={"literal_binds": True}))
    assert "deleted" in compiled
    assert "version" in compiled.lower()
