#!/usr/bin/env python3
"""Build a normalized AML shadow suite from public benchmark datasets.

Dataset files remain external and retain their upstream licenses. The generated
manifest contains only the selected benchmark content and must not be committed.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any


def _timestamp_ms(value: str, formats: tuple[str, ...]) -> int | None:
    for pattern in formats:
        try:
            parsed = datetime.strptime(value, pattern).replace(tzinfo=timezone.utc)
            return int(parsed.timestamp() * 1000)
        except ValueError:
            continue
    return None


def _clean_message(role: object, content: object, timestamp: int | None) -> dict[str, Any] | None:
    text = str(content or "").replace("<|endoftext|>", "").strip()
    normalized_role = str(role or "").lower()
    if not text or normalized_role not in {"user", "assistant"}:
        return None
    message: dict[str, Any] = {"role": normalized_role, "content": text}
    if timestamp is not None:
        message["timestamp"] = timestamp
    return message


def build_locomo(dataset: Path, *, sample_limit: int = 0) -> list[dict[str, Any]]:
    samples = json.loads(dataset.read_text(encoding="utf-8"))
    if isinstance(samples, dict):
        samples = samples.get("samples") or samples.get("data") or []
    if sample_limit:
        samples = samples[:sample_limit]
    cases = []
    for sample_index, sample in enumerate(samples):
        sample_id = str(sample.get("sample_id") or sample_index)
        conversation = sample["conversation"]
        speaker_a = str(conversation.get("speaker_a") or "")
        sessions = []
        evidence_text: dict[str, str] = {}
        session_names = sorted(
            (
                key
                for key, value in conversation.items()
                if key.startswith("session_")
                and not key.endswith("_date_time")
                and isinstance(value, list)
            ),
            key=lambda key: int(key.split("_")[1]),
        )
        for session_name in session_names:
            date = str(conversation.get(f"{session_name}_date_time") or "")
            timestamp = _timestamp_ms(date, ("%I:%M %p on %d %B, %Y",))
            messages = []
            for turn in conversation[session_name]:
                text = str(turn.get("text") or turn.get("blip_caption") or "").strip()
                evidence_id = str(turn.get("dia_id") or "")
                role = "user" if str(turn.get("speaker") or "") == speaker_a else "assistant"
                message = _clean_message(role, text, timestamp)
                if message is None:
                    continue
                messages.append(message)
                if evidence_id:
                    evidence_text[evidence_id] = text
            if messages:
                sessions.append({"session_id": f"{sample_id}:{session_name}", "messages": messages})

        queries = []
        for question_index, question in enumerate(sample.get("qa") or []):
            category = str(question.get("category") or "unknown")
            evidence_ids = [
                part.strip()
                for value in question.get("evidence") or []
                for part in str(value).split(";")
                if part.strip()
            ]
            if category == "5" or not evidence_ids:
                continue
            queries.append(
                {
                    "query_id": f"{sample_id}:q{question_index}",
                    "query": str(question["question"]),
                    "gold_answer": question.get("answer"),
                    "gold_evidence_texts": [
                        evidence_text[value] for value in evidence_ids if value in evidence_text
                    ],
                    "capability": {
                        "1": "relational_multi_hop",
                        "2": "temporal_event",
                        "3": "open_domain",
                        "4": "explicit_fact",
                    }.get(category, "unknown"),
                    "source_category": category,
                }
            )
        cases.append(
            {
                "case_id": sample_id,
                "source": "locomo",
                "sessions": sessions,
                "queries": queries,
            }
        )
    return cases


def build_longmemeval(dataset: Path, *, sample_limit: int = 0) -> list[dict[str, Any]]:
    rows = json.loads(dataset.read_text(encoding="utf-8"))
    if isinstance(rows, dict):
        rows = rows.get("data") or rows.get("samples") or []
    if sample_limit:
        rows = rows[:sample_limit]
    cases = []
    for row_index, row in enumerate(rows):
        question_id = str(row.get("question_id") or row_index)
        session_ids = [str(value) for value in row.get("haystack_session_ids") or []]
        answer_session_ids = {str(value) for value in row.get("answer_session_ids") or []}
        sessions = []
        gold_evidence_texts = []
        for session_index, raw_session in enumerate(row.get("haystack_sessions") or []):
            session_id = (
                session_ids[session_index]
                if session_index < len(session_ids)
                else f"session-{session_index}"
            )
            dates = row.get("haystack_dates") or []
            date = str(dates[session_index]) if session_index < len(dates) else ""
            timestamp = _timestamp_ms(
                date,
                (
                    "%Y/%m/%d (%a) %H:%M",
                    "%Y/%m/%d %H:%M",
                    "%Y-%m-%d %H:%M:%S",
                    "%Y-%m-%d",
                ),
            )
            messages = []
            for raw_message in raw_session:
                message = _clean_message(
                    raw_message.get("role"), raw_message.get("content"), timestamp
                )
                if message is None:
                    continue
                messages.append(message)
                if session_id in answer_session_ids:
                    gold_evidence_texts.append(message["content"])
            if messages:
                sessions.append({"session_id": session_id, "messages": messages})
        cases.append(
            {
                "case_id": question_id,
                "source": "longmemeval-s",
                "sessions": sessions,
                "queries": [
                    {
                        "query_id": question_id,
                        "query": str(row.get("question") or ""),
                        "gold_answer": row.get("answer"),
                        "gold_evidence_texts": gold_evidence_texts,
                        "capability": str(row.get("question_type") or "unknown"),
                        "question_date": row.get("question_date"),
                        "evidence_granularity": "session",
                    }
                ],
            }
        )
    return cases


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", choices=("locomo", "longmemeval-s"))
    parser.add_argument("dataset", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--sample-limit", type=int, default=0)
    args = parser.parse_args()

    if args.source == "locomo":
        cases = build_locomo(args.dataset, sample_limit=args.sample_limit)
    else:
        cases = build_longmemeval(args.dataset, sample_limit=args.sample_limit)
    manifest = {
        "schema_version": "aml-shadow-v1",
        "source": args.source,
        "cases": cases,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    query_count = sum(len(case["queries"]) for case in cases)
    session_count = sum(len(case["sessions"]) for case in cases)
    print(
        f"wrote cases={len(cases)} sessions={session_count} queries={query_count} to {args.output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
