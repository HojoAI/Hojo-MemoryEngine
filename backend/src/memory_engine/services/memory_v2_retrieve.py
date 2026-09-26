"""P0/P1 policy-first hybrid retrieval and bundle-based memory call."""

from __future__ import annotations

import hashlib
import json
import logging
import math
import re
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from typing import Any
from uuid import uuid4

from pydantic import ValidationError as PydanticValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from memory_engine.config import get_settings
from memory_engine.core.context import RequestContext
from memory_engine.core.exceptions import ForbiddenError, NotFoundError, ValidationError
from memory_engine.integrations import llm_client, memory_claim_store, qdrant_store
from memory_engine.schemas.memory_claim import (
    MemoryBundleItem,
    MemoryBundleOut,
    MemoryCallV2Request,
    MemoryCallV2Response,
    MemoryProvenance,
    MemoryRetrieveV2Request,
    MemoryUsageContext,
)
from memory_engine.services import billing_service, memory_policy, rules as rule_service

logger = logging.getLogger(__name__)

_RERANK_SYSTEM = (
    "You rank already-authorized memory candidates. Return JSON only with key selected. "
    "Each selected item must use an existing claim_id and contain relevance (0..1), usage, "
    "and reason. Prefer direct first-person factual evidence that answers the exact question. "
    "For counting questions, select only actual operands and reject hypothetical examples, "
    "instructions, plans belonging to third parties, and merely topically similar text. "
    "Never create facts or claim ids."
)

_ACTION_QUERY_PHRASES: tuple[tuple[str, str], ...] = (
    ("pick up", r"\bpick\s+up\b"),
    ("return", r"\breturn(?:ed|ing|s)?\b"),
    ("cancel", r"\bcancel(?:led|ing|s)?\b"),
    ("pay", r"\bpay(?:ing|ment|ments|s)?\b"),
    ("schedule", r"\bschedul(?:e|ed|ing|es)\b"),
    ("renew", r"\brenew(?:ed|ing|s)?\b"),
)

_QUERY_TERM_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "did",
    "do",
    "does",
    "for",
    "from",
    "have",
    "how",
    "i",
    "in",
    "is",
    "it",
    "many",
    "me",
    "my",
    "of",
    "on",
    "or",
    "the",
    "this",
    "to",
    "what",
    "when",
    "where",
    "which",
    "who",
    "with",
    "you",
    "your",
}

# Keep the small lexical fallback deliberately dependency-free, but cover the
# few English inflections that are both common in user questions and not
# handled by suffix stripping (``lead``/``led`` in particular).
_IRREGULAR_TERM_VARIANTS: dict[str, tuple[str, ...]] = {
    "lead": ("lead", "led"),
}

_MONEY_QUERY_TERMS = {
    "amount",
    "budget",
    "cost",
    "expense",
    "expenses",
    "money",
    "paid",
    "pay",
    "price",
    "spent",
    "spend",
    "total",
}
_MONEY_AMOUNT_PATTERN = re.compile(
    r"(?:[$€£¥]\s?\d[\d,]*(?:\.\d{1,2})?|\b\d[\d,]*(?:\.\d{1,2})?\s*(?:usd|dollars?|euros?|pounds?|yuan)\b)",
    re.I,
)
_DATE_PATTERN = re.compile(r"\b20\d{2}[-/]\d{1,2}(?:[-/]\d{1,2})?\b")
_NATURAL_DATE_PATTERN = re.compile(
    r"\b(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
    r"Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|"
    r"Dec(?:ember)?)\s+(?:(\d{1,2})(?:st|nd|rd|th)?\s*,?\s*)?(20\d{2})\b",
    re.I,
)
_MONTH_NUMBERS = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}
_TEMPORAL_HISTORY_PATTERN = re.compile(
    r"\b(?:this|last|next|previous|past|current|following|prior|earlier|later)"
    r"\s+(?:day|week|month|year|morning|afternoon|evening|night)|"
    r"\b(?:day|week|month|year)\s+(?:before|after)|"
    r"\b(?:since|until|between)\b|"
    r"\b(?:yesterday|tomorrow|today|tonight)\b",
    re.I,
)
_FACT_CHANGE_PATTERN = re.compile(
    r"\b(?:change(?:d|s)?|updated?|previously|formerly|originally|"
    r"no\s+longer|use(?:d)?\s+to|stopped?|switched?|replaced?|before\s+I|over\s+time)\b",
    re.I,
)
_AGGREGATION_QUERY_PATTERN = re.compile(
    r"\b(?:how many|how much|total|combined|all|number of|sum of)\b", re.I
)
_AGGREGATION_OPERAND_PATTERN = re.compile(
    r"(?:[$€£¥]\s?\d|\b(?:\d+(?:\.\d+)?|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)"
    r"\s+(?:[a-z]+\s+){0,2}(?:days?|weeks?|months?|years?|hours?|minutes?|items?|plants?|projects?|kits?)\b|\b\d+\s*/\s*\d+\b)",
    re.I,
)
# A few three-letter terms are high-signal in personal-memory questions. The
# general four-character floor remains useful for avoiding a broad Mongo scan.
_SHORT_RECALL_TERMS = {"bed", "ent", "uti"}
_AGGREGATION_TERM_STOPWORDS = {
    "all",
    "amount",
    "combined",
    "count",
    "how",
    "many",
    "much",
    "number",
    "spent",
    "spend",
    "total",
}


