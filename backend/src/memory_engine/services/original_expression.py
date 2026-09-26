"""Extract a short original-text span that relates to a parsed memory value."""

from __future__ import annotations

import re
from typing import Any

_MAX_EXPR_LEN = 120
_MIN_LCS_LEN = 4
_CLAUSE_SPLIT = re.compile(r"[。！？；;\n]+")


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        parts = [_as_text(item) for item in value]
        return "；".join(part for part in parts if part)
    if isinstance(value, dict):
        nested = value.get("value", value)
        if nested is not value:
            return _as_text(nested)
        return str(value).strip()
    return str(value).strip()


def _clip(text: str, max_len: int = _MAX_EXPR_LEN) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= max_len:
        return text
    return text[: max_len - 1].rstrip() + "…"


def _longest_common_substring(left: str, right: str) -> str:
    """Return the longest contiguous shared substring (character-level)."""
    if not left or not right:
        return ""
    # Prefer shorter haystack as DP rows for memory.
    if len(left) < len(right):
        left, right = right, left
    best = ""
    prev = [0] * (len(right) + 1)
    for i, ch_l in enumerate(left, start=1):
        cur = [0] * (len(right) + 1)
        for j, ch_r in enumerate(right, start=1):
            if ch_l == ch_r:
                cur[j] = prev[j - 1] + 1
                if cur[j] > len(best):
                    best = left[i - cur[j] : i]
        prev = cur
    return best


def _best_clause(query: str, value_text: str) -> str:
    clauses = [c.strip() for c in _CLAUSE_SPLIT.split(query) if c.strip()]
    if not clauses:
        return ""
    value_chars = set(value_text)
    if not value_chars:
        return ""
    best = ""
    best_score = 0.0
    for clause in clauses:
        if not clause:
            continue
        overlap = len(value_chars & set(clause))
        score = overlap / max(len(value_chars), 1)
        if value_text in clause:
            score += 1.0
        if score > best_score:
            best_score = score
            best = clause
    return best if best_score > 0 else ""


def extract_original_expression(
    query: str | None,
    value: Any,
    *,
    explicit: str | None = None,
    max_len: int = _MAX_EXPR_LEN,
) -> str | None:
    """Pick a short contiguous span from ``query`` related to ``value``.

    Preference order:
    1. Explicit caller-provided expression (clipped).
    2. Exact ``value`` substring inside ``query``.
    3. Longest common substring (>= 4 chars).
    4. Best-overlapping sentence/clause in ``query``.
    """
    if explicit is not None and explicit.strip():
        return _clip(explicit.strip(), max_len)

    query_text = (query or "").strip()
    value_text = _as_text(value)
    if not query_text or not value_text:
        return None

    # Exact / near-exact containment.
    if value_text in query_text:
        return _clip(value_text, max_len)

    # Try without surrounding punctuation / quotes on value.
    stripped_value = value_text.strip("\"'「」『』《》")
    if stripped_value and stripped_value in query_text:
        return _clip(stripped_value, max_len)

    lcs = _longest_common_substring(query_text, value_text)
    if len(lcs) >= _MIN_LCS_LEN:
        return _clip(lcs, max_len)

    clause = _best_clause(query_text, value_text)
    if clause:
        return _clip(clause, max_len)

    return None
