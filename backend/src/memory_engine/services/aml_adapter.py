"""Synchronous evidence-only adapter for the Agent Memory Leaderboard."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
import re
from collections import Counter
from datetime import datetime, timezone
from typing import Any

from memory_engine.config import get_settings
from memory_engine.core.context import RequestContext
from memory_engine.core.exceptions import ConflictError
from memory_engine.integrations import aml_store, llm_client, qdrant_store
from memory_engine.schemas.aml import (
    AMLAddRequest,
    AMLAddResponse,
    AMLClearResponse,
    AMLSearchItem,
    AMLSearchRequest,
    AMLSearchResponse,
)

_TOKEN_PATTERN = re.compile(r"[a-z0-9]+|[\u3400-\u9fff]+", re.IGNORECASE)
_EXPLICIT_VALUE_PATTERN = re.compile(
    r"(?:\b\d+(?:[.,:]\d+)*(?:%|[a-z]{2,4})?\b|[$€£¥]\s?\d[\d,.]*|20\d{2}(?:[-/]\d{1,2}){0,2})",
    re.IGNORECASE,
)
_CURRENT_STATE_PATTERN = re.compile(
    r"\b(?:current|currently|latest|now|final|finally|still|updated?)\b|"
    r"现在|目前|当前|最新|最终|后来|改成|变更为|更新后",
    re.IGNORECASE,
)
_UPDATE_EVIDENCE_PATTERN = re.compile(
    r"\b(?:changed?|correct(?:ed|ion)?|final(?:ly)?|moved|updated?|instead|no longer)\b|"
    r"更正|更新|改成|变更为|最终|搬家|不再|作废|不是",
    re.IGNORECASE,
)
_AGGREGATION_QUERY_PATTERN = re.compile(
    r"\b(?:how many|how much|total|sum|combined|number of)\b|一共|总共|合计|总计|多少",
    re.IGNORECASE,
)
_AGGREGATION_OPERAND_PATTERN = re.compile(
    r"[$€£¥]\s?\d|\b\d+(?:[.,]\d+)*\b",
    re.IGNORECASE,
)
_AGGREGATION_STOPWORDS = {"combined", "how", "many", "much", "number", "sum", "total"}
_ENGLISH_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "did",
    "do",
    "does",
    "for",
    "from",
    "how",
    "i",
    "in",
    "is",
    "it",
    "me",
    "my",
    "of",
    "on",
    "the",
    "to",
    "was",
    "what",
    "when",
    "where",
    "which",
    "who",
    "why",
    "with",
}
_LOGGER = logging.getLogger(__name__)


def _payload_hash(body: AMLAddRequest) -> str:
    raw = json.dumps(body.model_dump(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _unit_id(ctx: RequestContext, request_id: str, index: int) -> str:
    raw = f"{ctx.tenant_id}:{ctx.org_id}:{request_id}:{index}"
    return f"aml_{hashlib.sha256(raw.encode()).hexdigest()[:32]}"


def _timestamp_iso(timestamp_ms: int | None, fallback: str) -> str:
    if timestamp_ms is None:
        return fallback
    return datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc).isoformat()


def _format_evidence(role: str, content: str, occurred_at: str) -> str:
    return f"[{occurred_at}] {role}: {content}"


def _parse_json_object(raw: str) -> dict[str, Any]:
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("LLM response did not contain a JSON object")
    value = json.loads(text[start : end + 1])
    if not isinstance(value, dict):
        raise ValueError("LLM response was not a JSON object")
    return value


async def _llm_json(
    *,
    prompt: str,
    system: str,
    model: str,
) -> dict[str, Any]:
    raw, _prompt_tokens, _completion_tokens = await llm_client.chat_completion(
        prompt,
        system=system,
        model=model,
        llm_params={"temperature": 0, "max_tokens": 800},
    )
    return _parse_json_object(raw)


async def _augment_message_terms(
    body: AMLAddRequest,
    settings: Any,
) -> dict[int, list[str]]:
    if not settings.aml_llm_add_augment_enabled:
        return {}
    messages = [
        {"index": index, "role": message.role, "content": message.content}
        for index, message in enumerate(body.messages)
    ]
    prompt = (
        "Extract short retrieval terms for each conversational message. "
        "Preserve only facts and aliases present in the message; do not answer a question, "
        "invent facts, summarize the conversation, or output anything except JSON.\n"
        f"Messages:\n{json.dumps(messages, ensure_ascii=False)}\n"
        'Return exactly {"messages":[{"index":0,"terms":["..."]}]}.'
    )
    try:
        result = await _llm_json(
            prompt=prompt,
            system=(
                "You create auxiliary search terms for a memory index. "
                "The original messages remain the source of truth."
            ),
            model=settings.aml_llm_model,
        )
        output: dict[int, list[str]] = {}
        for item in result.get("messages") or []:
            if not isinstance(item, dict):
                continue
            index = item.get("index")
            terms = item.get("terms")
            if isinstance(index, int) and isinstance(terms, list):
                output[index] = [str(term).strip() for term in terms if str(term).strip()][:12]
        return output
    except Exception:
        _LOGGER.exception("AML Add LLM augmentation failed")
        if settings.aml_llm_required:
            raise
        return {}


def _build_units(
    ctx: RequestContext,
    body: AMLAddRequest,
    terms_by_index: dict[int, list[str]] | None = None,
) -> list[dict[str, Any]]:
    now = aml_store.utc_now()
    terms_by_index = terms_by_index or {}
    units = []
    for index, message in enumerate(body.messages):
        evidence = _format_evidence(
            message.role,
            message.content,
            _timestamp_iso(message.timestamp, now),
        )
        terms = terms_by_index.get(index) or []
        searchable_content = evidence
        if terms:
            searchable_content += "\n[retrieval terms] " + " ".join(terms)
        units.append(
            {
                "unit_id": _unit_id(ctx, body.request_id, index),
                "tenant_id": ctx.tenant_id,
                "org_id": ctx.org_id,
                "request_id": body.request_id,
                "user_id": body.user_id,
                "session_id": body.session_id,
                "message_index": index,
                "role": message.role,
                "content": evidence,
                "event_time_ms": message.timestamp,
                "occurred_at": _timestamp_iso(message.timestamp, now),
                "searchable_content": searchable_content,
                "created_at": now,
            }
        )
    return units


async def add(ctx: RequestContext, body: AMLAddRequest) -> AMLAddResponse:
    digest = _payload_hash(body)
    now = aml_store.utc_now()
    ledger = await aml_store.reserve_add_request(
        {
            "tenant_id": ctx.tenant_id,
            "org_id": ctx.org_id,
            "request_id": body.request_id,
            "user_id": body.user_id,
            "session_id": body.session_id,
            "payload_hash": digest,
            "status": "processing",
            "created_at": now,
        }
    )
    if ledger.get("payload_hash") != digest:
        raise ConflictError("request_id was already used with a different payload")
    if ledger.get("status") == "complete":
        return AMLAddResponse(
            request_id=body.request_id,
            user_id=body.user_id,
            session_id=body.session_id,
        )

    settings = get_settings()
    terms_by_index = await _augment_message_terms(body, settings)
    units = _build_units(ctx, body, terms_by_index)
    await aml_store.upsert_units(units)
    try:
        await qdrant_store.upsert_aml_memory_units(units)
    except Exception:
        if settings.aml_require_vector_index:
            raise
    await aml_store.complete_add_request(ctx.tenant_id, ctx.org_id, body.request_id, digest)
    return AMLAddResponse(
        request_id=body.request_id,
        user_id=body.user_id,
        session_id=body.session_id,
    )


def _normalize_english_token(token: str) -> str:
    irregular = {
        "bought": "buy",
        "children": "child",
        "felt": "feel",
        "gone": "go",
        "graduated": "graduate",
        "had": "have",
        "moved": "move",
        "went": "go",
    }
    token = irregular.get(token, token)
    for suffix in ("ing", "ied", "ed", "es", "s"):
        if len(token) > len(suffix) + 3 and token.endswith(suffix):
            if suffix == "ied":
                return f"{token[:-3]}y"
            return token[: -len(suffix)]
    return token


def _tokens(text: str) -> list[str]:
    """Tokenize English morphologies and Chinese phrases without extra dependencies."""
    output: list[str] = []
    for raw in _TOKEN_PATTERN.findall(text.casefold()):
        if re.fullmatch(r"[\u3400-\u9fff]+", raw):
            if len(raw) == 1:
                output.append(raw)
            else:
                output.extend(raw[index : index + 2] for index in range(len(raw) - 1))
                if len(raw) <= 4:
                    output.append(raw)
            continue
        normalized = _normalize_english_token(raw)
        if normalized and normalized not in _ENGLISH_STOPWORDS:
            output.append(normalized)
    return output


def _explicit_match_rank(query: str, units: list[dict[str, Any]]) -> list[tuple[str, float]]:
    """Rank exact entities and values that dense similarity can easily blur."""
    query_tokens = set(_tokens(query))
    query_values = {value.casefold() for value in _EXPLICIT_VALUE_PATTERN.findall(query)}
    if not query_tokens and not query_values:
        return []
    ranked: list[tuple[str, float]] = []
    for unit in units:
        text = str(unit.get("searchable_content") or unit.get("content") or "")
        text_tokens = set(_tokens(text))
        token_coverage = len(query_tokens & text_tokens) / max(1, len(query_tokens))
        text_values = {value.casefold() for value in _EXPLICIT_VALUE_PATTERN.findall(text)}
        value_coverage = len(query_values & text_values) / max(1, len(query_values))
        score = token_coverage + value_coverage
        if score > 0:
            ranked.append((str(unit["unit_id"]), score))
    return sorted(ranked, key=lambda item: item[1], reverse=True)


def _event_time_ms(unit: dict[str, Any]) -> int:
    value = unit.get("event_time_ms")
    if isinstance(value, int):
        return value
    raw = str(unit.get("occurred_at") or unit.get("created_at") or "")
    try:
        return int(datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp() * 1000)
    except ValueError:
        return 0


def _temporal_rank(query: str, units: list[dict[str, Any]]) -> list[tuple[str, float]]:
    """Prefer updated recent evidence only for explicit current-state questions."""
    if not _CURRENT_STATE_PATTERN.search(query):
        return []
    query_terms = set(_tokens(query))
    candidates = []
    for unit in units:
        text = str(unit.get("searchable_content") or unit.get("content") or "")
        overlap = len(query_terms & set(_tokens(text)))
        if not overlap:
            continue
        update_signal = 1 if _UPDATE_EVIDENCE_PATTERN.search(text) else 0
        candidates.append((str(unit["unit_id"]), update_signal, _event_time_ms(unit), overlap))
    candidates.sort(key=lambda item: (item[1], item[2], item[3]), reverse=True)
    return [
        (unit_id, float(update_signal * 2 + overlap))
        for unit_id, update_signal, _timestamp, overlap in candidates
    ]


def _aggregation_rank(query: str, units: list[dict[str, Any]]) -> list[tuple[str, float]]:
    """Keep concrete operands available for counting and total questions."""
    if not _AGGREGATION_QUERY_PATTERN.search(query):
        return []
    query_terms = set(_tokens(query)) - _AGGREGATION_STOPWORDS
    ranked = []
    for unit in units:
        text = str(unit.get("searchable_content") or unit.get("content") or "")
        if not _AGGREGATION_OPERAND_PATTERN.search(text):
            continue
        overlap = len(query_terms & set(_tokens(text)))
        if query_terms and not overlap:
            continue
        ranked.append((str(unit["unit_id"]), float(1 + overlap)))
    return sorted(ranked, key=lambda item: item[1], reverse=True)


def _apply_role_bias(
    fused: dict[str, float],
    by_id: dict[str, dict[str, Any]],
    *,
    user_boost: float,
    assistant_penalty: float,
) -> None:
    """Favor first-person source turns over assistant acknowledgements."""
    for unit_id, score in list(fused.items()):
        role = str((by_id.get(unit_id) or {}).get("role") or "").casefold()
        if role == "user":
            fused[unit_id] = score * (1 + user_boost)
        elif role == "assistant":
            fused[unit_id] = score * max(0.0, 1 - assistant_penalty)


def _bm25_rank(query: str, units: list[dict[str, Any]]) -> list[tuple[str, float]]:
    query_terms = _tokens(query)
    if not query_terms or not units:
        return []
    documents = [
        _tokens(str(unit.get("searchable_content") or unit.get("content") or "")) for unit in units
    ]
    avg_len = sum(len(document) for document in documents) / max(1, len(documents))
    document_frequency: Counter[str] = Counter()
    for document in documents:
        document_frequency.update(set(document))
    total = len(documents)
    scores: list[tuple[str, float]] = []
    for unit, document in zip(units, documents, strict=True):
        frequencies = Counter(document)
        score = 0.0
        for term in query_terms:
            frequency = frequencies.get(term, 0)
            if not frequency:
                continue
            inverse_frequency = math.log(
                1 + (total - document_frequency[term] + 0.5) / (document_frequency[term] + 0.5)
            )
            denominator = frequency + 1.2 * (1 - 0.75 + 0.75 * len(document) / max(1.0, avg_len))
            score += inverse_frequency * frequency * 2.2 / denominator
        if score > 0:
            scores.append((str(unit["unit_id"]), score))
    return sorted(scores, key=lambda item: item[1], reverse=True)


def _add_rrf_channel(
    fused: dict[str, float],
    ranked_ids: list[str],
    *,
    weight: float,
    damping: int,
) -> None:
    for rank, unit_id in enumerate(ranked_ids, start=1):
        fused[unit_id] = fused.get(unit_id, 0.0) + weight / (damping + rank)


def _add_neighbor_evidence(
    fused: dict[str, float],
    ranked: list[tuple[str, float]],
    by_id: dict[str, dict[str, Any]],
    *,
    seed_limit: int,
    window: int,
    weight: float,
    damping: int,
) -> None:
    """Recall adjacent raw turns around strong seeds without rewriting evidence."""
    by_session_index: dict[tuple[str, int], str] = {}
    for unit_id, unit in by_id.items():
        session_id = str(unit.get("session_id") or "")
        message_index = unit.get("message_index")
        if session_id and isinstance(message_index, int):
            by_session_index[(session_id, message_index)] = unit_id
    for seed_rank, (seed_id, _score) in enumerate(ranked[:seed_limit], start=1):
        seed = by_id.get(seed_id) or {}
        session_id = str(seed.get("session_id") or "")
        message_index = seed.get("message_index")
        if not session_id or not isinstance(message_index, int):
            continue
        for distance in range(1, window + 1):
            for neighbor_index in (message_index - distance, message_index + distance):
                neighbor_id = by_session_index.get((session_id, neighbor_index))
                if neighbor_id and neighbor_id != seed_id:
                    fused[neighbor_id] = fused.get(neighbor_id, 0.0) + (
                        weight / (damping + seed_rank + distance - 1)
                    )


def _diversify_by_session(
    ranked: list[tuple[str, float]],
    by_id: dict[str, dict[str, Any]],
    *,
    max_per_session: int,
) -> list[tuple[str, float]]:
    """Prefer cross-session evidence, then append deferred items in original order."""
    selected: list[tuple[str, float]] = []
    deferred: list[tuple[str, float]] = []
    counts: dict[str, int] = {}
    for item in ranked:
        unit = by_id.get(item[0]) or {}
        session_id = str(unit.get("session_id") or "")
        if not session_id or counts.get(session_id, 0) < max_per_session:
            selected.append(item)
            if session_id:
                counts[session_id] = counts.get(session_id, 0) + 1
        else:
            deferred.append(item)
    return selected + deferred


async def _rerank_candidates(
    query: str,
    candidates: list[dict[str, Any]],
    settings: Any,
) -> list[str] | None:
    if not settings.aml_llm_rerank_enabled or not candidates:
        return None
    prompt_candidates = [
        {
            "id": str(unit["unit_id"]),
            "content": str(unit.get("content") or unit.get("searchable_content") or "")[:4000],
        }
        for unit in candidates[: settings.aml_llm_rerank_candidates]
    ]
    prompt = (
        "Rank the candidate memory evidence by usefulness for answering the query. "
        "Return only candidate IDs in descending relevance order. Do not answer the query, "
        "add facts, or rewrite evidence.\n"
        f"Query: {query}\n"
        f"Candidates:\n{json.dumps(prompt_candidates, ensure_ascii=False)}\n"
        'Return exactly {"unit_ids":["id1","id2"]}.'
    )
    try:
        result = await _llm_json(
            prompt=prompt,
            system=(
                "You are a memory evidence reranker. Select and order only the supplied IDs. "
                "Never generate an answer."
            ),
            model=settings.aml_llm_model,
        )
        allowed = {str(unit["unit_id"]) for unit in candidates}
        ordered = []
        for value in result.get("unit_ids") or []:
            unit_id = str(value)
            if unit_id in allowed and unit_id not in ordered:
                ordered.append(unit_id)
        return ordered or None
    except Exception:
        _LOGGER.exception("AML Search LLM rerank failed")
        if settings.aml_llm_required:
            raise
        return None


async def search(ctx: RequestContext, body: AMLSearchRequest) -> AMLSearchResponse:
    settings = get_settings()
    units = await aml_store.list_units_for_user(
        ctx.tenant_id,
        ctx.org_id,
        body.user_id,
        limit=settings.aml_max_user_units,
    )
    option_text = "\n".join(body.options or [])
    vector_calls = [
        qdrant_store.search_aml_memory_units(
            ctx.tenant_id,
            ctx.org_id,
            body.user_id,
            body.query,
            limit=settings.aml_candidate_limit,
        )
    ]
    if option_text:
        vector_calls.append(
            qdrant_store.search_aml_memory_units(
                ctx.tenant_id,
                ctx.org_id,
                body.user_id,
                f"{body.query}\n{option_text}",
                limit=settings.aml_candidate_limit,
            )
        )
    vector_results = await asyncio.gather(*vector_calls, return_exceptions=True)
    semantic_query = vector_results[0] if isinstance(vector_results[0], list) else []
    semantic_options = (
        vector_results[1] if len(vector_results) > 1 and isinstance(vector_results[1], list) else []
    )

    by_id = {str(unit["unit_id"]): unit for unit in units}
    semantic_ids = {
        str(item["unit_id"]) for item in [*semantic_query, *semantic_options] if item.get("unit_id")
    }
    missing_ids = sorted(semantic_ids - set(by_id))
    if missing_ids:
        hydrated = await aml_store.list_units_by_ids(
            ctx.tenant_id,
            ctx.org_id,
            body.user_id,
            missing_ids,
        )
        by_id.update({str(unit["unit_id"]): unit for unit in hydrated})
        units.extend(hydrated)
    fused: dict[str, float] = {}
    _add_rrf_channel(
        fused,
        [str(item["unit_id"]) for item in semantic_query if item.get("unit_id") in by_id],
        weight=settings.aml_vector_weight,
        damping=settings.aml_rrf_k,
    )
    lexical_query = _bm25_rank(body.query, units)
    _add_rrf_channel(
        fused,
        [unit_id for unit_id, _score in lexical_query],
        weight=settings.aml_lexical_weight,
        damping=settings.aml_rrf_k,
    )
    if settings.aml_exact_match_enabled:
        exact_query = _explicit_match_rank(body.query, units)
        _add_rrf_channel(
            fused,
            [unit_id for unit_id, _score in exact_query],
            weight=settings.aml_exact_match_weight,
            damping=settings.aml_rrf_k,
        )
    if settings.aml_temporal_ranking_enabled:
        temporal_query = _temporal_rank(body.query, units)
        _add_rrf_channel(
            fused,
            [unit_id for unit_id, _score in temporal_query],
            weight=settings.aml_temporal_weight,
            damping=settings.aml_rrf_k,
        )
    aggregation_query = _aggregation_rank(body.query, units)
    _add_rrf_channel(
        fused,
        [unit_id for unit_id, _score in aggregation_query],
        weight=settings.aml_aggregation_weight,
        damping=settings.aml_rrf_k,
    )
    if option_text:
        _add_rrf_channel(
            fused,
            [str(item["unit_id"]) for item in semantic_options if item.get("unit_id") in by_id],
            weight=settings.aml_option_weight,
            damping=settings.aml_rrf_k,
        )
        lexical_options = _bm25_rank(option_text, units)
        _add_rrf_channel(
            fused,
            [unit_id for unit_id, _score in lexical_options],
            weight=settings.aml_option_weight,
            damping=settings.aml_rrf_k,
        )

    ranked = sorted(fused.items(), key=lambda item: item[1], reverse=True)
    if not ranked:
        return AMLSearchResponse(data=[])
    if settings.aml_neighbor_evidence_enabled:
        _add_neighbor_evidence(
            fused,
            ranked,
            by_id,
            seed_limit=settings.aml_neighbor_seed_limit,
            window=settings.aml_neighbor_window,
            weight=settings.aml_neighbor_weight,
            damping=settings.aml_rrf_k,
        )
        _apply_role_bias(
            fused,
            by_id,
            user_boost=settings.aml_user_evidence_boost,
            assistant_penalty=settings.aml_assistant_evidence_penalty,
        )
        ranked = sorted(fused.items(), key=lambda item: item[1], reverse=True)
    else:
        _apply_role_bias(
            fused,
            by_id,
            user_boost=settings.aml_user_evidence_boost,
            assistant_penalty=settings.aml_assistant_evidence_penalty,
        )
        ranked = sorted(fused.items(), key=lambda item: item[1], reverse=True)
    if settings.aml_session_diversity_enabled:
        ranked = _diversify_by_session(
            ranked,
            by_id,
            max_per_session=settings.aml_session_max_items,
        )
    ranked_units = [by_id[unit_id] for unit_id, _score in ranked]
    reranked_ids = await _rerank_candidates(body.query, ranked_units, settings)
    rerank_scores: dict[str, float] | None = None
    if reranked_ids:
        ranked_by_id = dict(ranked)
        reranked_set = set(reranked_ids)
        ranked = [(unit_id, ranked_by_id[unit_id]) for unit_id in reranked_ids]
        ranked.extend(
            (unit_id, score)
            for unit_id, score in sorted(
                ranked_by_id.items(), key=lambda item: item[1], reverse=True
            )
            if unit_id not in reranked_set
        )
        total_ranked = len(ranked)
        rerank_scores = {
            unit_id: (total_ranked - index) / total_ranked
            for index, (unit_id, _score) in enumerate(ranked)
        }
    maximum = ranked[0][1]
    data = []
    for unit_id, score in ranked[: body.top_k]:
        unit = by_id[unit_id]
        data.append(
            AMLSearchItem(
                id=unit_id,
                content=str(unit.get("content") or unit["searchable_content"]),
                score=(
                    rerank_scores[unit_id]
                    if rerank_scores is not None
                    else score / maximum
                    if maximum
                    else 0.0
                ),
                created_at=str(unit.get("occurred_at") or unit.get("created_at")),
            )
        )
    return AMLSearchResponse(data=data)


async def clear(ctx: RequestContext, user_id: str) -> AMLClearResponse:
    deleted_units, deleted_requests = await aml_store.delete_user_data(
        ctx.tenant_id, ctx.org_id, user_id
    )
    await qdrant_store.delete_aml_memory_for_user(ctx.tenant_id, ctx.org_id, user_id)
    return AMLClearResponse(
        user_id=user_id,
        deleted_units=deleted_units,
        deleted_requests=deleted_requests,
    )


async def health() -> dict[str, Any]:
    mongo_ok, qdrant_ok = False, False
    errors: list[str] = []
    try:
        mongo_ok = await aml_store.ping()
    except Exception as exc:
        errors.append(f"mongo:{type(exc).__name__}")
    try:
        qdrant_ok, qdrant_error = await qdrant_store.ping_qdrant(record_failure=False)
        if not qdrant_ok:
            errors.append(f"qdrant:{qdrant_error}")
    except Exception as exc:
        errors.append(f"qdrant:{type(exc).__name__}")
    return {
        "status": "ok" if mongo_ok and qdrant_ok else "unavailable",
        "mongo": mongo_ok,
        "qdrant": qdrant_ok,
        "errors": errors,
    }
