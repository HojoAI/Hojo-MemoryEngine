"""Deterministic P0 memory permission and usage-context filtering."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from memory_engine.config import get_settings
from memory_engine.core.context import RequestContext
from memory_engine.core.exceptions import ForbiddenError
from memory_engine.core.permissions import permission_granted
from memory_engine.schemas.memory_claim import MemoryUsageContext


def _matches(values: list[str] | None, value: str) -> bool:
    allowed = values or []
    return "*" in allowed or value in allowed


def ensure_retrieve_permission(ctx: RequestContext, usage: MemoryUsageContext) -> None:
    if get_settings().app_disable_auth:
        return
    required = "memory:retrieve:self" if usage.scope == "self" else "memory:retrieve:cross"
    if not permission_granted(ctx.permissions, required):
        raise ForbiddenError(f"Missing permission: {required}")


def filter_claims(
    ctx: RequestContext,
    claims: list[dict[str, Any]],
    usage: MemoryUsageContext,
    *,
    llm_requested: bool,
    allow_historical: bool = False,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Apply hard policy checks before candidates are sent to embeddings or LLMs."""
    excluded = {
        "different_namespace": 0,
        "permission_denied": 0,
        "scope_mismatch": 0,
        "expired": 0,
        "conflicted_or_inactive": 0,
    }
    allowed: list[dict[str, Any]] = []
    target_ns = usage.namespace.model_dump(exclude_none=True)
    now = datetime.now(timezone.utc)
    for claim in claims:
        namespace = claim.get("namespace") or {}
        if namespace.get("type") != target_ns["type"] or namespace.get("id") != target_ns["id"]:
            excluded["different_namespace"] += 1
            continue
        is_active_current = claim.get("lifecycle_status") == "active" and claim.get("is_current", False)
        is_historical = allow_historical and claim.get("lifecycle_status") in {
            "active", "superseded", "conflicted"
        }
        if not (is_active_current or is_historical):
            excluded["conflicted_or_inactive"] += 1
            continue
        expires_at = claim.get("expires_at")
        if expires_at:
            try:
                expiry = datetime.fromisoformat(str(expires_at).replace("Z", "+00:00"))
                if expiry.tzinfo is None:
                    expiry = expiry.replace(tzinfo=timezone.utc)
                if expiry <= now:
                    excluded["expired"] += 1
                    continue
            except ValueError:
                excluded["expired"] += 1
                continue
        policy = claim.get("access_policy") or {}
        if not _matches(policy.get("allowed_modules"), usage.module_id):
            excluded["permission_denied"] += 1
            continue
        if not _matches(policy.get("allowed_scenarios"), usage.scenario):
            excluded["permission_denied"] += 1
            continue
        if usage.scope not in (policy.get("allowed_scopes") or ["self"]):
            excluded["permission_denied"] += 1
            continue
        if not _matches(policy.get("allowed_roles"), usage.caller_role):
            excluded["permission_denied"] += 1
            continue
        if llm_requested and not policy.get("allow_llm", True):
            excluded["permission_denied"] += 1
            continue
        if policy.get("sensitivity") == "sensitive" and not (
            get_settings().app_disable_auth
            or permission_granted(ctx.permissions, "memory:retrieve:sensitive")
        ):
            excluded["permission_denied"] += 1
            continue

        meeting_ids = {
            p.get("meeting_id") for p in (claim.get("provenance") or []) if p.get("meeting_id")
        }
        if usage.scope == "self" and usage.current_meeting_id:
            if usage.current_meeting_id not in meeting_ids:
                excluded["scope_mismatch"] += 1
                continue
        elif usage.scope == "cross" and usage.current_meeting_id:
            if usage.current_meeting_id in meeting_ids:
                excluded["scope_mismatch"] += 1
                continue
        allowed.append(claim)
    return allowed, excluded
