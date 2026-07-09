"""Memory retrieve (explicit/implicit) and call with LLM."""

from __future__ import annotations

import json
import re
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from memory_engine.config import get_settings
from memory_engine.core.context import RequestContext
from memory_engine.core.exceptions import NotFoundError
from memory_engine.integrations import llm_client, mongo_store, qdrant_store
from memory_engine.schemas.memory_field import (
    DataCallRequest,
    DataCallResponse,
    DataRetrieveRequest,
    LLMConfig,
    MemoryDataRetrieveOut,
    RetrieveRuleBody,
)
from memory_engine.services import billing_service, memory_field as mf_service, rules as rule_service

_RETRIEVE_SYSTEM = (
    "You are a memory retrieval assistant. Answer using only the provided memory "
    "content. If the memory is insufficient, say so briefly."
)
_IMPLICIT_SYSTEM = (
    "You select the most relevant user memory for a task. Respond with JSON only: "
    '{"memory_field_name":"<field name or null>","answer":"<your answer>"}. '
    "Use null for memory_field_name when no memory applies."
)


def _serialize_value(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


def _llm_from_config(llm: LLMConfig | None) -> tuple[str | None, str | None, str | None]:
    if not llm:
        return None, None, None
    return llm.base_url, llm.api_key, llm.model_name


async def _run_llm(
    session: AsyncSession,
    ctx: RequestContext,
    prompt: str,
    llm: LLMConfig | None,
    *,
    system: str | None = None,
) -> str:
    base_url, api_key, model = _llm_from_config(llm)
    settings = get_settings()
    model_name = model or settings.openai_model
    text, pt, ct = await llm_client.chat_completion(
        prompt,
        system=system,
        base_url=base_url,
        api_key=api_key,
        model=model_name,
    )
    await billing_service.emit_llm_completion(
        session,
        ctx,
        model_name=model_name,
        prompt_tokens=pt,
        completion_tokens=ct,
    )
    return text


async def _resolve_retrieve_rule(
    session: AsyncSession,
    ctx: RequestContext,
    body: DataRetrieveRequest,
) -> DataRetrieveRequest:
    """Merge DB retrieve_rule when rule_name is set."""
    if not body.rule_name:
        return body
    implicit = body.memory_field_name is None
    row = await rule_service.get_active_retrieve(
        session,
        ctx,
        body.rule_name,
        memory_field_name=body.memory_field_name,
        implicit=implicit,
    )
    if not row:
        raise NotFoundError(f"retrieve_rule '{body.rule_name}' not found")

    db_rule = rule_service.retrieve_rule_to_body(row)
    cfg = row.rule_config_json or {}
    merged = RetrieveRuleBody(
        method=body.rule.method if body.rule.method != "EXACT" else db_rule.get("method", "EXACT"),
        prompt=body.rule.prompt or db_rule.get("prompt"),
        llm=body.rule.llm or (LLMConfig(**db_rule["llm"]) if db_rule.get("llm") else None),
    )
    if body.rule.method != "EXACT":
        merged.method = body.rule.method
    if cfg.get("prompt") and not body.rule.prompt:
        merged.prompt = cfg.get("prompt")
    if body.memory_field_name is None and row.memory_field_name:
        body = body.model_copy(update={"memory_field_name": row.memory_field_name})
    return body.model_copy(update={"rule": merged})


def _doc_to_out(doc: dict[str, Any], *, retrieve_result: str | None = None) -> MemoryDataRetrieveOut:
    return MemoryDataRetrieveOut(
        user_id=doc["user_id"],
        memory_field_name=doc["memory_field_name"],
        value=doc.get("value"),
        deleted=doc.get("deleted", 0),
        retrieve_result=retrieve_result,
    )


async def retrieve(
    session: AsyncSession,
    ctx: RequestContext,
    body: DataRetrieveRequest,
) -> MemoryDataRetrieveOut | None:
    """Explicit or implicit memory retrieval."""
    body = await _resolve_retrieve_rule(session, ctx, body)
    if body.memory_field_name:
        return await _retrieve_explicit(session, ctx, body)
    return await _retrieve_implicit(session, ctx, body)


async def _retrieve_explicit(
    session: AsyncSession,
    ctx: RequestContext,
    body: DataRetrieveRequest,
) -> MemoryDataRetrieveOut | None:
    name = body.memory_field_name
    assert name is not None
    field = await mf_service.get_active_by_name(session, ctx, name)
    if not field:
        raise NotFoundError(f"memory_field '{name}' not found")

    doc = await mongo_store.get_memory_data(ctx.tenant_id, ctx.org_id, body.user_id, name)
    if not doc:
        return None

    method = body.rule.method.upper()
    prompt_text = body.rule.prompt or ""

    if method == "EXACT":
        return _doc_to_out(doc)

    if method == "REGEX":
        pattern = prompt_text or ".*"
        if not re.search(pattern, _serialize_value(doc.get("value")), re.DOTALL):
            return None
        return _doc_to_out(doc)

    if method == "SEMANTIC":
        query = prompt_text or _serialize_value(doc.get("value"))
        await qdrant_store.search_vectors(
            ctx.tenant_id,
            ctx.org_id,
            body.user_id,
            query,
            memory_field_name=name,
            limit=1,
        )
        return _doc_to_out(doc)

    if method == "LLM":
        task = prompt_text or "Summarize the memory content."
        user_prompt = (
            f"Memory field: {name}\n"
            f"Memory content:\n{_serialize_value(doc.get('value'))}\n\n"
            f"Task:\n{task}"
        )
        result = await _run_llm(session, ctx, user_prompt, body.rule.llm, system=_RETRIEVE_SYSTEM)
        return _doc_to_out(doc, retrieve_result=result)

    return _doc_to_out(doc)


async def _retrieve_implicit(
    session: AsyncSession,
    ctx: RequestContext,
    body: DataRetrieveRequest,
) -> MemoryDataRetrieveOut | None:
    docs = await mongo_store.list_memory_data_for_user(ctx.tenant_id, ctx.org_id, body.user_id)
    if not docs:
        return None

    method = body.rule.method.upper()
    prompt_text = body.rule.prompt or ""

    if method == "EXACT":
        for doc in docs:
            if prompt_text and _serialize_value(doc.get("value")) == prompt_text:
                return _doc_to_out(doc)
        return _doc_to_out(docs[0])

    if method == "REGEX":
        pattern = prompt_text or ".*"
        for doc in docs:
            if re.search(pattern, _serialize_value(doc.get("value")), re.DOTALL):
                return _doc_to_out(doc)
        return None

    if method == "SEMANTIC":
        query = prompt_text or " "
        hits = await qdrant_store.search_vectors(
            ctx.tenant_id, ctx.org_id, body.user_id, query, limit=1
        )
        if hits and hits[0].get("memory_field_name"):
            field_name = hits[0]["memory_field_name"]
            doc = await mongo_store.get_memory_data(
                ctx.tenant_id, ctx.org_id, body.user_id, field_name
            )
            if doc:
                return _doc_to_out(doc)
        return _doc_to_out(docs[0])

    if method == "LLM":
        catalog = [
            {"memory_field_name": d["memory_field_name"], "value": d.get("value")} for d in docs
        ]
        task = prompt_text or "Find the most relevant memory for the user request."
        user_prompt = (
            f"Available memories (JSON):\n{json.dumps(catalog, ensure_ascii=False)}\n\n"
            f"User request:\n{task}"
        )
        raw = await _run_llm(session, ctx, user_prompt, body.rule.llm, system=_IMPLICIT_SYSTEM)
        field_name, answer = _parse_implicit_llm_response(raw)
        if not field_name:
            return None
        doc = await mongo_store.get_memory_data(ctx.tenant_id, ctx.org_id, body.user_id, field_name)
        if not doc:
            return None
        return _doc_to_out(doc, retrieve_result=answer or raw)

    return _doc_to_out(docs[0])


def _parse_implicit_llm_response(raw: str) -> tuple[str | None, str | None]:
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        data = json.loads(text)
        name = data.get("memory_field_name")
        if name is None or name == "null":
            return None, data.get("answer")
        return str(name), data.get("answer")
    except json.JSONDecodeError:
        return None, raw


async def call_memory(
    session: AsyncSession,
    ctx: RequestContext,
    body: DataCallRequest,
) -> DataCallResponse:
    """Fill prompt slot; optionally run LLM; honor call_rule when rule_name set."""
    field = await mf_service.get_active_by_name(session, ctx, body.memory_field_name)
    if not field:
        raise NotFoundError(f"memory_field '{body.memory_field_name}' not found")

    prompt_template = body.prompt_template
    slot = body.slot
    use_llm = body.use_llm
    llm = body.llm

    if body.rule_name:
        row = await rule_service.get_active_call(
            session, ctx, body.memory_field_name, body.rule_name
        )
        if not row:
            raise NotFoundError(f"call_rule '{body.rule_name}' not found")
        cfg = row.rule_config_json or {}
        prompt_template = cfg.get("prompt_template", prompt_template)
        slot = row.slot_name or slot
        use_llm = cfg.get("use_llm", use_llm)
        if cfg.get("llm") and llm is None:
            llm = LLMConfig(**cfg["llm"])

    filled = prompt_template.replace(slot, _serialize_value(body.mem_data))
    if not use_llm:
        return DataCallResponse(result=filled, filled_prompt=filled)

    system = (
        "You are a helpful assistant. Answer the user's question using the context "
        "provided in the message. Be concise."
    )
    result = await _run_llm(session, ctx, filled, llm, system=system)
    return DataCallResponse(result=result, filled_prompt=filled)
