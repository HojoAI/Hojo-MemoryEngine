"""P1 atomic claim ingest and deterministic update engine."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from jsonschema import ValidationError as JsonSchemaValidationError
from jsonschema import validate as validate_json_schema
from sqlalchemy.ext.asyncio import AsyncSession

from memory_engine.config import get_settings
from memory_engine.core.context import RequestContext
from memory_engine.core.exceptions import NotFoundError, ValidationError
from memory_engine.integrations import memory_claim_store, qdrant_store
from memory_engine.schemas.memory_claim import (
    MemoryAccessPolicy,
    MemoryClaimInput,
    MemoryClaimResolveRequest,
    MemoryClaimRevokeRequest,
    MemoryIngestRequest,
    MemoryIngestResult,
    MemoryNamespace,
    MemoryProvenance,
    MemorySourceEventInput,
    MemoryUpdateDecision,
)
from memory_engine.services import memory_field as memory_field_service

logger = logging.getLogger(__name__)

_FACT_AUTHORITY = {
    "opinion": 1,
    "proposal": 2,
    "forecast": 2,
    "stated": 3,
    "commitment": 4,
    "decision": 5,
    "correction": 6,
}


def _provenance(event: MemorySourceEventInput, event_id: str) -> dict[str, Any]:
    return MemoryProvenance(
        source_type=event.source_type,
        source_id=event.source_id or event_id,
        meeting_id=event.meeting_id,
        segment_id=event.segment_id,
        speaker_id=event.speaker_id,
        speaker_role=event.speaker_role,
        evidence=event.raw_text[:8000] if event.raw_text else None,
        occurred_at=event.occurred_at,
    ).model_dump(exclude_none=True)


def _claim_doc(
    ctx: RequestContext,
    body: MemoryIngestRequest,
    claim: MemoryClaimInput,
    event_id: str,
    access_policy: MemoryAccessPolicy,
    update_policy: dict[str, Any],
    retrieval_policy: dict[str, Any],
    policy_schema_version: str,
) -> dict[str, Any]:
    namespace = body.namespace.model_dump(exclude_none=True)
    identity_id = memory_claim_store.claim_identity_id(
        ctx.tenant_id,
        ctx.org_id,
        body.user_id,
        namespace,
        claim.dimension,
        claim.claim_key,
    )
    return {
        "schema_version": "2.0",
        "tenant_id": ctx.tenant_id,
        "org_id": ctx.org_id,
        "user_id": body.user_id,
        "namespace": namespace,
        "identity_id": identity_id,
        "dimension": claim.dimension,
        "claim_type": claim.claim_type,
        "claim_key": claim.claim_key,
        "value": claim.value,
        "text": claim.text,
        "fact_status": claim.fact_status,
        "lifecycle_status": "active",
        "confidence": claim.confidence,
        "importance": claim.importance,
        "effective_at": claim.effective_at,
        "expires_at": claim.expires_at,
        "access_policy": access_policy.model_dump(),
        "update_policy": update_policy,
        "retrieval_policy": retrieval_policy,
        "policy_schema_version": policy_schema_version,
        "provenance": [_provenance(body.source_event, event_id)],
        "source_event_ids": [event_id],
    }


def _non_conflicting_object_update(old: Any, new: Any) -> dict[str, Any] | None:
    """Return merged object only when the new object merely fills missing keys."""
    if not isinstance(old, dict) or not isinstance(new, dict):
        return None
    overlap = set(old) & set(new)
    if any(not memory_claim_store.values_equal(old[k], new[k]) for k in overlap):
        return None
    if set(new).issubset(old):
        return old
    return {**old, **new}


def _parse_event_time(value: Any) -> datetime | None:
    """Only use comparable source timestamps, never ingestion wall-clock time."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


def _fact_time(claim: dict[str, Any]) -> datetime | None:
    effective = _parse_event_time(claim.get("effective_at"))
    if effective is not None:
        return effective
    observed = [
        stamp
        for provenance in claim.get("provenance") or []
        if (stamp := _parse_event_time(provenance.get("occurred_at"))) is not None
    ]
    return max(observed, default=None)


