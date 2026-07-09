"""Memory field API schemas."""

from typing import Any

from pydantic import BaseModel, Field, model_validator

from memory_engine.schemas.common import SearchMode


class MemoryFieldCreate(BaseModel):
    """Create memory field."""

    name: str = Field(..., max_length=255)
    description: str | None = None
    value_type: str = "string"
    match_method: str = "OVERWRITE"
    storage_type: str = "KV"
    source: str = "api"


class MemoryFieldUpdate(BaseModel):
    """Update memory field (creates new version)."""

    description: str | None = None
    value_type: str | None = None
    match_method: str | None = None
    storage_type: str | None = None
    status: str | None = None


class MemoryFieldOut(BaseModel):
    """Memory field response."""

    id: int
    tenant_id: int
    org_id: int
    name: str
    description: str | None
    value_type: str
    match_method: str
    storage_type: str
    version: int
    status: str
    source: str

    model_config = {"from_attributes": True}


class MemoryFieldGetQuery(BaseModel):
    """GET /schema/get query."""

    name: str
    mode: SearchMode = SearchMode.EXACT


class MemoryDataCreate(BaseModel):
    """Create memory data."""

    user_id: str                        # 用户标识
    memory_field_name: str              # 存到哪个记忆字段
    value: Any | None = None            # 直接给值（跳过LLM解析）
    query: str | None = None            # 给原始文本，让LLM解析成记忆数据
    extra: dict | None = None           # 额外信息
    write_rule: str | None = None       # 写入规则
    parse_rule_name: str | None = None  # 解析规则名称
    merge_rule_name: str | None = None  # 合并规则名称
    language: str | None = "en"         # 注入到prompt的{language}槽位，默认en
    source: str | None = Field(
        None,
        description="dialogue | knowledge",
    )

    # value和query不能同时为空
    @model_validator(mode="after")
    def require_value_or_query(self) -> "MemoryDataCreate":
        if self.value is None and not self.query:
            raise ValueError("either value or query is required")
        return self


class MemoryDataUpdate(BaseModel):
    """Update memory data."""

    user_id: str
    memory_field_name: str
    value: Any
    write_rule: str | None = None
    merge_rule_name: str | None = None
    source: str | None = Field(
        None,
        description="dialogue | knowledge",
    )


class MemoryDataOut(BaseModel):
    """Memory data response."""

    user_id: str
    memory_field_name: str
    value: Any | None = None
    deleted: int = 0


class MemoryDataListPage(BaseModel):
    """Paginated memory data list (dashboard / debug)."""

    items: list[MemoryDataOut]
    total: int


class UserMemoryDataRequest(BaseModel):
    """Service API: all memory **data** for one Mongo/Qdrant partition."""

    memory_user_id: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description=(
            "Partition id stored as memory_data.user_id in MongoDB and payload.user_id "
            "in Qdrant (e.g. API key prefix or SDK user_id). Not MySQL app_user.id."
        ),
    )
    offset: int = Field(0, ge=0)
    limit: int = Field(200, ge=1, le=1000)


class UserMemoryDataListResult(BaseModel):
    """All memory data for one Mongo/Qdrant partition (paginated)."""

    memory_user_id: str
    items: list[MemoryDataOut]
    total: int
    offset: int
    limit: int


class UserMemoryDataDeleteResult(BaseModel):
    """Bulk soft-delete for one partition (Mongo ``deleted=1``, Qdrant ``payload.deleted=1``)."""

    memory_user_id: str
    deleted_count: int = Field(
        ...,
        description="Mongo memory_data documents marked deleted=1 (not removed).",
    )
    vector_marked_count: int = Field(
        ...,
        description="Qdrant points marked payload.deleted=1 (not physically deleted).",
    )


class UserMemoryDataExistsResult(BaseModel):
    """Whether the user has any active memory data (same scope as ``list-all``)."""

    memory_user_id: str
    has_data: bool = Field(..., description="True if at least one undeleted memory row exists")


class UserMemoryExportEmailRequest(BaseModel):
    """H5: email memory export (same data scope as ``list-all``)."""

    email: str = Field(..., min_length=3, max_length=320, description="Recipient email")
    offset: int = Field(0, ge=0, description="Same as GET list-all")
    limit: int | None = Field(
        None,
        ge=1,
        le=1000,
        description="If set, export only this page; if omitted, export all (capped server-side)",
    )


class UserMemoryExportEmailResult(BaseModel):
    """Result after memory export email was sent."""

    email: str
    memory_user_id: str
    item_count: int = Field(..., description="Number of rows included in the email")
    total: int = Field(..., description="Total active rows matching list-all count")
    offset: int
    limit: int = Field(..., description="Effective export window (limit or item_count when full export)")


class LLMConfig(BaseModel):
    """Per-request LLM overrides (SDK RetrieveRule / Data.call)."""

    base_url: str | None = None
    api_key: str | None = None
    model_name: str | None = None


class RetrieveRuleBody(BaseModel):
    """Retrieve rule for POST /data/retrieve."""

    method: str = "EXACT"
    prompt: str | None = None
    llm: LLMConfig | None = None


class DataRetrieveRequest(BaseModel):
    """Retrieve memory data (explicit or implicit)."""

    user_id: str
    memory_field_name: str | None = None
    rule_name: str | None = None
    rule: RetrieveRuleBody = Field(default_factory=RetrieveRuleBody)


class MemoryDataRetrieveOut(MemoryDataOut):
    """Retrieve response; includes optional LLM inference."""

    retrieve_result: str | None = None


class DataCallRequest(BaseModel):
    """Call memory into a prompt template."""

    memory_field_name: str
    prompt_template: str
    slot: str
    mem_data: Any
    use_llm: bool = True
    llm: LLMConfig | None = None
    rule_name: str | None = None


class DataCallResponse(BaseModel):
    """Call response."""

    result: str
    filled_prompt: str
