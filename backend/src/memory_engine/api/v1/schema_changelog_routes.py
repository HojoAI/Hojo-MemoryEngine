"""Schema changelog poll/SSE for SDK hot-reload."""

import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from memory_engine.api.deps import require_permission
from memory_engine.core.context import RequestContext
from memory_engine.schemas.common import ApiResponse
from memory_engine.services import schema_changelog as changelog_svc

router = APIRouter(prefix="/schema/changelog", tags=["schema-changelog"])


@router.get("/poll", response_model=ApiResponse)
async def changelog_poll(
    cursor: str = "0-0",
    block_ms: int = 5000,
    count: int = 50,
    ctx: RequestContext = Depends(require_permission("schema:read")),
) -> ApiResponse:
    """Long-poll schema/rule changes (Canal → Redis Stream)."""
    events, next_cursor = await changelog_svc.poll_changelog(
        ctx.tenant_id,
        ctx.org_id,
        cursor=cursor,
        block_ms=min(block_ms, 30_000),
        count=count,
    )
    return ApiResponse(data={"events": events, "cursor": next_cursor})


@router.get("/stream")
async def changelog_stream(
    cursor: str = "0-0",
    timeout_seconds: int = 300,
    ctx: RequestContext = Depends(require_permission("schema:read")),
) -> StreamingResponse:
    """SSE stream of schema changelog events for SDK."""

    async def event_generator() -> AsyncIterator[str]:
        current = cursor
        async for ev in changelog_svc.stream_changelog(
            ctx.tenant_id,
            ctx.org_id,
            cursor=current,
            timeout_seconds=min(timeout_seconds, 3600),
        ):
            current = ev.get("_cursor", current)
            yield f"data: {json.dumps(ev, default=str)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