def _is_newer_same_authority_fact(
    incoming: dict[str, Any], current: dict[str, Any]
) -> bool:
    """A later user statement updates a mutable fact, absent stronger authority.

    Equal-authority contradictions without source chronology remain conflicts.
    An older replay must not roll the current value back.
    """
    if incoming.get("fact_status") != "stated" or current.get("fact_status") != "stated":
        return False
    incoming_time, current_time = _fact_time(incoming), _fact_time(current)
    return bool(
        incoming_time is not None
        and current_time is not None
        and incoming_time > current_time
        and float(incoming.get("confidence", 0.0)) >= float(current.get("confidence", 0.0))
    )


async def _index_claim_best_effort(claim: dict[str, Any]) -> None:
    try:
        await qdrant_store.upsert_claim_vector(claim)
    except Exception as exc:
        logger.warning("claim vector index skipped claim_id=%s: %s", claim.get("claim_id"), exc)


async def _delete_claim_index_best_effort(tenant_id: int, claim_id: str) -> None:
    try:
        await qdrant_store.mark_claim_deleted(tenant_id, claim_id)
    except Exception as exc:
        logger.warning("claim vector delete skipped claim_id=%s: %s", claim_id, exc)


async def _ingest_one(
    session: AsyncSession,
    ctx: RequestContext,
    body: MemoryIngestRequest,
    claim: MemoryClaimInput,
    event_id: str,
) -> MemoryUpdateDecision:
    settings = get_settings()
    field = await memory_field_service.get_active_by_name(session, ctx, claim.dimension)
    if field and field.json_schema:
        try:
            validate_json_schema(instance=claim.value, schema=field.json_schema)
        except JsonSchemaValidationError as exc:
            return MemoryUpdateDecision(
                action="REJECT",
                reason=f"JSON Schema validation failed: {exc.message}",
                lifecycle_status="pending",
            )
    update_policy = (getattr(field, "update_policy_json", None) or {}) if field else {}
    min_confidence = float(
        update_policy.get("min_confidence", settings.memory_claim_min_confidence)
    )
    if claim.confidence < min_confidence:
        return MemoryUpdateDecision(
            action="REJECT",
            reason=(
                f"confidence {claim.confidence:.2f} below threshold "
                f"{min_confidence:.2f}"
            ),
            lifecycle_status="pending",
        )

    if claim.access_policy is not None:
        access_policy = claim.access_policy
    elif field and getattr(field, "access_policy_json", None):
        access_policy = MemoryAccessPolicy.model_validate(field.access_policy_json)
    else:
        access_policy = MemoryAccessPolicy()
    retrieval_policy = (getattr(field, "retrieval_policy_json", None) or {}) if field else {}
    policy_schema_version = str(getattr(field, "schema_version", "1.0") or "1.0")
    doc = _claim_doc(
        ctx,
        body,
        claim,
        event_id,
        access_policy,
        update_policy,
        retrieval_policy,
        policy_schema_version,
    )
    current = await memory_claim_store.get_latest_claim(doc["identity_id"])
    if not current:
        stored = await memory_claim_store.insert_claim(doc, make_current=True)
        await _index_claim_best_effort(stored)
        return MemoryUpdateDecision(
            action="ADD",
            claim_id=stored["claim_id"],
            reason="no active claim with the same namespace and claim_key",
            lifecycle_status="active",
        )

    if memory_claim_store.values_equal(current.get("value"), claim.value):
        await memory_claim_store.confirm_claim(
            current["claim_id"], doc["provenance"][0], claim.confidence
        )
        return MemoryUpdateDecision(
            action="CONFIRM",
            claim_id=current["claim_id"],
            reason="new evidence confirms the current value",
            lifecycle_status=current.get("lifecycle_status", "active"),
        )

    merged = (
        _non_conflicting_object_update(current.get("value"), claim.value)
        if update_policy.get("allow_non_conflicting_object_fill", True)
        else None
    )
    if merged is not None:
        doc["value"] = merged
        doc["supersedes"] = current["claim_id"]
        stored = await memory_claim_store.insert_claim(doc, make_current=True)
        status_extra: dict[str, Any] = {"superseded_by": stored["claim_id"]}
        if (new_time := _fact_time(doc)) is not None:
            status_extra["superseded_at"] = new_time.isoformat()
        await memory_claim_store.mark_claim_status(
            current["claim_id"], "superseded", **status_extra
        )
        await _delete_claim_index_best_effort(ctx.tenant_id, current["claim_id"])
        await _index_claim_best_effort(stored)
        return MemoryUpdateDecision(
            action="UPDATE",
            claim_id=stored["claim_id"],
            previous_claim_id=current["claim_id"],
            reason="new evidence fills previously missing structured fields",
            lifecycle_status="active",
        )

    incoming_authority = _FACT_AUTHORITY.get(claim.fact_status, 0)
    current_authority = _FACT_AUTHORITY.get(str(current.get("fact_status")), 0)
    auto_supersede_statuses = set(
        update_policy.get("auto_supersede_fact_statuses", ["decision", "correction"])
    )
    newer_same_authority = update_policy.get("allow_chronological_supersede", True) and (
        _is_newer_same_authority_fact(doc, current)
    )
    if incoming_authority > current_authority or newer_same_authority or (
        claim.fact_status in auto_supersede_statuses
        and claim.confidence >= float(current.get("confidence", 0.0))
    ):
        doc["supersedes"] = current["claim_id"]
        stored = await memory_claim_store.insert_claim(doc, make_current=True)
        status_extra: dict[str, Any] = {"superseded_by": stored["claim_id"]}
        if (new_time := _fact_time(doc)) is not None:
            status_extra["superseded_at"] = new_time.isoformat()
        await memory_claim_store.mark_claim_status(
            current["claim_id"], "superseded", **status_extra
        )
        await _delete_claim_index_best_effort(ctx.tenant_id, current["claim_id"])
        await _index_claim_best_effort(stored)
        return MemoryUpdateDecision(
            action="SUPERSEDE",
            claim_id=stored["claim_id"],
            previous_claim_id=current["claim_id"],
            reason=(
                "newer source evidence updates the same-authority fact"
                if newer_same_authority else "new evidence has a higher fact authority"
            ),
            lifecycle_status="active",
        )

    doc["lifecycle_status"] = "conflicted"
    doc["conflicts_with"] = [current["claim_id"]]
    stored = await memory_claim_store.insert_claim(doc, make_current=False)
    return MemoryUpdateDecision(
        action="CONFLICT",
        claim_id=stored["claim_id"],
        previous_claim_id=current["claim_id"],
        reason="different value lacks enough authority to replace the active claim",
        lifecycle_status="conflicted",
    )