def _as_utc(value: datetime) -> datetime:
    """Normalize MongoDB datetimes, which are UTC but may be returned without tzinfo."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _strip_json_fence(raw: str) -> str:
    text = raw.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    return re.sub(r"\s*```$", "", text)


def _lexical_score(query: str, claim: dict[str, Any]) -> float:
    text = str(claim.get("text") or claim.get("value") or "")
    if not query.strip():
        return min(1.0, float(claim.get("importance", 3)) / 5.0)
    if query in text or text in query:
        return 1.0

    # Token overlap is more useful than raw character overlap for benchmark
    # questions. Normalize common English inflections so "graduate" matches
    # "graduated" while long unrelated documents do not dominate by length.
    def tokens(value: str) -> set[str]:
        words = re.findall(r"[a-z0-9]+", value.lower())
        stopwords = {
            "a",
            "an",
            "and",
            "are",
            "did",
            "do",
            "for",
            "i",
            "in",
            "is",
            "it",
            "me",
            "my",
            "of",
            "the",
            "to",
            "what",
            "with",
        }
        normalized = set()
        for word in words:
            if word in stopwords:
                continue
            for suffix in ("ing", "ed", "es", "s"):
                if len(word) > len(suffix) + 3 and word.endswith(suffix):
                    word = word[: -len(suffix)]
                    break
            if word.endswith("at"):
                word += "e"
            normalized.add(word)
        return normalized

    query_tokens = tokens(query)
    text_tokens = tokens(text)
    if query_tokens and text_tokens:
        overlap = len(query_tokens & text_tokens) / len(query_tokens)
        if overlap:
            return min(
                1.0,
                0.75 * overlap + 0.25 * SequenceMatcher(None, query.lower(), text.lower()).ratio(),
            )
    q_chars, t_chars = set(query), set(text)
    overlap = len(q_chars & t_chars) / max(1, len(q_chars | t_chars))
    sequence = SequenceMatcher(None, query, text).ratio()
    return min(1.0, 0.65 * overlap + 0.35 * sequence)


def _action_phrases(query: str) -> list[str]:
    """Extract explicit pending-action verbs that warrant lexical recall."""
    return [phrase for phrase, pattern in _ACTION_QUERY_PHRASES if re.search(pattern, query, re.I)]


def _action_phrase_coverage(text: str, phrases: list[str]) -> float:
    if not phrases:
        return 0.0
    lowered = text.lower()
    return sum(phrase in lowered for phrase in phrases) / len(phrases)


def _query_recall_terms(query: str, *, max_terms: int = 8) -> list[str]:
    """Pick stable content words for a bounded Mongo lexical recall pass."""
    terms: list[str] = []
    seen: set[str] = set()
    for word in re.findall(r"[a-z0-9]+", query.lower()):
        if (len(word) < 4 and word not in _SHORT_RECALL_TERMS) or word in _QUERY_TERM_STOPWORDS:
            continue
        # Search the simple stem so singular/plural and common suffixes meet.
        stem = word
        for suffix in ("ing", "ed", "es", "s"):
            if len(stem) > len(suffix) + 3 and stem.endswith(suffix):
                stem = stem[: -len(suffix)]
                break
        if stem not in seen:
            seen.add(stem)
            terms.append(stem)
        if len(terms) >= max_terms:
            break
    return terms


def _query_term_coverage(query: str, text: str) -> float:
    """Return the fraction of stable query terms present in a claim."""
    terms = _query_recall_terms(query)
    if not terms:
        return 0.0
    lowered = text.lower()
    return sum(_term_matches(lowered, term) for term in terms) / len(terms)


def _term_matches(lowered_text: str, term: str) -> bool:
    """Match a normalized query term against simple regular/irregular forms."""
    variants = _IRREGULAR_TERM_VARIANTS.get(term, (term,))
    return any(
        bool(re.search(rf"\b{re.escape(variant)}\w*\b", lowered_text)) for variant in variants
    )


def _is_money_aggregation_query(query: str) -> bool:
    tokens = set(re.findall(r"[a-z0-9]+", query.lower()))
    return bool(tokens & _MONEY_QUERY_TERMS) and bool(
        re.search(r"\b(?:how much|total|spent|spend|cost|price|expense)\b", query, re.I)
    )


def _monetary_evidence_coverage(query: str, text: str) -> float:
    """Identify explicit priced operands for a scoped money aggregation query.

    A broad vector query about expenses otherwise tends to rank recurring
    activity mentions (for example bike mileage) over the one historical
    message that contains the price needed for the calculation.
    """
    if not _is_money_aggregation_query(query) or not _MONEY_AMOUNT_PATTERN.search(text):
        return 0.0
    subject_terms = [term for term in _query_recall_terms(query) if term not in _MONEY_QUERY_TERMS]
    if not subject_terms:
        return 0.5
    lowered = text.lower()
    return 1.0 if any(_term_matches(lowered, term) for term in subject_terms) else 0.35


def _needs_aggregation_rerank(query: str) -> bool:
    return bool(_AGGREGATION_QUERY_PATTERN.search(query))


def _retrieval_query_facets(query: str, *, max_queries: int) -> list[str]:
    """Build bounded focused queries for compound questions.

    EverOS' multi-round retriever keeps each sub-query in an independent RRF
    block so specialist evidence is not drowned out by the broad original
    query.  This deterministic first stage adopts the same coverage property
    without introducing an LLM call on every retrieval.  It only expands
    explicit conjunctions and always keeps the original query as facet zero.
    """
    original = query.strip()
    if not original or max_queries <= 1:
        return [original] if original else []
    parts = [
        part.strip(" \t\r\n?.,;:")
        for part in re.split(r"\s+(?:and|or|versus|vs\.?|as well as)\s+", original, flags=re.I)
        if part.strip(" \t\r\n?.,;:")
    ]
    if len(parts) < 2:
        return [original]

    facet_stopwords = _QUERY_TERM_STOPWORDS | {
        "am",
        "both",
        "can",
        "could",
        "had",
        "has",
        "need",
        "should",
        "things",
        "was",
        "were",
        "will",
        "would",
    }

    def content_terms(value: str) -> list[str]:
        return [
            word
            for word in re.findall(r"[a-z0-9]+", value.lower())
            if word not in facet_stopwords and (len(word) >= 3 or word in _SHORT_RECALL_TERMS)
        ]

    all_terms = content_terms(original)
    if len(all_terms) < 3:
        return [original]
    anchors = all_terms[:2]
    facets = [original]
    for part in parts:
        terms = content_terms(part)
        if not terms:
            continue
        if len(terms) < 2:
            terms = [*anchors, *terms]
        focused = " ".join(dict.fromkeys(terms))
        if focused and focused.lower() != original.lower() and focused not in facets:
            facets.append(focused)
        if len(facets) >= max_queries:
            break
    return facets


def _prioritize_query_facet_coverage(
    candidates: list[dict[str, Any]], *, facet_count: int
) -> tuple[list[dict[str, Any]], int]:
    """Place the best candidate for every focused facet before fallbacks.

    Facet zero is the original broad query and retains the highest-ranked
    candidate.  Additional facets each receive at most one guaranteed slot;
    all unselected candidates remain available in their existing score order.
    """
    if facet_count <= 1 or not candidates:
        return candidates, 0
    core: list[dict[str, Any]] = []
    selected_ids: set[str] = set()
    for facet_index in range(facet_count):
        candidate = next(
            (
                item
                for item in candidates
                if facet_index in item.get("_query_facets", set())
                and str(item.get("claim_id")) not in selected_ids
            ),
            None,
        )
        if candidate is None:
            continue
        core.append(candidate)
        selected_ids.add(str(candidate.get("claim_id")))
    remaining = [item for item in candidates if str(item.get("claim_id")) not in selected_ids]
    promoted = sum(1 for index, item in enumerate(core) if candidates.index(item) != index)
    return core + remaining, promoted


def _aggregation_evidence_coverage(query: str, text: str) -> float:
    """Score concrete operands for a count, duration, or money aggregation.

    A query such as "total bike expenses" is semantically close to many bike
    discussions. This deterministic preference keeps records carrying an
    actual amount/duration/count in the final top-k without another LLM call.
    """
    if not _needs_aggregation_rerank(query) or not _AGGREGATION_OPERAND_PATTERN.search(text):
        return 0.0
    terms = [
        term
        for term in _query_recall_terms(query)
        if term not in _AGGREGATION_TERM_STOPWORDS and term not in _MONEY_QUERY_TERMS
    ]
    if not terms:
        return 0.5
    return sum(_term_matches(text.lower(), term) for term in terms) / len(terms)


def _evidence_speaker_role(claim: dict[str, Any]) -> str | None:
    """Return a normalized source role only when provenance states one."""
    roles = {
        str(provenance.get("speaker_role") or "").strip().lower()
        for provenance in claim.get("provenance") or []
    }
    if roles & {"user", "human", "customer", "speaker_a", "speaker_b"}:
        return "user"
    if roles & {"assistant", "bot", "ai", "system"}:
        return "assistant"
    return None


def _query_requests_history(query: str) -> bool:
    """Use historical claims only for explicitly time-scoped questions."""
    return bool(
        _query_date_tokens(query)
        or _TEMPORAL_HISTORY_PATTERN.search(query)
        or _FACT_CHANGE_PATTERN.search(query)
        or re.search(
            r"\b(?:sequence|in order|progress|earlier|previous|as of)\b",
            query,
            re.I,
        )
    )


def _claim_matches_query_date(query: str, claim: dict[str, Any]) -> bool:
    dates = set(_query_date_tokens(query))
    if not dates:
        return False
    evidence: list[str] = []
    for provenance in claim.get("provenance") or []:
        for key in ("occurred_at", "effective_at"):
            value = provenance.get(key)
            if value:
                evidence.append(str(value))
    for key in ("effective_at", "occurred_at"):
        value = claim.get(key)
        if value:
            evidence.append(str(value))
    normalized_evidence = [_normalize_date_token(value) for value in evidence]
    return any(
        evidence_date == query_date
        or (len(query_date) == 7 and evidence_date.startswith(query_date + "-"))
        for query_date in dates
        for evidence_date in normalized_evidence
        if evidence_date
    )


def _query_date_tokens(query: str) -> list[str]:
    """Normalize ISO and English month-name dates found in a question."""
    dates: list[str] = []
    for value in _DATE_PATTERN.findall(query):
        normalized = _normalize_date_token(value)
        if normalized and normalized not in dates:
            dates.append(normalized)
    for month_name, day_text, year_text in _NATURAL_DATE_PATTERN.findall(query):
        month = _MONTH_NUMBERS[month_name[:3].lower()]
        try:
            if day_text:
                normalized = (
                    datetime(int(year_text), month, int(day_text), tzinfo=timezone.utc)
                    .date()
                    .isoformat()
                )
            else:
                normalized = f"{int(year_text):04d}-{month:02d}"
        except ValueError:
            continue
        if normalized not in dates:
            dates.append(normalized)
    return dates


def _normalize_date_token(value: str) -> str:
    match = re.search(r"20\d{2}[-/]\d{1,2}(?:[-/]\d{1,2})?", value)
    return match.group(0).replace("/", "-") if match else ""


def _as_of_cutoff(query: str) -> datetime | None:
    """Return an exclusive UTC cutoff for an explicit dated snapshot."""
    match = re.search(r"\b(?:as of|on|by)\s+(.+?)(?:[?!;]|$)", query, re.I)
    if not match:
        return None
    dates = _query_date_tokens(match.group(1))
    if not dates:
        return None
    try:
        normalized = dates[0]
        if len(normalized) == 7:
            year, month = (int(part) for part in normalized.split("-"))
            if month == 12:
                return datetime(year + 1, 1, 1, tzinfo=timezone.utc)
            return datetime(year, month + 1, 1, tzinfo=timezone.utc)
        return datetime.fromisoformat(normalized).replace(tzinfo=timezone.utc) + timedelta(days=1)
    except ValueError:
        return None


def _claim_as_of_exclusion(claim: dict[str, Any], cutoff: datetime) -> str | None:
    """Exclude only versions known to be outside the requested snapshot."""

    def parse(value: Any) -> datetime | None:
        if isinstance(value, datetime):
            return _as_utc(value)
        if not isinstance(value, str) or not value:
            return None
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return _as_utc(parsed)

    effective = parse(claim.get("effective_at"))
    observed = [
        stamp
        for provenance in claim.get("provenance") or []
        if (stamp := parse(provenance.get("occurred_at"))) is not None
    ]
    start = effective or min(observed, default=None)
    if start is not None and start >= cutoff:
        return "future"
    superseded = parse(claim.get("superseded_at"))
    if superseded is not None and superseded < cutoff:
        return "superseded"
    return None


def _merge_excluded_counts(target: dict[str, int], incoming: dict[str, int]) -> None:
    """Accumulate policy-filter telemetry without treating it as a list."""
    for key, value in incoming.items():
        target[key] = target.get(key, 0) + int(value)


async def _rerank_with_llm(
    session: AsyncSession,
    ctx: RequestContext,
    body: MemoryRetrieveV2Request,
    candidates: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    payload = [
        {
            "claim_id": c["claim_id"],
            "dimension": c["dimension"],
            "text": c["text"],
            "fact_status": c["fact_status"],
            "base_score": c["_score"],
        }
        for c in candidates[: body.candidate_limit]
    ]
    prompt = json.dumps(
        {
            "task": {
                "module_id": body.usage_context.module_id,
                "scenario": body.usage_context.scenario,
                "query": body.query,
            },
            "candidates": payload,
            "max_items": body.top_k,
        },
        ensure_ascii=False,
    )
    llm = body.llm
    text, pt, ct = await llm_client.chat_completion(
        prompt,
        system=_RERANK_SYSTEM,
        base_url=llm.base_url if llm else None,
        api_key=llm.api_key if llm else None,
        model=llm.model_name if llm else None,
        llm_params={"temperature": 0},
    )
    await billing_service.emit_llm_completion(
        session,
        ctx,
        model_name=(llm.model_name if llm and llm.model_name else get_settings().openai_model),
        prompt_tokens=pt,
        completion_tokens=ct,
    )
    parsed = json.loads(_strip_json_fence(text))
    valid_ids = {c["claim_id"] for c in candidates}
    selected: dict[str, dict[str, Any]] = {}
    for item in parsed.get("selected", []):
        claim_id = str(item.get("claim_id") or "")
        if claim_id not in valid_ids:
            continue
        score = max(0.0, min(1.0, float(item.get("relevance", 0.0))))
        selected[claim_id] = {
            "score": score,
            "usage": str(item.get("usage") or ""),
            "reason": str(item.get("reason") or ""),
        }
    return selected


def _estimate_tokens(text: str) -> int:
    return max(1, math.ceil(len(text) / 2))


def _compact_aggregation_text(text: str, query: str, max_chars: int) -> str:
    """Keep query-bearing fact sentences from oversized aggregation claims."""
    if len(text) <= max_chars:
        return text
    parts = [part.strip() for part in re.split(r"(?<=[.!?。！？\n])\s*", text) if part.strip()]
    if not parts:
        return text[:max_chars]
    terms = _query_recall_terms(query)
    ranked = sorted(
        enumerate(parts),
        key=lambda pair: (
            bool(_AGGREGATION_OPERAND_PATTERN.search(pair[1])),
            sum(_term_matches(pair[1].lower(), term) for term in terms),
            -pair[0],
        ),
        reverse=True,
    )
    chosen: list[tuple[int, str]] = []
    used = 0
    for index, part in ranked:
        if len(part) > max_chars:
            operand = _AGGREGATION_OPERAND_PATTERN.search(part)
            if operand:
                start = max(0, min(operand.start() - max_chars // 3, len(part) - max_chars))
                part = part[start : start + max_chars]
        extra = len(part) + (1 if chosen else 0)
        if used + extra > max_chars:
            continue
        chosen.append((index, part))
        used += extra
    if not chosen:
        return text[:max_chars]
    chosen.sort(key=lambda pair: pair[0])
    return " ".join(part for _, part in chosen)


async def _resolve_profile(
    session: AsyncSession,
    ctx: RequestContext,
    body: MemoryRetrieveV2Request,
) -> tuple[MemoryRetrieveV2Request, str | None, int | None, dict[str, Any]]:
    """Resolve an optional server-side V2 retrieval profile without changing legacy calls."""
    if not body.rule_name:
        return body, None, None, {}
    row = await rule_service.get_active_retrieve(session, ctx, body.rule_name, implicit=True)
    if row is None:
        raise NotFoundError(f"retrieve_rule '{body.rule_name}' not found")
    config = dict(row.rule_config_json or {})
    updates: dict[str, Any] = {"method": str(row.retrieve_method or body.method).upper()}
    for key in ("required_dimensions", "top_k", "candidate_limit", "max_tokens", "min_score"):
        if key in config and config[key] is not None:
            updates[key] = config[key]
    try:
        resolved = MemoryRetrieveV2Request.model_validate({**body.model_dump(), **updates})
    except PydanticValidationError as exc:
        raise ValidationError(f"invalid retrieve_rule '{body.rule_name}': {exc}") from exc
    return resolved, row.rule_name, row.version, config


def _normalized(value: Any) -> str:
    if isinstance(value, (dict, list)):
        value = json.dumps(value, ensure_ascii=False, sort_keys=True)
    return "".join(char.lower() for char in str(value or "") if char.isalnum())


def _relation_to_current(claim: dict[str, Any], body: MemoryRetrieveV2Request) -> str:
    current = body.current_context
    if current is None:
        return "increment"
    claim_text = _normalized(claim.get("text"))
    current_text = _normalized(current.raw_text)
    if len(claim_text) >= 8 and claim_text in current_text:
        return "duplicate"
    claim_numbers = set(re.findall(r"\d+(?:\.\d+)?", str(claim.get("text") or "")))
    value_numbers = set(
        re.findall(r"\d+(?:\.\d+)?", json.dumps(claim.get("value"), ensure_ascii=False))
    )
    current_numbers = set(re.findall(r"\d+(?:\.\d+)?", current.raw_text))
    if claim_numbers and value_numbers and value_numbers.issubset(current_numbers):
        return "duplicate"
    for fact in current.claims:
        if fact.dimension != claim.get("dimension"):
            continue
        claim_key = str(claim.get("claim_key") or "")
        if fact.claim_key and claim_key and fact.claim_key != claim_key:
            continue
        old_value, new_value = _normalized(claim.get("value")), _normalized(fact.value)
        if old_value and new_value:
            return "duplicate" if old_value == new_value else "conflict"
        if claim_text and _normalized(fact.text) == claim_text:
            return "duplicate"
    return "increment"


def _no_hit_reason(
    excluded: dict[str, int], duplicate_ids: list[str], conflict_ids: list[str]
) -> str:
    if duplicate_ids:
        return "current_duplicate"
    if conflict_ids:
        return "current_conflict"
    for key in (
        "permission_denied",
        "scope_mismatch",
        "conflicted_or_inactive",
        "expired",
        "below_score",
        "token_budget",
    ):
        if excluded.get(key, 0):
            return key
    return "no_candidate"


def _evidence_group_key(claim: dict[str, Any]) -> str | None:
    """Return a stable session/source group without inventing client metadata."""
    for provenance in claim.get("provenance") or []:
        for key in ("meeting_id", "source_id"):
            value = provenance.get(key)
            if value:
                return f"{key}:{value}"
    return None


def _diversify_by_evidence_group(
    candidates: list[dict[str, Any]], *, max_per_group: int
) -> tuple[list[dict[str, Any]], int]:
    """Prefer diverse evidence groups while preserving a score-ordered fallback.

    The second pass is important: a single-session question must still be able
    to use more than ``max_per_group`` claims when no other session is relevant.
    """
    if max_per_group < 1:
        return candidates, 0
    selected: list[dict[str, Any]] = []
    deferred: list[dict[str, Any]] = []
    counts: dict[str, int] = {}
    for claim in candidates:
        group = _evidence_group_key(claim)
        if group is None or counts.get(group, 0) < max_per_group:
            selected.append(claim)
            if group is not None:
                counts[group] = counts.get(group, 0) + 1
        else:
            deferred.append(claim)
    return selected + deferred, len(deferred)


def _aggregation_rerank_shortlist(
    candidates: list[dict[str, Any]], limit: int
) -> list[dict[str, Any]]:
    """Expose independent source events to the judge before its hard cutoff.

    Ordinary score ordering can fill the whole shortlist with claims from one
    verbose session. The final ranking still belongs to the judge; this only
    changes which authorized candidates it can inspect.
    """
    diversified, _ = _diversify_by_evidence_group(candidates, max_per_group=2)
    return diversified[: max(1, limit)]


def _diagnostic_ids(claims: list[dict[str, Any]], limit: int) -> dict[str, Any]:
    """Bound ID-only diagnostic output; never serialize claim content."""
    ids = [str(claim["claim_id"]) for claim in claims if claim.get("claim_id")]
    return {"count": len(ids), "claim_ids": ids[:limit], "omitted": max(0, len(ids) - limit)}


def _diagnostic_ranked(claims: list[dict[str, Any]], limit: int) -> dict[str, Any]:
    """Include only stable identifiers, source groups and numeric scores."""

    def safe_source_group(claim: dict[str, Any]) -> str | None:
        group = _evidence_group_key(claim)
        if group is None:
            return None
        if re.fullmatch(r"[A-Za-z0-9_.:/-]{1,128}", group):
            return group
        return "sha256:" + hashlib.sha256(group.encode("utf-8")).hexdigest()[:16]

    return {
        "count": len(claims),
        "items": [
            {
                "claim_id": str(claim["claim_id"]),
                "source_group": safe_source_group(claim),
                "score": round(float(claim.get("_score", 0.0)), 4),
            }
            for claim in claims[:limit]
        ],
        "omitted": max(0, len(claims) - limit),
    }


async def retrieve(
    session: AsyncSession,
    ctx: RequestContext,
    body: MemoryRetrieveV2Request,
) -> MemoryBundleOut:
    body, profile_id, profile_version, profile = await _resolve_profile(session, ctx, body)
    memory_policy.ensure_retrieve_permission(ctx, body.usage_context)
    namespace = body.usage_context.namespace.model_dump(exclude_none=True)
    allow_historical = getattr(
        get_settings(), "memory_retrieve_historical_enabled", False
    ) and _query_requests_history(body.query)
    claims = await memory_claim_store.list_current_claims(
        ctx.tenant_id,
        ctx.org_id,
        body.user_id,
        namespace,
        dimensions=body.required_dimensions or None,
        limit=body.candidate_limit,
        include_history=allow_historical,
    )
    candidates, excluded = memory_policy.filter_claims(
        ctx,
        claims,
        body.usage_context,
        llm_requested=body.method == "LLM",
        allow_historical=allow_historical,
    )
    retrieval_trace: dict[str, Any] = {
        "mongo_candidates": len(claims),
        "authorized_candidates": len(candidates),
        "action_phrases": [],
        "action_recalled": 0,
        "lexical_terms": [],
        "lexical_recalled": 0,
        "monetary_evidence_boosted": 0,
        "aggregation_evidence_boosted": 0,
        "temporal_evidence_boosted": 0,
        "user_evidence_boosted": 0,
        "assistant_evidence_penalized": 0,
        "vector_hits": 0,
        "vector_hydrated": 0,
        "query_facet_count": 1,
        "query_facet_hits": [],
        "query_facet_candidates_promoted": 0,
        "evidence_neighbors_recalled": 0,
        "evidence_groups_deferred": 0,
        "historical_mode": allow_historical,
        "as_of_future_excluded": 0,
        "as_of_superseded_excluded": 0,
        "errors": [],
    }

    # Multi-action questions are often underspecified for a single embedding:
    # e.g. "what do I need to pick up or return?". Recall direct evidence for
    # each stated action from the same authorized user namespace, then merge it
    # with the ordinary candidate window before vector/lexical ranking.
    action_phrases = _action_phrases(body.query)
    settings = get_settings()
    diagnostics_enabled = bool(getattr(settings, "memory_retrieve_diagnostics_enabled", False))
    diagnostics_limit = int(getattr(settings, "memory_retrieve_diagnostics_max_ids", 200))
    diagnostic_stages: dict[str, Any] = {}
    if diagnostics_enabled:
        diagnostic_stages["mongo"] = {
            "fetched": _diagnostic_ids(claims, diagnostics_limit),
            "authorized": _diagnostic_ids(candidates, diagnostics_limit),
            "excluded": dict(excluded),
        }
    retrieval_trace["action_phrases"] = action_phrases
    if action_phrases and getattr(settings, "memory_retrieve_action_recall_enabled", True):
        try:
            action_claims = await memory_claim_store.list_current_claims_matching_phrases(
                ctx.tenant_id,
                ctx.org_id,
                body.user_id,
                namespace,
                action_phrases,
                dimensions=body.required_dimensions or None,
                limit=getattr(settings, "memory_retrieve_action_recall_limit", 8),
                include_history=allow_historical,
            )
            raw_action_claims = action_claims
            action_claims, action_excluded = memory_policy.filter_claims(
                ctx,
                action_claims,
                body.usage_context,
                llm_requested=body.method == "LLM",
                allow_historical=allow_historical,
            )
            known_ids = {str(claim["claim_id"]) for claim in candidates}
            action_new = [
                claim for claim in action_claims if str(claim["claim_id"]) not in known_ids
            ]
            candidates.extend(action_new)
            retrieval_trace["action_recalled"] = len(action_new)
            _merge_excluded_counts(excluded, action_excluded)
            if diagnostics_enabled:
                diagnostic_stages["action"] = {
                    "fetched": _diagnostic_ids(raw_action_claims, diagnostics_limit),
                    "authorized": _diagnostic_ids(action_claims, diagnostics_limit),
                    "added": _diagnostic_ids(action_new, diagnostics_limit),
                    "already_present": len(action_claims) - len(action_new),
                    "excluded": action_excluded,
                }
        except Exception as exc:
            # Action recall is an optional quality enhancement. Preserve the
            # legacy retrieval path if the backing text index is unavailable.
            logger.warning("memory action recall failed: %s", exc)
            retrieval_trace["errors"].append("action_recall_failed")

    # Lexical recall is intentionally separate from the normal candidate
    # window. It protects precise entities and aggregation operands that a
    # single broad embedding query often misses.
    lexical_terms = _query_recall_terms(body.query)
    retrieval_trace["lexical_terms"] = lexical_terms
    lexical_recalled_ids: set[str] = set()
    if lexical_terms and getattr(settings, "memory_retrieve_lexical_recall_enabled", True):
        try:
            lexical_claims = await memory_claim_store.list_current_claims_matching_terms(
                ctx.tenant_id,
                ctx.org_id,
                body.user_id,
                namespace,
                lexical_terms,
                dimensions=body.required_dimensions or None,
                limit=max(
                    getattr(settings, "memory_retrieve_lexical_recall_limit", 80),
                    160 if allow_historical or _needs_aggregation_rerank(body.query) else 0,
                ),
                include_history=allow_historical,
            )
            raw_lexical_claims = lexical_claims
            lexical_claims, lexical_excluded = memory_policy.filter_claims(
                ctx,
                lexical_claims,
                body.usage_context,
                llm_requested=body.method == "LLM",
                allow_historical=allow_historical,
            )
            known_ids = {str(claim["claim_id"]) for claim in candidates}
            lexical_new = [
                claim for claim in lexical_claims if str(claim["claim_id"]) not in known_ids
            ]
            candidates.extend(lexical_new)
            lexical_recalled_ids = {str(claim["claim_id"]) for claim in lexical_new}
            retrieval_trace["lexical_recalled"] = len(lexical_new)
            _merge_excluded_counts(excluded, lexical_excluded)
            if diagnostics_enabled:
                diagnostic_stages["lexical"] = {
                    "fetched": _diagnostic_ids(raw_lexical_claims, diagnostics_limit),
                    "authorized": _diagnostic_ids(lexical_claims, diagnostics_limit),
                    "added": _diagnostic_ids(lexical_new, diagnostics_limit),
                    "already_present": len(lexical_claims) - len(lexical_new),
                    "excluded": lexical_excluded,
                }
        except Exception as exc:
            logger.warning("memory lexical recall failed: %s", exc)
            retrieval_trace["errors"].append(
                f"lexical_recall_failed:{type(exc).__name__}:{str(exc)[:160]}"
            )

    enhanced_composition = profile_id is not None or body.current_context is not None
    dropped_current_duplicate_claim_ids: list[str] = []
    conflicting_claim_ids: list[str] = []
    dropped_redundant_claim_ids: list[str] = []
    if enhanced_composition:
        increments: list[dict[str, Any]] = []
        for claim in candidates:
            relation = _relation_to_current(claim, body)
            if relation == "duplicate":
                dropped_current_duplicate_claim_ids.append(str(claim["claim_id"]))
            elif relation == "conflict":
                conflicting_claim_ids.append(str(claim["claim_id"]))
            else:
                increments.append(claim)
        candidates = increments

        deduplicated: list[dict[str, Any]] = []
        signatures: set[tuple[str, str, str]] = set()
        for claim in candidates:
            signature = (
                str(claim.get("dimension") or ""),
                str(claim.get("claim_type") or ""),
                _normalized(claim.get("value")),
            )
            if signature in signatures:
                dropped_redundant_claim_ids.append(str(claim["claim_id"]))
                continue
            signatures.add(signature)
            deduplicated.append(claim)
        candidates = deduplicated
    if diagnostics_enabled and enhanced_composition:
        diagnostic_stages["composition"] = {
            "retained": _diagnostic_ids(candidates, diagnostics_limit),
            "current_duplicates": dropped_current_duplicate_claim_ids[:diagnostics_limit],
            "conflicts": conflicting_claim_ids[:diagnostics_limit],
            "redundant": dropped_redundant_claim_ids[:diagnostics_limit],
        }

    retrieval_queries = [body.query]
    if getattr(settings, "memory_retrieve_multifacet_enabled", True):
        retrieval_queries = _retrieval_query_facets(
            body.query,
            max_queries=getattr(settings, "memory_retrieve_multifacet_max_queries", 3),
        ) or [body.query]
    retrieval_trace["query_facet_count"] = len(retrieval_queries)
    vector_scores: dict[str, float] = {}
    vector_query_facets: dict[str, set[int]] = {}
    if body.method in {"SEMANTIC", "HYBRID", "LLM"} and body.query.strip():
        try:
            combined_hits: dict[str, dict[str, Any]] = {}
            facet_hit_counts: list[int] = []
            for facet_index, retrieval_query in enumerate(retrieval_queries):
                facet_limit = (
                    body.candidate_limit
                    if facet_index == 0
                    else min(
                        body.candidate_limit,
                        getattr(settings, "memory_retrieve_multifacet_candidate_limit", 30),
                    )
                )
                try:
                    hits = await qdrant_store.search_claim_vectors(
                        ctx.tenant_id,
                        ctx.org_id,
                        body.user_id,
                        namespace,
                        retrieval_query,
                        dimensions=body.required_dimensions or None,
                        limit=facet_limit,
                    )
                except Exception as exc:
                    logger.warning(
                        "memory query facet vector recall failed facet=%s: %s",
                        facet_index,
                        exc,
                    )
                    retrieval_trace["errors"].append(
                        f"query_facet_vector_recall_failed:{facet_index}:"
                        f"{type(exc).__name__}:{str(exc)[:120]}"
                    )
                    facet_hit_counts.append(0)
                    continue
                facet_ids: set[str] = set()
                for hit in hits:
                    if not hit.get("claim_id"):
                        continue
                    claim_id = str(hit["claim_id"])
                    score = float(hit["score"])
                    facet_ids.add(claim_id)
                    vector_query_facets.setdefault(claim_id, set()).add(facet_index)
                    if score > vector_scores.get(claim_id, -1.0):
                        vector_scores[claim_id] = score
                        combined_hits[claim_id] = hit
                facet_hit_counts.append(len(facet_ids))
            retrieval_trace["query_facet_hits"] = facet_hit_counts
            retrieval_trace["vector_hits"] = len(vector_scores)
            if diagnostics_enabled:
                diagnostic_stages["vector"] = {
                    "hits": _diagnostic_ids(list(combined_hits.values()), diagnostics_limit),
                    "facet_count": len(retrieval_queries),
                    "facet_hit_counts": facet_hit_counts,
                }
            # Qdrant searches the entire authorized namespace.  The initial
            # Mongo query above is bounded (and ordered by recency), so a
            # highly relevant older vector hit may otherwise have no claim
            # document available to rank. Hydrate those hits by id, retaining
            # the same user/namespace/status filters, then policy-filter them
            # before merging with the ordinary candidate window.
            known_ids = {str(claim["claim_id"]) for claim in candidates}
            missing_ids = [claim_id for claim_id in vector_scores if claim_id not in known_ids]
            if missing_ids:
                recalled = await memory_claim_store.list_current_claims_by_ids(
                    ctx.tenant_id,
                    ctx.org_id,
                    body.user_id,
                    namespace,
                    missing_ids,
                    dimensions=body.required_dimensions or None,
                    include_history=allow_historical,
                )
                raw_recalled = recalled
                recalled, recalled_excluded = memory_policy.filter_claims(
                    ctx,
                    recalled,
                    body.usage_context,
                    llm_requested=body.method == "LLM",
                    allow_historical=allow_historical,
                )
                known_ids = {str(claim["claim_id"]) for claim in candidates}
                vector_new = [
                    claim for claim in recalled if str(claim["claim_id"]) not in known_ids
                ]
                candidates.extend(vector_new)
                retrieval_trace["vector_hydrated"] = len(vector_new)
                _merge_excluded_counts(excluded, recalled_excluded)
                if diagnostics_enabled:
                    diagnostic_stages["vector"].update(
                        {
                            "requested_missing": len(missing_ids),
                            "hydrated": _diagnostic_ids(raw_recalled, diagnostics_limit),
                            "authorized": _diagnostic_ids(recalled, diagnostics_limit),
                            "added": _diagnostic_ids(vector_new, diagnostics_limit),
                            "excluded": recalled_excluded,
                        }
                    )
        except Exception as exc:
            logger.warning("memory vector recall failed: %s", exc)
            retrieval_trace["errors"].append(
                f"vector_recall_failed:{type(exc).__name__}:{str(exc)[:160]}"
            )
            vector_scores = {}

    # A claim can contain the key entity while a sibling claim from the same
    # source event contains the date, qualifier, or another aggregation
    # operand.  Seed this expansion from a provisional hybrid score rather
    # than from recency, then run the ordinary policy filter and final ranking
    # over every recalled item.
    if candidates and getattr(settings, "memory_retrieve_evidence_neighbor_enabled", False):
        try:
            provisional_vector_weight = getattr(settings, "memory_retrieve_vector_weight", 0.75)
            provisional = sorted(
                candidates,
                key=lambda claim: (
                    provisional_vector_weight
                    * max(0.0, min(1.0, vector_scores.get(str(claim["claim_id"]), 0.0)))
                    + (1.0 - provisional_vector_weight) * _lexical_score(body.query, claim)
                ),
                reverse=True,
            )
            seed_limit = getattr(settings, "memory_retrieve_evidence_neighbor_seed_limit", 4)
            neighbor_claims = await memory_claim_store.list_current_claim_evidence_neighbors(
                ctx.tenant_id,
                ctx.org_id,
                body.user_id,
                namespace,
                provisional[:seed_limit],
                dimensions=body.required_dimensions or None,
                limit=getattr(settings, "memory_retrieve_evidence_neighbor_limit", 16),
                include_history=allow_historical,
            )
            raw_neighbor_claims = neighbor_claims
            neighbor_claims, neighbor_excluded = memory_policy.filter_claims(
                ctx,
                neighbor_claims,
                body.usage_context,
                llm_requested=body.method == "LLM",
                allow_historical=allow_historical,
            )
            known_ids = {str(claim["claim_id"]) for claim in candidates}
            neighbors_new = [
                claim for claim in neighbor_claims if str(claim["claim_id"]) not in known_ids
            ]
            candidates.extend(neighbors_new)
            retrieval_trace["evidence_neighbors_recalled"] = len(neighbors_new)
            _merge_excluded_counts(excluded, neighbor_excluded)
            if diagnostics_enabled:
                diagnostic_stages["neighbors"] = {
                    "seeds": _diagnostic_ids(provisional[:seed_limit], diagnostics_limit),
                    "fetched": _diagnostic_ids(raw_neighbor_claims, diagnostics_limit),
                    "authorized": _diagnostic_ids(neighbor_claims, diagnostics_limit),
                    "added": _diagnostic_ids(neighbors_new, diagnostics_limit),
                    "already_present": len(neighbor_claims) - len(neighbors_new),
                    "excluded": neighbor_excluded,
                }
        except Exception as exc:
            # Neighbor evidence is an enhancement, never a dependency for
            # baseline retrieval availability.
            logger.warning("memory evidence neighbor recall failed: %s", exc)
            retrieval_trace["errors"].append(
                f"evidence_neighbor_recall_failed:{type(exc).__name__}:{str(exc)[:160]}"
            )

    cutoff = _as_of_cutoff(body.query) if allow_historical else None
    if cutoff is not None:
        snapshot_candidates: list[dict[str, Any]] = []
        for claim in candidates:
            exclusion = _claim_as_of_exclusion(claim, cutoff)
            if exclusion:
                retrieval_trace[f"as_of_{exclusion}_excluded"] += 1
            else:
                snapshot_candidates.append(claim)
        candidates = snapshot_candidates
        if diagnostics_enabled:
            diagnostic_stages["as_of_snapshot"] = _diagnostic_ids(candidates, diagnostics_limit)

    for claim in candidates:
        claim["_query_facets"] = vector_query_facets.get(str(claim["claim_id"]), set())
        claim_text = str(claim.get("text") or claim.get("value") or "")
        lexical = _lexical_score(body.query, claim)
        term_coverage = _query_term_coverage(body.query, claim_text)
        monetary_coverage = _monetary_evidence_coverage(body.query, claim_text)
        aggregation_coverage = _aggregation_evidence_coverage(body.query, claim_text)
        vector = vector_scores.get(str(claim["claim_id"]))
        if vector is not None:
            # Hybrid ranking: vector similarity handles paraphrases while a
            # lexical component preserves exact names, numbers, and entities.
            # EXACT mode remains unchanged because vector_scores is empty.
            vector = max(0.0, min(1.0, float(vector)))
            vector_weight = get_settings().memory_retrieve_vector_weight
            claim["_score"] = vector_weight * vector + (1.0 - vector_weight) * lexical
        else:
            claim["_score"] = lexical
        # Give explicit coverage a small, bounded advantage over vector-only
        # similarity. This keeps exact operands visible without discarding
        # paraphrased semantic matches.
        claim["_score"] = min(1.0, float(claim["_score"]) + 0.15 * term_coverage)
        if monetary_coverage:
            claim["_score"] = min(
                1.0,
                float(claim["_score"])
                + getattr(settings, "memory_retrieve_monetary_evidence_boost", 0.18)
                * monetary_coverage,
            )
            retrieval_trace["monetary_evidence_boosted"] += 1
        if aggregation_coverage:
            claim["_score"] = min(
                1.0,
                float(claim["_score"])
                + getattr(settings, "memory_retrieve_aggregation_evidence_boost", 0.12)
                * aggregation_coverage,
            )
            retrieval_trace["aggregation_evidence_boosted"] += 1
        if allow_historical and _claim_matches_query_date(body.query, claim):
            # A date-scoped query should prefer the claim from that snapshot,
            # even when a newer superseding claim has a stronger embedding.
            claim["_score"] = min(1.0, float(claim["_score"]) + 0.20)
            retrieval_trace["temporal_evidence_boosted"] += 1
        action_coverage = _action_phrase_coverage(
            str(claim.get("text") or claim.get("value") or ""), action_phrases
        )
        if action_coverage:
            claim["_score"] = min(
                1.0,
                float(claim["_score"])
                + getattr(settings, "memory_retrieve_action_recall_boost", 0.12) * action_coverage,
            )
        if str(claim["claim_id"]) in lexical_recalled_ids:
            claim["_score"] = min(
                1.0,
                float(claim["_score"])
                + getattr(settings, "memory_retrieve_lexical_recall_boost", 0.08),
            )
        speaker_role = _evidence_speaker_role(claim)
        if speaker_role == "user":
            claim["_score"] = min(
                1.0,
                float(claim["_score"])
                + getattr(settings, "memory_retrieve_user_evidence_boost", 0.06),
            )
            retrieval_trace["user_evidence_boosted"] += 1
        elif speaker_role == "assistant":
            claim["_score"] = max(
                0.0,
                float(claim["_score"])
                - getattr(settings, "memory_retrieve_assistant_evidence_penalty", 0.12),
            )
            retrieval_trace["assistant_evidence_penalized"] += 1
        claim["_usage"] = None
        claim["_reason"] = "vector recall" if vector is not None else "lexical fallback"
    candidates.sort(key=lambda c: (float(c["_score"]), int(c.get("importance", 3))), reverse=True)
    if diagnostics_enabled:
        diagnostic_stages["ranked_before_rerank"] = _diagnostic_ranked(
            candidates, diagnostics_limit
        )

    auto_aggregation_rerank = _needs_aggregation_rerank(body.query) and getattr(
        settings, "memory_retrieve_aggregation_rerank_enabled", True
    )
    if (body.method == "LLM" or auto_aggregation_rerank) and candidates:
        rerank_candidates = candidates
        if auto_aggregation_rerank and body.method != "LLM":
            rerank_limit = getattr(settings, "memory_retrieve_aggregation_rerank_limit", 40)
            rerank_candidates = _aggregation_rerank_shortlist(candidates, rerank_limit)
        try:
            reranked = await _rerank_with_llm(session, ctx, body, candidates)
        except Exception:
            reranked = None
        if reranked is not None:
            candidates = [c for c in candidates if c["claim_id"] in reranked]
            for claim in candidates:
                decision = reranked[claim["claim_id"]]
                claim["_score"] = decision["score"]
                claim["_usage"] = decision["usage"]
                claim["_reason"] = decision["reason"]
            candidates.sort(key=lambda c: float(c["_score"]), reverse=True)
        if diagnostics_enabled:
            diagnostic_stages["rerank"] = {
                "attempted": True,
                "succeeded": reranked is not None,
                "shortlist": _diagnostic_ids(rerank_candidates, diagnostics_limit),
                "retained": _diagnostic_ranked(candidates, diagnostics_limit),
            }

    if getattr(settings, "memory_retrieve_session_diversity_enabled", True):
        candidates, deferred_count = _diversify_by_evidence_group(
            candidates,
            max_per_group=getattr(settings, "memory_retrieve_session_max_items", 2),
        )
        retrieval_trace["evidence_groups_deferred"] = deferred_count
    candidates, facet_promoted = _prioritize_query_facet_coverage(
        candidates, facet_count=len(retrieval_queries)
    )
    retrieval_trace["query_facet_candidates_promoted"] = facet_promoted
    if diagnostics_enabled:
        diagnostic_stages["ranked_after_diversity"] = _diagnostic_ranked(
            candidates, diagnostics_limit
        )

    selected: list[MemoryBundleItem] = []
    token_count = 0
    below_score = 0
    token_budget = 0
    max_items_rejected = 0
    token_limit_rejected = 0
    rejected_below_score: list[dict[str, Any]] = []
    rejected_max_items: list[dict[str, Any]] = []
    rejected_token_limit: list[dict[str, Any]] = []
    try:
        configured_max_items = int(profile.get("max_increment_items", body.top_k))
    except (TypeError, ValueError) as exc:
        raise ValidationError(
            f"invalid max_increment_items in retrieve_rule '{profile_id}'"
        ) from exc
    max_increment_items = max(1, min(body.top_k, configured_max_items))
    aggregation_selection_expanded = False
    aggregation_query = _needs_aggregation_rerank(body.query)
    aggregation_max_claim_chars = int(
        getattr(settings, "memory_retrieve_aggregation_max_claim_chars", 1200)
    )
    if aggregation_query:
        aggregation_max_items = int(getattr(settings, "memory_retrieve_aggregation_max_items", 12))
        expanded_limit = max(1, min(body.top_k, aggregation_max_items))
        if expanded_limit > max_increment_items:
            max_increment_items = expanded_limit
            aggregation_selection_expanded = True
    elif len(retrieval_queries) > 1:
        multifacet_max_items = int(getattr(settings, "memory_retrieve_multifacet_max_items", 12))
        max_increment_items = max(
            max_increment_items,
            max(1, min(body.top_k, multifacet_max_items)),
        )
    usage_mode = str(profile.get("usage_mode") or "authorized_background_only")
    for claim in candidates:
        score = float(claim["_score"])
        claim_min_score = float((claim.get("retrieval_policy") or {}).get("min_score", 0.0))
        if score < max(body.min_score, claim_min_score):
            below_score += 1
            if diagnostics_enabled:
                rejected_below_score.append(claim)
            continue
        claim_text = str(claim.get("text") or "")
        if aggregation_query:
            claim_text = _compact_aggregation_text(
                claim_text, body.query, aggregation_max_claim_chars
            )
        claim_tokens = _estimate_tokens(claim_text)
        if len(selected) >= max_increment_items:
            token_budget += 1
            max_items_rejected += 1
            if diagnostics_enabled:
                rejected_max_items.append(claim)
            continue
        if token_count + claim_tokens > body.max_tokens:
            token_budget += 1
            token_limit_rejected += 1
            if diagnostics_enabled:
                rejected_token_limit.append(claim)
            continue
        selected.append(
            MemoryBundleItem(
                claim_id=claim["claim_id"],
                dimension=claim["dimension"],
                claim_type=claim["claim_type"],
                text=claim_text,
                value=claim.get("value"),
                fact_status=claim["fact_status"],
                score=score,
                usage=claim.get("_usage"),
                reason=claim.get("_reason"),
                provenance=[
                    MemoryProvenance.model_validate(p) for p in claim.get("provenance", [])
                ],
                relation_to_current="increment",
                usage_mode=usage_mode,
                allowed_action="append_background",
            )
        )
        token_count += claim_tokens
    excluded["below_score"] = below_score
    excluded["token_budget"] = token_budget
    retrieval_trace["ranked_candidates"] = len(candidates)
    retrieval_trace["selected"] = len(selected)
    retrieval_trace["max_items_rejected"] = max_items_rejected
    retrieval_trace["token_limit_rejected"] = token_limit_rejected
    retrieval_trace["aggregation_selection_expanded"] = aggregation_selection_expanded
    bundle_id = f"mb_{uuid4().hex}"
    # Keep retrieval diagnostics in the service log as well as the API bundle.
    # This is intentionally counter-only: do not log query text or claim text.
    logger.info(
        "memory retrieval trace tenant=%s org=%s user=%s method=%s "
        "vector_hits=%s vector_hydrated=%s lexical_recalled=%s "
        "action_recalled=%s evidence_neighbors_recalled=%s aggregation_boosted=%s "
        "user_boosted=%s assistant_penalized=%s ranked_candidates=%s selected=%s errors=%s",
        ctx.tenant_id,
        ctx.org_id,
        body.user_id,
        body.method,
        retrieval_trace["vector_hits"],
        retrieval_trace["vector_hydrated"],
        retrieval_trace["lexical_recalled"],
        retrieval_trace["action_recalled"],
        retrieval_trace["evidence_neighbors_recalled"],
        retrieval_trace["aggregation_evidence_boosted"],
        retrieval_trace["user_evidence_boosted"],
        retrieval_trace["assistant_evidence_penalized"],
        retrieval_trace["ranked_candidates"],
        retrieval_trace["selected"],
        len(retrieval_trace["errors"]),
    )
    if diagnostics_enabled:
        selected_ids = {item.claim_id for item in selected}
        logger.info(
            "memory retrieval diagnostics %s",
            json.dumps(
                {
                    "bundle_id": bundle_id,
                    "tenant_id": ctx.tenant_id,
                    "org_id": ctx.org_id,
                    "user_id": body.user_id,
                    "method": body.method,
                    "candidate_limit": body.candidate_limit,
                    "top_k": body.top_k,
                    "max_tokens": body.max_tokens,
                    "used_tokens": token_count,
                    "stages": diagnostic_stages,
                    "selection": {
                        "selected": _diagnostic_ranked(
                            [c for c in candidates if c["claim_id"] in selected_ids],
                            diagnostics_limit,
                        ),
                        "below_score": _diagnostic_ranked(rejected_below_score, diagnostics_limit),
                        "max_items": _diagnostic_ranked(rejected_max_items, diagnostics_limit),
                        "token_limit": _diagnostic_ranked(rejected_token_limit, diagnostics_limit),
                    },
                    "policy_excluded": excluded,
                    "error_count": len(retrieval_trace["errors"]),
                },
                ensure_ascii=False,
                separators=(",", ":"),
            ),
        )

    settings = get_settings()
    created_at = datetime.now(timezone.utc)
    expires_at = created_at + timedelta(seconds=settings.memory_v2_bundle_ttl_seconds)
    policy_version = (
        f"retrieve_rule.v{profile_version}" if profile_version is not None else "request.v1"
    )
    await memory_claim_store.save_bundle(
        {
            "bundle_id": bundle_id,
            "tenant_id": ctx.tenant_id,
            "org_id": ctx.org_id,
            "user_id": body.user_id,
            "namespace": namespace,
            "usage_context": body.usage_context.model_dump(),
            "method": body.method,
            "query": body.query,
            "claim_ids": [item.claim_id for item in selected],
            "items": [item.model_dump() for item in selected],
            "excluded": excluded,
            "token_count": token_count,
            "profile_id": profile_id,
            "profile_version": profile_version,
            "dropped_current_duplicate_claim_ids": dropped_current_duplicate_claim_ids,
            "dropped_redundant_claim_ids": dropped_redundant_claim_ids,
            "conflicting_claim_ids": conflicting_claim_ids,
            "created_at": created_at,
            "policy_version": policy_version,
            "claim_schema_version": "memory-claim-v2",
            "expires_at": expires_at,
        }
    )
    return MemoryBundleOut(
        bundle_id=bundle_id,
        items=selected,
        excluded=excluded,
        token_count=token_count,
        method=body.method,
        profile_id=profile_id,
        profile_version=profile_version,
        selected_claim_ids=[item.claim_id for item in selected],
        dropped_current_duplicate_claim_ids=dropped_current_duplicate_claim_ids,
        dropped_redundant_claim_ids=dropped_redundant_claim_ids,
        conflicting_claim_ids=conflicting_claim_ids,
        effective_injection_count=len(selected),
        policy_version=policy_version,
        claim_schema_version="memory-claim-v2",
        expires_at=expires_at.isoformat(),
        retrieval_trace=retrieval_trace,
        no_hit_reason=(
            None
            if selected
            else _no_hit_reason(
                excluded, dropped_current_duplicate_claim_ids, conflicting_claim_ids
            )
        ),
    )


async def call(
    session: AsyncSession,
    ctx: RequestContext,
    body: MemoryCallV2Request,
) -> MemoryCallV2Response:
    bundle = await memory_claim_store.get_bundle(ctx.tenant_id, ctx.org_id, body.bundle_id)
    if not bundle:
        raise NotFoundError("memory bundle not found or expired")
    expires_at = bundle.get("expires_at")
    if isinstance(expires_at, datetime) and _as_utc(expires_at) <= datetime.now(timezone.utc):
        raise NotFoundError("memory bundle not found or expired")
    usage = bundle.get("usage_context") or {}
    if usage.get("module_id") != body.module_id:
        raise ForbiddenError("memory bundle cannot be reused by another module")
    usage_context = MemoryUsageContext.model_validate(usage)
    memory_policy.ensure_retrieve_permission(ctx, usage_context)

    # Revalidate status and data-level policy at consumption time. A bundle is an
    # audit snapshot, not a capability token that survives revoke/policy changes.
    namespace = usage_context.namespace.model_dump(exclude_none=True)
    current = await memory_claim_store.list_current_claims(
        ctx.tenant_id,
        ctx.org_id,
        str(bundle["user_id"]),
        namespace,
        limit=max(200, len(bundle.get("claim_ids") or [])),
    )
    authorized, _ = memory_policy.filter_claims(
        ctx, current, usage_context, llm_requested=body.use_llm
    )
    authorized_ids = {item["claim_id"] for item in authorized}
    bundle_ids = set(bundle.get("claim_ids") or [])
    if not bundle_ids.issubset(authorized_ids):
        raise ForbiddenError("memory bundle authorization changed; retrieve again")
    context = json.dumps(bundle.get("items") or [], ensure_ascii=False, default=str)
    filled = body.prompt_template.replace(body.slot, context)
    result = filled
    if body.use_llm:
        llm = body.llm
        result, pt, ct = await llm_client.chat_completion(
            filled,
            system="Use only the authorized memory context. Do not invent missing facts.",
            base_url=llm.base_url if llm else None,
            api_key=llm.api_key if llm else None,
            model=llm.model_name if llm else None,
        )
        await billing_service.emit_llm_completion(
            session,
            ctx,
            model_name=(llm.model_name if llm and llm.model_name else get_settings().openai_model),
            prompt_tokens=pt,
            completion_tokens=ct,
        )
    return MemoryCallV2Response(result=result, filled_prompt=filled, bundle_id=body.bundle_id)
