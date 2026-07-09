"""Advanced schema search: SEMANTIC / LLM modes."""

from __future__ import annotations

import json
import re

from sqlalchemy.ext.asyncio import AsyncSession

from memory_engine.core.context import RequestContext
from memory_engine.integrations import llm_client
from memory_engine.models.schema import MemoryField
from memory_engine.schemas.common import SearchMode
from memory_engine.services import memory_field as mf_service

_SCHEMA_LLM_SYSTEM = (
    "你是记忆字段名匹配器。给定候选字段名列表与用户输入，仅在存在与用户输入「语义完全相同」"
    "的一个字段名时返回该名称；否则必须返回 null。不要猜测、不要返回相近但不同的字段。"
    '只输出 JSON：{"name":"<字段名>"} 或 {"name":null}。'
)


async def _semantic_pick(
    rows: list[MemoryField], query: str
) -> MemoryField | None:
    if not rows:
        return None
    try:
        q_vec = await llm_client.embed_text(query)
    except Exception:
        return rows[0]
    best: MemoryField | None = None
    best_score = -1.0
    for row in rows:
        text = f"{row.name} {row.description or ''}"
        try:
            vec = await llm_client.embed_text(text)
        except Exception:
            continue
        score = sum(a * b for a, b in zip(q_vec, vec, strict=False))
        if score > best_score:
            best_score = score
            best = row
    return best or rows[0]


def _parse_llm_pick_name(raw: str) -> str | None:
    """Parse ``{"name": ...}`` from model output."""
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        picked = json.loads(text).get("name")
    except json.JSONDecodeError:
        return None
    if picked is None:
        return None
    name = str(picked).strip()
    return name or None


async def _llm_pick(rows: list[MemoryField], query: str) -> MemoryField | None:
    """List active field names, ask LLM to pick one semantically identical match or none."""
    if not rows:
        return None
    names = [r.name for r in rows]
    by_name = {r.name: r for r in rows}
    prompt = (
        f"候选字段名（memory_field.deleted=0）：\n"
        f"{json.dumps(names, ensure_ascii=False)}\n\n"
        f"用户输入：\n{query.strip()}"
    )
    raw, _, _ = await llm_client.chat_completion(prompt, system=_SCHEMA_LLM_SYSTEM)
    picked = _parse_llm_pick_name(raw)
    if not picked:
        return None
    return by_name.get(picked)


async def search_schema(
    session: AsyncSession,
    ctx: RequestContext,
    name: str,
    mode: SearchMode,
) -> MemoryField | None:
    """Resolve schema by EXACT / REGEX / SEMANTIC / LLM."""
    if mode == SearchMode.EXACT:
        return await mf_service.get_active_by_name(session, ctx, name)
    if mode == SearchMode.REGEX:
        rows = await mf_service.list_active(session, ctx, limit=500)
        for row in rows:
            if re.search(name, row.name):
                return row
        return None
    rows = await mf_service.list_active(session, ctx, limit=200)
    if mode == SearchMode.SEMANTIC:
        return await _semantic_pick(rows, name)
    if mode == SearchMode.LLM:
        return await _llm_pick(rows, name)
    return await mf_service.get_active_by_name(session, ctx, name)