async def ingest(
    session: AsyncSession, ctx: RequestContext, body: MemoryIngestRequest
) -> MemoryIngestResult:
    event_id = await memory_claim_store.save_source_event(
        ctx.tenant_id,
        ctx.org_id,
        body.user_id,
        body.namespace.model_dump(exclude_none=True),
        body.source_event.model_dump(exclude_none=True),
    )
    decisions = [
        await _ingest_one(session, ctx, body, claim, event_id) for claim in body.claims
    ]
    return MemoryIngestResult(event_id=event_id, decisions=decisions)


async def ingest_legacy_projection(
    session: AsyncSession,
    ctx: RequestContext,
    *,
    user_id: str,
    memory_field_name: str,
    value: Any,
    source: str | None,
    original_expression: str | None,
    extra: dict[str, Any] | None,
) -> None:
    """Best-effort V1 dual write; failures must never break the legacy write path."""
    settings = get_settings()
    if not settings.memory_v1_dual_write_enabled:
        return
    metadata = extra or {}
    raw_namespace = metadata.get("namespace")
    namespace = (
        MemoryNamespace.model_validate(raw_namespace)
        if isinstance(raw_namespace, dict)
        else MemoryNamespace(type="user", id="default", label="Legacy default")
    )
    evidence = original_expression or metadata.get("evidence") or str(value)
    policy_raw = metadata.get("access_policy")
    policy = (
        MemoryAccessPolicy.model_validate(policy_raw)
        if isinstance(policy_raw, dict)
        else MemoryAccessPolicy(allowed_scopes=["self", "cross", "all"])
    )
    body = MemoryIngestRequest(
        user_id=user_id,
        namespace=namespace,
        source_event=MemorySourceEventInput(
            event_id=metadata.get("event_id"),
            source_type=source or "api",
            source_id=metadata.get("source_id"),
            meeting_id=metadata.get("meeting_id"),
            segment_id=metadata.get("segment_id"),
            speaker_id=metadata.get("speaker_id"),
            speaker_role=metadata.get("speaker_role"),
            raw_text=evidence,
            occurred_at=metadata.get("occurred_at"),
        ),
        claims=[
            MemoryClaimInput(
                dimension=memory_field_name,
                claim_type="legacy_projection",
                claim_key=memory_field_name,
                value=value,
                text=str(value),
                # Legacy V1 represents the latest materialized projection, so a
                # changed value must supersede its former projection deterministically.
                fact_status=metadata.get("fact_status", "correction"),
                confidence=float(metadata.get("confidence", 1.0)),
                importance=int(metadata.get("importance", 3)),
                access_policy=policy,
            )
        ],
    )
    await ingest(session, ctx, body)


