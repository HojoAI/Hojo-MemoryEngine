"""Schema API routes (/schema/*)."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from memory_engine.api.deps import require_permission
from memory_engine.core.context import RequestContext
from memory_engine.db.session import get_db
from memory_engine.schemas.common import ApiResponse, SearchMode
from memory_engine.schemas.memory_field import (
    MemoryFieldCreate,
    MemoryFieldOut,
    MemoryFieldUpdate,
)
from memory_engine.schemas.rules import (
    CallRuleCreate,
    MergeRuleCreate,
    ParseRuleCreate,
    RetrieveRuleCreate,
    RuleOut,
    RuleUpdateBody,
)
from memory_engine.services import memory_field as mf_service
from memory_engine.services import rules as rule_service
from memory_engine.services.workflow_launch import launch_schema_crud, launch_schema_upsert

router = APIRouter(prefix="/schema", tags=["schema"])


@router.post("/create", response_model=ApiResponse)
async def schema_create(
    body: MemoryFieldCreate,
    dedup_mode: SearchMode = SearchMode.EXACT,
    use_temporal: bool = False,
    wait: bool = False,
    session: AsyncSession = Depends(get_db),
    ctx: RequestContext = Depends(require_permission("schema:create")),
) -> ApiResponse:
    existing = await mf_service.search_by_mode(session, ctx, body.name, dedup_mode)
    if existing:
        from memory_engine.core.exceptions import ConflictError

        raise ConflictError(
            f"memory_field '{body.name}' already exists (dedup_mode={dedup_mode.value})"
        )
    if use_temporal:
        return ApiResponse(
            data=await launch_schema_crud(ctx, "create", body.name, create_body=body, wait=wait)
        )
    return ApiResponse(data=await mf_service.create(session, ctx, body))


@router.post("/upsert", response_model=ApiResponse)
async def schema_upsert(
    body: MemoryFieldCreate,
    wait: bool = False,
    ctx: RequestContext = Depends(require_permission("schema:create")),
) -> ApiResponse:
    """Create or update schema via Temporal orchestration."""
    data = await launch_schema_upsert(ctx, body, wait=wait)
    return ApiResponse(data=data)


@router.post("/update", response_model=ApiResponse)
async def schema_update(
    name: str,
    body: MemoryFieldUpdate,
    use_temporal: bool = False,
    wait: bool = False,
    session: AsyncSession = Depends(get_db),
    ctx: RequestContext = Depends(require_permission("schema:update")),
) -> ApiResponse:
    if use_temporal:
        return ApiResponse(
            data=await launch_schema_crud(
                ctx, "update", name, update_body=body, wait=wait
            )
        )
    return ApiResponse(data=await mf_service.update(session, ctx, name, body))


@router.post("/delete", response_model=ApiResponse)
async def schema_delete(
    name: str,
    use_temporal: bool = False,
    wait: bool = False,
    session: AsyncSession = Depends(get_db),
    ctx: RequestContext = Depends(require_permission("schema:delete")),
) -> ApiResponse:
    if use_temporal:
        return ApiResponse(data=await launch_schema_crud(ctx, "delete", name, wait=wait))
    await mf_service.delete_soft(session, ctx, name)
    return ApiResponse(message="deleted")


@router.get("/get", response_model=ApiResponse)
async def schema_get(
    name: str,
    mode: SearchMode = SearchMode.EXACT,
    session: AsyncSession = Depends(get_db),
    ctx: RequestContext = Depends(require_permission("schema:read")),
) -> ApiResponse:
    row = await mf_service.search_by_mode(session, ctx, name, mode)
    if not row:
        return ApiResponse(data=None)
    return ApiResponse(data=MemoryFieldOut.model_validate(row))


@router.get("/list", response_model=ApiResponse)
async def schema_list(
    offset: int = 0,
    limit: int = 50,
    session: AsyncSession = Depends(get_db),
    ctx: RequestContext = Depends(require_permission("schema:read")),
) -> ApiResponse:
    rows = await mf_service.list_active(session, ctx, offset=offset, limit=limit)
    return ApiResponse(data=[MemoryFieldOut.model_validate(r) for r in rows])


@router.post("/parse/create", response_model=ApiResponse)
async def parse_create(
    body: ParseRuleCreate,
    session: AsyncSession = Depends(get_db),
    ctx: RequestContext = Depends(require_permission("schema:write")),
) -> ApiResponse:
    row = await rule_service.create_parse(
        session,
        ctx,
        memory_field_name=body.memory_field_name,
        rule_name=body.rule_name,
        rule_config_json=body.rule_config_json,
        capability_id=body.capability_id,
        capability_name=body.capability_name,
        module_name=body.module_name,
        service_name=body.service_name,
        code_fingerprint=body.code_fingerprint,
        priority=body.priority,
    )
    return ApiResponse(data=RuleOut.model_validate(row))


@router.post("/parse/update", response_model=ApiResponse)
async def parse_update(
    memory_field_name: str,
    rule_name: str,
    body: RuleUpdateBody,
    session: AsyncSession = Depends(get_db),
    ctx: RequestContext = Depends(require_permission("schema:write")),
) -> ApiResponse:
    row = await rule_service.update_parse(session, ctx, memory_field_name, rule_name, body)
    return ApiResponse(data=RuleOut.model_validate(row))


@router.post("/parse/delete", response_model=ApiResponse)
async def parse_delete(
    memory_field_name: str,
    rule_name: str,
    session: AsyncSession = Depends(get_db),
    ctx: RequestContext = Depends(require_permission("schema:write")),
) -> ApiResponse:
    await rule_service.delete_parse_soft(session, ctx, memory_field_name, rule_name)
    return ApiResponse(message="deleted")


@router.get("/parse/get", response_model=ApiResponse)
async def parse_get(
    memory_field_name: str,
    rule_name: str,
    session: AsyncSession = Depends(get_db),
    ctx: RequestContext = Depends(require_permission("schema:read")),
) -> ApiResponse:
    row = await rule_service.get_active_parse(session, ctx, memory_field_name, rule_name)
    if not row:
        return ApiResponse(data=None)
    return ApiResponse(data=RuleOut.model_validate(row))


@router.get("/parse/list", response_model=ApiResponse)
async def parse_list(
    session: AsyncSession = Depends(get_db),
    ctx: RequestContext = Depends(require_permission("schema:read")),
) -> ApiResponse:
    rows = await rule_service.list_parse(session, ctx)
    return ApiResponse(data=[RuleOut.model_validate(r) for r in rows])


# ---------- merge_rule (LLM fusion for MERGE match_method) ----------


@router.post("/merge/create", response_model=ApiResponse)
async def merge_create(
    body: MergeRuleCreate,
    session: AsyncSession = Depends(get_db),
    ctx: RequestContext = Depends(require_permission("schema:write")),
) -> ApiResponse:
    row = await rule_service.create_merge(
        session,
        ctx,
        memory_field_name=body.memory_field_name,
        rule_name=body.rule_name,
        rule_config_json=body.rule_config_json,
        capability_id=body.capability_id,
        priority=body.priority,
    )
    return ApiResponse(data=RuleOut.model_validate(row))


@router.post("/merge/delete", response_model=ApiResponse)
async def merge_delete(
    memory_field_name: str,
    rule_name: str,
    session: AsyncSession = Depends(get_db),
    ctx: RequestContext = Depends(require_permission("schema:write")),
) -> ApiResponse:
    await rule_service.delete_merge_soft(session, ctx, memory_field_name, rule_name)
    return ApiResponse(message="deleted")


@router.get("/merge/get", response_model=ApiResponse)
async def merge_get(
    memory_field_name: str,
    rule_name: str,
    session: AsyncSession = Depends(get_db),
    ctx: RequestContext = Depends(require_permission("schema:read")),
) -> ApiResponse:
    row = await rule_service.get_active_merge(session, ctx, memory_field_name, rule_name)
    if not row:
        return ApiResponse(data=None)
    return ApiResponse(data=RuleOut.model_validate(row))


@router.get("/merge/list", response_model=ApiResponse)
async def merge_list(
    session: AsyncSession = Depends(get_db),
    ctx: RequestContext = Depends(require_permission("schema:read")),
) -> ApiResponse:
    rows = await rule_service.list_merge(session, ctx)
    return ApiResponse(data=[RuleOut.model_validate(r) for r in rows])


# ---------- retrieve_rule ----------


@router.post("/retrieve/create", response_model=ApiResponse)
async def retrieve_create(
    body: RetrieveRuleCreate,
    session: AsyncSession = Depends(get_db),
    ctx: RequestContext = Depends(require_permission("schema:write")),
) -> ApiResponse:
    row = await rule_service.create_retrieve(session, ctx, body)
    return ApiResponse(data=RuleOut.model_validate(row))


@router.post("/retrieve/update", response_model=ApiResponse)
async def retrieve_update(
    rule_name: str,
    body: RuleUpdateBody,
    memory_field_name: str | None = None,
    session: AsyncSession = Depends(get_db),
    ctx: RequestContext = Depends(require_permission("schema:write")),
) -> ApiResponse:
    row = await rule_service.update_retrieve(
        session, ctx, rule_name, body, memory_field_name=memory_field_name
    )
    return ApiResponse(data=RuleOut.model_validate(row))


@router.post("/retrieve/delete", response_model=ApiResponse)
async def retrieve_delete(
    rule_name: str,
    memory_field_name: str | None = None,
    session: AsyncSession = Depends(get_db),
    ctx: RequestContext = Depends(require_permission("schema:write")),
) -> ApiResponse:
    await rule_service.delete_retrieve_soft(
        session, ctx, rule_name, memory_field_name=memory_field_name
    )
    return ApiResponse(message="deleted")


@router.get("/retrieve/get", response_model=ApiResponse)
async def retrieve_get(
    rule_name: str,
    memory_field_name: str | None = None,
    session: AsyncSession = Depends(get_db),
    ctx: RequestContext = Depends(require_permission("schema:read")),
) -> ApiResponse:
    row = await rule_service.get_active_retrieve(
        session, ctx, rule_name, memory_field_name=memory_field_name
    )
    if not row:
        return ApiResponse(data=None)
    return ApiResponse(data=RuleOut.model_validate(row))


@router.get("/retrieve/list", response_model=ApiResponse)
async def retrieve_list(
    session: AsyncSession = Depends(get_db),
    ctx: RequestContext = Depends(require_permission("schema:read")),
) -> ApiResponse:
    rows = await rule_service.list_retrieve(session, ctx)
    return ApiResponse(data=[RuleOut.model_validate(r) for r in rows])


# ---------- call_rule ----------


@router.post("/call/create", response_model=ApiResponse)
async def call_create(
    body: CallRuleCreate,
    session: AsyncSession = Depends(get_db),
    ctx: RequestContext = Depends(require_permission("schema:write")),
) -> ApiResponse:
    row = await rule_service.create_call(session, ctx, body)
    return ApiResponse(data=RuleOut.model_validate(row))


@router.post("/call/update", response_model=ApiResponse)
async def call_update(
    memory_field_name: str,
    rule_name: str,
    body: RuleUpdateBody,
    session: AsyncSession = Depends(get_db),
    ctx: RequestContext = Depends(require_permission("schema:write")),
) -> ApiResponse:
    row = await rule_service.update_call(session, ctx, memory_field_name, rule_name, body)
    return ApiResponse(data=RuleOut.model_validate(row))


@router.post("/call/delete", response_model=ApiResponse)
async def call_delete(
    memory_field_name: str,
    rule_name: str,
    session: AsyncSession = Depends(get_db),
    ctx: RequestContext = Depends(require_permission("schema:write")),
) -> ApiResponse:
    await rule_service.delete_call_soft(session, ctx, memory_field_name, rule_name)
    return ApiResponse(message="deleted")


@router.get("/call/get", response_model=ApiResponse)
async def call_get(
    memory_field_name: str,
    rule_name: str,
    session: AsyncSession = Depends(get_db),
    ctx: RequestContext = Depends(require_permission("schema:read")),
) -> ApiResponse:
    row = await rule_service.get_active_call(session, ctx, memory_field_name, rule_name)
    if not row:
        return ApiResponse(data=None)
    return ApiResponse(data=RuleOut.model_validate(row))


@router.get("/call/list", response_model=ApiResponse)
async def call_list(
    session: AsyncSession = Depends(get_db),
    ctx: RequestContext = Depends(require_permission("schema:read")),
) -> ApiResponse:
    rows = await rule_service.list_call(session, ctx)
    return ApiResponse(data=[RuleOut.model_validate(r) for r in rows])
