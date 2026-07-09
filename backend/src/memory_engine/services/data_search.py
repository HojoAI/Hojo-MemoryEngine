"""Memory data search by value (EXACT / REGEX / SEMANTIC / LLM)."""

from __future__ import annotations

import json
import re
from typing import Any

from memory_engine.core.context import RequestContext
from memory_engine.integrations import llm_client, mongo_store, qdrant_store
from memory_engine.schemas.common import SearchMode
from memory_engine.schemas.memory_field import MemoryDataOut, MemoryDataRetrieveOut


def _serialize(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


async def search_memory_data(
    ctx: RequestContext,
    user_id: str,
    memory_field_name: str,
    query: str,
    mode: SearchMode,
) -> MemoryDataOut | MemoryDataRetrieveOut | None:
    doc = await mongo_store.get_memory_data(
        ctx.tenant_id, ctx.org_id, user_id, memory_field_name
    )
    if not doc:
        return None

    value = doc.get("value")
    if mode == SearchMode.EXACT:
        if query and _serialize(value) != query:
            return None
        return MemoryDataOut(
            user_id=user_id,
            memory_field_name=memory_field_name,
            value=value,
        )

    if mode == SearchMode.REGEX:
        if not re.search(query or ".*", _serialize(value), re.DOTALL):
            return None
        return MemoryDataOut(user_id=user_id, memory_field_name=memory_field_name, value=value)

    if mode == SearchMode.SEMANTIC:
        hits = await qdrant_store.search_vectors(
            ctx.tenant_id,
            ctx.org_id,
            user_id,
            query or _serialize(value),
            memory_field_name=memory_field_name,
            limit=1,
        )
        if not hits:
            return MemoryDataOut(user_id=user_id, memory_field_name=memory_field_name, value=value)
        return MemoryDataOut(user_id=user_id, memory_field_name=memory_field_name, value=value)

    if mode == SearchMode.LLM:
        prompt = (
            f"Memory field: {memory_field_name}\n"
            f"Value:\n{_serialize(value)}\n\n"
            f"Question:\n{query or 'Summarize this memory'}"
        )
        result, _, _ = await llm_client.chat_completion(
            prompt,
            system="Answer using only the memory value provided.",
        )
        return MemoryDataRetrieveOut(
            user_id=user_id,
            memory_field_name=memory_field_name,
            value=value,
            retrieve_result=result,
        )

    return MemoryDataOut(user_id=user_id, memory_field_name=memory_field_name, value=value)