async def history(ctx: RequestContext, claim_id: str) -> tuple[str, list[dict[str, Any]]]:
    result = await memory_claim_store.list_history(ctx.tenant_id, ctx.org_id, claim_id)
    if not result:
        raise NotFoundError("memory claim not found")
    return result


async def revoke(
    ctx: RequestContext, claim_id: str, body: MemoryClaimRevokeRequest
) -> None:
    claim = await memory_claim_store.get_claim(ctx.tenant_id, ctx.org_id, claim_id)
    if not claim:
        raise NotFoundError("memory claim not found")
    await memory_claim_store.mark_claim_status(
        claim_id,
        "revoked",
        is_current=False,
        revoke_reason=body.reason,
        revoked_by=ctx.user_id,
    )
    try:
        await qdrant_store.mark_claim_deleted(ctx.tenant_id, claim_id)
    except Exception as exc:
        logger.warning("claim vector revoke skipped claim_id=%s: %s", claim_id, exc)


async def resolve_conflict(
    ctx: RequestContext, claim_id: str, body: MemoryClaimResolveRequest
) -> None:
    """Resolve a conflicted claim through an explicit, auditable reviewer action."""
    claim = await memory_claim_store.get_claim(ctx.tenant_id, ctx.org_id, claim_id)
    if not claim:
        raise NotFoundError("memory claim not found")
    if claim.get("lifecycle_status") != "conflicted":
        raise ValidationError("only conflicted claims can be resolved")
    review = {
        "review_resolution": body.resolution,
        "review_reason": body.reason,
        "reviewed_by": ctx.user_id,
    }
    if body.resolution == "REJECT":
        await memory_claim_store.mark_claim_status(
            claim_id, "revoked", is_current=False, **review
        )
        return

    current = await memory_claim_store.get_latest_claim(claim["identity_id"])
    if current and current["claim_id"] != claim_id:
        await memory_claim_store.mark_claim_status(
            current["claim_id"], "superseded", is_current=False, superseded_by=claim_id
        )
    await memory_claim_store.mark_claim_status(
        claim_id, "active", is_current=True, **review
    )
    refreshed = await memory_claim_store.get_claim(ctx.tenant_id, ctx.org_id, claim_id)
    if refreshed:
        await _index_claim_best_effort(refreshed)
