from __future__ import annotations

import json
from pathlib import Path
import sys


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from build_aml_shadow_suite import build_locomo, build_longmemeval  # noqa: E402
from eval_aml_shadow_remote import _chunk_messages, _matches  # noqa: E402
from generate_aml_capability_suite import build_suite  # noqa: E402


def test_locomo_builder_splits_evidence_ids_and_preserves_timestamps(tmp_path: Path) -> None:
    dataset = tmp_path / "locomo.json"
    dataset.write_text(
        json.dumps(
            [
                {
                    "sample_id": "conv-test",
                    "conversation": {
                        "speaker_a": "Alice",
                        "session_1_date_time": "10:15 AM on 02 January, 2026",
                        "session_1": [
                            {"speaker": "Alice", "text": "First fact", "dia_id": "D1"},
                            {"speaker": "Bob", "text": "Second fact", "dia_id": "D2"},
                        ],
                    },
                    "qa": [
                        {
                            "question": "What happened?",
                            "answer": "Both facts",
                            "evidence": ["D1;D2"],
                            "category": 1,
                        }
                    ],
                }
            ]
        ),
        encoding="utf-8",
    )

    cases = build_locomo(dataset)

    query = cases[0]["queries"][0]
    messages = cases[0]["sessions"][0]["messages"]
    assert query["gold_evidence_texts"] == ["First fact", "Second fact"]
    assert query["capability"] == "relational_multi_hop"
    assert all(isinstance(message["timestamp"], int) for message in messages)


def test_longmemeval_builder_marks_session_granularity(tmp_path: Path) -> None:
    dataset = tmp_path / "longmemeval.json"
    dataset.write_text(
        json.dumps(
            [
                {
                    "question_id": "q1",
                    "question": "Where?",
                    "answer": "Paris",
                    "question_type": "single-session-user",
                    "haystack_session_ids": ["s1", "s2"],
                    "answer_session_ids": ["s2"],
                    "haystack_dates": ["2026-01-01", "2026-01-02"],
                    "haystack_sessions": [
                        [{"role": "user", "content": "Noise"}],
                        [{"role": "user", "content": "I moved to Paris"}],
                    ],
                }
            ]
        ),
        encoding="utf-8",
    )

    cases = build_longmemeval(dataset)

    query = cases[0]["queries"][0]
    assert query["gold_evidence_texts"] == ["I moved to Paris"]
    assert query["evidence_granularity"] == "session"


def test_chunk_messages_obeys_message_and_word_limits() -> None:
    messages = [
        {"role": "user", "content": "one two"},
        {"role": "assistant", "content": "three four"},
        {"role": "user", "content": "中文"},
    ]

    chunks = _chunk_messages(messages, max_messages=2, max_words=4)

    assert [len(chunk) for chunk in chunks] == [2, 1]
    assert _matches("[timestamp] user: I moved to Paris", "I moved to Paris")


def test_synthetic_suite_covers_all_aml_text_capabilities() -> None:
    suite = build_suite()
    capabilities = {query["capability"] for case in suite["cases"] for query in case["queries"]}

    assert capabilities == {
        "explicit_fact",
        "relational_multi_hop",
        "temporal_event",
        "memory_governance",
        "personalization_care",
        "rules_process",
        "epistemic_safety_privacy",
    }
    assert any(query.get("expected_empty") for case in suite["cases"] for query in case["queries"])
