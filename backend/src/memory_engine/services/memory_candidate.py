"""M13 memory candidate extraction and comparison without persistence side effects."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from pydantic import ValidationError as PydanticValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from memory_engine.config import get_settings
from memory_engine.core.context import RequestContext
from memory_engine.core.exceptions import ValidationError
from memory_engine.integrations import llm_client, memory_claim_store, oss_document_loader
from memory_engine.schemas.memory_candidate import (
    ExistingMemoryItem,
    MemoryCandidate,
    MemoryCandidateCompareRequest,
    MemoryCandidateCompareResponse,
    MemoryCandidateExtractRequest,
    MemoryCandidateExtractResponse,
    MemoryCandidateRejected,
    MemoryMergePreview,
)
from memory_engine.services import billing_service


logger = logging.getLogger(__name__)


_EXTRACT_SYSTEM = """You extract atomic user memories for a review screen.
Return one JSON object only. Never invent facts.
Each candidate must belong to exactly one allowed category:
- identity: the user's identity, occupation, company, responsibilities, and stable background
- projects: projects, teams, collaborators, goals, milestones, and work context
- preferences: working preferences, recurring habits, dislikes, and communication preferences
- terms: proper nouns, abbreviations, product names, and terminology that should be preserved

Return {"candidates": [...], "rejected": [...], "warnings": [...]}.
Each candidate has category, label, content, confidence, sensitivity, sensitive_type,
sensitive_reason, source_spans, and optional term. sensitivity is normal, sensitive, or
prohibited. A term object has text, aliases, and definition. source_spans use offsets from the
input text when certain. source_spans MUST be an empty list or an array of objects shaped like
{"start": 0, "end": 10, "segmentId": null}; never put source text strings in source_spans.
Split independent facts into separate candidates. If no useful memory exists, return an empty
candidates list."""

_COMPARE_SYSTEM = """You compare one proposed user-memory candidate with existing memories.
Return one JSON object only. result must be NEW, DUPLICATE, MERGE, CONFLICT, or REJECT.
DUPLICATE means the same fact. MERGE means the same subject can be safely combined without
losing information. CONFLICT means incompatible facts. NEW means distinct information.
REJECT means the proposal should not be stored as memory. Never modify data and never invent
item ids. matched_item_ids may only contain ids supplied in existing_items. For MERGE, return
merge_preview with content and base_item_id. Otherwise merge_preview must be null. Also return
confidence, reason_code, and a concise display_reason in the requested language."""


def _json_object(raw: str) -> dict[str, Any]:
    text = raw.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            raise ValidationError("EXTRACTION_FAILED: model returned invalid JSON") from exc
        try:
            value = json.loads(text[start : end + 1])
        except json.JSONDecodeError as nested:
            raise ValidationError("EXTRACTION_FAILED: model returned invalid JSON") from nested
    if not isinstance(value, dict):
        raise ValidationError("EXTRACTION_FAILED: model response must be a JSON object")
    return value


def _candidate_validation_summary(exc: Exception) -> list[dict[str, str]]:
    if not isinstance(exc, PydanticValidationError):
        return [{"type": type(exc).__name__, "location": "", "message": str(exc)}]
    return [
        {
            "type": str(error.get("type", "")),
            "location": ".".join(str(part) for part in error.get("loc", ())),
            "message": str(error.get("msg", "")),
        }
        for error in exc.errors()
    ]


def _rejected_candidate(raw_candidate: Any, reason: str) -> MemoryCandidateRejected:
    content = raw_candidate.get("content", "") if isinstance(raw_candidate, dict) else ""
    return MemoryCandidateRejected(content=str(content or "")[:16000], reason=reason)


def _normalize_candidate_source_spans(
    raw_candidate: Any, source_text: str
) -> tuple[Any, int, int]:
    """Convert quoted source evidence to offsets and discard unusable span values."""
    if not isinstance(raw_candidate, dict):
        return raw_candidate, 0, 0
    key = "source_spans" if "source_spans" in raw_candidate else "sourceSpans"
    raw_spans = raw_candidate.get(key)
    if raw_spans is None:
        return raw_candidate, 0, 0
    if not isinstance(raw_spans, list):
        normalized = dict(raw_candidate)
        normalized[key] = []
        return normalized, 0, 1

    spans: list[Any] = []
    converted = 0
    dropped = 0
    search_from = 0
    for raw_span in raw_spans:
        if isinstance(raw_span, dict):
            spans.append(raw_span)
            continue
        if isinstance(raw_span, str) and (quote := raw_span.strip()):
            start = source_text.find(quote, search_from)
            if start < 0:
                start = source_text.find(quote)
            if start >= 0:
                spans.append({"start": start, "end": start + len(quote)})
                search_from = start + len(quote)
                converted += 1
                continue
        dropped += 1

    normalized = dict(raw_candidate)
    normalized[key] = spans
    return normalized, converted, dropped


async def _complete(
    session: AsyncSession,
    ctx: RequestContext,
    *,
    prompt: str,
    system: str,
    request_id: str,
) -> tuple[dict[str, Any], str]:
    settings = get_settings()
    model = settings.openai_model
    raw, prompt_tokens, completion_tokens = await llm_client.chat_completion(
        prompt,
        system=system,
        model=model,
        llm_params={"temperature": 0},
    )
    await billing_service.emit_llm_completion(
        session,
        ctx,
        model_name=model,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        trace_id=request_id,
    )
    return _json_object(raw), model


async def extract_candidates(
    session: AsyncSession,
    ctx: RequestContext,
    body: MemoryCandidateExtractRequest,
) -> MemoryCandidateExtractResponse:
    source_text = body.source.text
    document_warnings: list[str] = []
    oss_url = (body.source.oss_url or "").strip()
    if oss_url:
        document = await oss_document_loader.load_document_text(oss_url)
        source_text = document.text
        document_warnings = document.warnings
    if not source_text:
        raise ValidationError("SOURCE_CONTENT_REQUIRED: text or ossUrl is required")
    payload = {
        "scene": body.scene,
        "language": body.language,
        "category_schema_version": body.category_schema_version,
        "allowed_categories": body.allowed_categories,
        "options": body.options.model_dump(by_alias=True),
        "source": {
            "type": "import_file" if oss_url else body.source.type,
            "sourceId": body.source.source_id,
            "text": source_text,
        },
    }
    parsed, model = await _complete(
        session,
        ctx,
        prompt=json.dumps(payload, ensure_ascii=False),
        system=_EXTRACT_SYSTEM,
        request_id=body.request_id,
    )
    raw_candidates = parsed.get("candidates") or []
    if not isinstance(raw_candidates, list):
        raise ValidationError("EXTRACTION_FAILED: candidates must be a list")

    candidates: list[MemoryCandidate] = []
    invalid_candidates: list[MemoryCandidateRejected] = []
    candidate_warnings: list[str] = []
    for index, raw_candidate in enumerate(raw_candidates):
        normalized_candidate, converted_spans, dropped_spans = (
            _normalize_candidate_source_spans(raw_candidate, source_text)
        )
        if converted_spans:
            candidate_warnings.append(
                f"Converted {converted_spans} quoted source spans at candidate index {index}"
            )
        if dropped_spans:
            candidate_warnings.append(
                f"Dropped {dropped_spans} invalid source spans at candidate index {index}"
            )
        try:
            candidate = MemoryCandidate.model_validate(normalized_candidate)
        except Exception as exc:
            logger.warning(
                "Skipping invalid extracted memory candidate: request_id=%s index=%s errors=%s",
                body.request_id,
                index,
                _candidate_validation_summary(exc),
            )
            invalid_candidates.append(
                _rejected_candidate(raw_candidate, "INVALID_CANDIDATE_FORMAT")
            )
            candidate_warnings.append(f"Skipped invalid candidate at index {index}")
            continue
        if candidate.category not in body.allowed_categories:
            logger.warning(
                "Skipping extracted memory candidate with disallowed category: "
                "request_id=%s index=%s category=%s",
                body.request_id,
                index,
                candidate.category,
            )
            invalid_candidates.append(
                _rejected_candidate(raw_candidate, "INVALID_CATEGORY")
            )
            candidate_warnings.append(f"Skipped disallowed category at index {index}")
            continue
        candidate.candidate_id = f"cand_{body.request_id.removeprefix('req_')}_{index + 1}"
        candidates.append(candidate)

    raw_rejected = parsed.get("rejected") or []
    if not isinstance(raw_rejected, list):
        raise ValidationError("EXTRACTION_FAILED: rejected must be a list")
    try:
        rejected = invalid_candidates + [
            MemoryCandidateRejected.model_validate(item) for item in raw_rejected
        ]
    except Exception as exc:
        raise ValidationError("EXTRACTION_FAILED: invalid rejected item") from exc
    raw_warnings = parsed.get("warnings") or []
    if not isinstance(raw_warnings, list):
        raise ValidationError("EXTRACTION_FAILED: warnings must be a list")
    warnings = (
        document_warnings
        + candidate_warnings
        + [str(item)[:1000] for item in raw_warnings]
    )
    return MemoryCandidateExtractResponse(
        request_id=body.request_id,
        model_version=model,
        category_schema_version=body.category_schema_version,
        candidates=candidates,
        rejected=rejected,
        warnings=warnings,
    )


def _claim_to_existing(claim: dict[str, Any]) -> ExistingMemoryItem | None:
    content = str(claim.get("text") or claim.get("value") or "").strip()
    item_id = str(claim.get("claim_id") or "").strip()
    if not content or not item_id:
        return None
    return ExistingMemoryItem(
        item_id=item_id,
        version=claim.get("revision"),
        category=str(claim.get("category") or claim.get("dimension") or "") or None,
        content=content[:16000],
    )


def _normalized_text(value: str) -> str:
    return re.sub(r"\s+", "", value).casefold()


async def compare_candidate(
    session: AsyncSession,
    ctx: RequestContext,
    body: MemoryCandidateCompareRequest,
) -> MemoryCandidateCompareResponse:
    namespace = {"type": body.namespace_type, "id": body.namespace_id}
    claims = await memory_claim_store.list_current_claims(
        ctx.tenant_id,
        ctx.org_id,
        body.user_id,
        namespace,
        limit=body.candidate_limit,
    )
    existing = [item for claim in claims if (item := _claim_to_existing(claim)) is not None]

    settings = get_settings()
    if body.candidate.sensitivity == "prohibited":
        return MemoryCandidateCompareResponse(
            request_id=body.request_id,
            model_version=f"{settings.openai_model}:deterministic",
            result="REJECT",
            confidence=1.0,
            reason_code="PROHIBITED_CONTENT",
            display_reason="该内容不允许加入记忆",
        )
    if not existing:
        return MemoryCandidateCompareResponse(
            request_id=body.request_id,
            model_version=f"{settings.openai_model}:deterministic",
            result="NEW",
            confidence=1.0,
            reason_code="NO_EXISTING_MEMORY",
            display_reason="未找到可比较的现有记忆",
        )

    candidate_text = _normalized_text(body.candidate.content)
    exact = next(
        (item for item in existing if _normalized_text(item.content) == candidate_text), None
    )
    if exact is not None:
        return MemoryCandidateCompareResponse(
            request_id=body.request_id,
            model_version=f"{settings.openai_model}:deterministic",
            result="DUPLICATE",
            confidence=1.0,
            matched_item_ids=[exact.item_id],
            reason_code="EXACT_MATCH",
            display_reason="与现有记忆内容完全相同",
        )

    payload = {
        "language": body.language,
        "candidate": body.candidate.model_dump(by_alias=True, exclude_none=True),
        "existing_items": [item.model_dump(by_alias=True) for item in existing],
    }
    parsed, model = await _complete(
        session,
        ctx,
        prompt=json.dumps(payload, ensure_ascii=False),
        system=_COMPARE_SYSTEM,
        request_id=body.request_id,
    )
    valid_ids = {item.item_id: item for item in existing}
    matched = [str(item) for item in (parsed.get("matched_item_ids") or [])]
    if any(item_id not in valid_ids for item_id in matched):
        raise ValidationError("COMPARE_FAILED: model returned an unknown item id")
    result = str(parsed.get("result") or "").upper()
    if result not in {"NEW", "DUPLICATE", "MERGE", "CONFLICT", "REJECT"}:
        raise ValidationError("COMPARE_FAILED: invalid comparison result")
    if result in {"DUPLICATE", "MERGE", "CONFLICT"} and not matched:
        raise ValidationError(f"COMPARE_FAILED: {result} requires a matched item")

    merge_preview = None
    raw_preview = parsed.get("merge_preview")
    if result == "MERGE":
        if not isinstance(raw_preview, dict):
            raise ValidationError("COMPARE_FAILED: MERGE requires merge_preview")
        base_item_id = str(raw_preview.get("base_item_id") or "")
        if base_item_id not in valid_ids:
            raise ValidationError("COMPARE_FAILED: invalid merge preview base item")
        if base_item_id not in matched:
            raise ValidationError("COMPARE_FAILED: merge base must be a matched item")
        base = valid_ids[base_item_id]
        merge_preview = MemoryMergePreview(
            content=str(raw_preview.get("content") or "").strip(),
            base_item_id=base_item_id,
            base_version=base.version,
        )

    try:
        confidence = max(0.0, min(1.0, float(parsed.get("confidence", 0.0))))
    except (TypeError, ValueError) as exc:
        raise ValidationError("COMPARE_FAILED: confidence must be numeric") from exc
    return MemoryCandidateCompareResponse(
        request_id=body.request_id,
        model_version=model,
        result=result,
        confidence=confidence,
        matched_item_ids=matched,
        reason_code=str(parsed.get("reason_code") or result),
        display_reason=str(parsed.get("display_reason") or result),
        merge_preview=merge_preview,
    )
