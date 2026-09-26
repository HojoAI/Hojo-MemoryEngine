#!/usr/bin/env python3
"""Evaluate the AML lexical channel against public LoCoMo evidence annotations."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

from memory_engine.services.aml_adapter import _bm25_rank


def _conversation_units(sample: dict) -> list[dict]:
    conversation = sample["conversation"]
    units: list[dict] = []
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
        session_date = str(conversation.get(f"{session_name}_date_time") or "unknown time")
        for turn in conversation[session_name]:
            evidence_id = str(turn.get("dia_id") or "")
            text = str(turn.get("text") or turn.get("blip_caption") or "").strip()
            if not evidence_id or not text:
                continue
            speaker = str(turn.get("speaker") or "unknown")
            units.append(
                {
                    "unit_id": evidence_id,
                    "searchable_content": f"[{session_date}] {speaker}: {text}",
                }
            )
    return units


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--ks", default="1,5,10,20,50,100")
    parser.add_argument(
        "--include-adversarial",
        action="store_true",
        help="include category-5 questions, which normally have no supporting evidence",
    )
    args = parser.parse_args()
    ks = sorted({int(value) for value in args.ks.split(",") if value.strip()})
    samples = json.loads(args.dataset.read_text(encoding="utf-8"))
    if isinstance(samples, dict):
        samples = samples.get("samples") or samples.get("data") or []

    total = 0
    reciprocal_rank = 0.0
    any_hits = defaultdict(int)
    all_hits = defaultdict(int)
    by_category: dict[str, list[int]] = defaultdict(list)
    for sample in samples:
        units = _conversation_units(sample)
        for question in sample.get("qa") or []:
            category = str(question.get("category") or "unknown")
            evidence = {str(item) for item in (question.get("evidence") or []) if item}
            if not evidence or (category == "5" and not args.include_adversarial):
                continue
            ranking = [unit_id for unit_id, _score in _bm25_rank(question["question"], units)]
            ranks = [ranking.index(item) + 1 for item in evidence if item in ranking]
            total += 1
            by_category[category].append(min(ranks) if ranks else 0)
            if ranks:
                reciprocal_rank += 1 / min(ranks)
            for k in ks:
                retrieved = set(ranking[:k])
                if retrieved & evidence:
                    any_hits[k] += 1
                if evidence.issubset(retrieved):
                    all_hits[k] += 1

    print(f"questions={total} mrr={reciprocal_rank / max(1, total):.4f}")
    for k in ks:
        print(
            f"k={k:>3} any_evidence_recall={any_hits[k] / max(1, total):.4f} "
            f"all_evidence_recall={all_hits[k] / max(1, total):.4f}"
        )
    for category in sorted(by_category):
        ranks = by_category[category]
        hit_at_10 = sum(1 for rank in ranks if 0 < rank <= 10) / max(1, len(ranks))
        print(f"category={category} questions={len(ranks)} any_evidence_recall@10={hit_at_10:.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
