#!/usr/bin/env python3
"""Generate a small, license-safe AML text-memory regression suite.

The suite is intentionally synthetic. It complements public benchmarks by
covering AML capability dimensions that retrieval-only datasets often miss,
especially corrections, rules, personalization, and isolation.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any


def _ms(value: str) -> int:
    return int(datetime.fromisoformat(value).replace(tzinfo=timezone.utc).timestamp() * 1000)


def _session(session_id: str, timestamp: str, *messages: tuple[str, str]) -> dict[str, Any]:
    timestamp_ms = _ms(timestamp)
    return {
        "session_id": session_id,
        "messages": [
            {"role": role, "content": content, "timestamp": timestamp_ms}
            for role, content in messages
        ],
    }


def build_suite() -> dict[str, Any]:
    cases = [
        {
            "case_id": "explicit-fact",
            "source": "aml-synthetic",
            "sessions": [
                _session(
                    "profile",
                    "2026-01-03T09:00:00",
                    ("user", "我的登山鞋尺码是欧码 43，常用品牌是 Salomon。"),
                    ("assistant", "记住了你的登山装备偏好。"),
                ),
                _session(
                    "distractor",
                    "2026-01-04T09:00:00",
                    ("user", "我给弟弟买了一双欧码 41 的跑鞋。"),
                    ("assistant", "那是给你弟弟的跑鞋。"),
                ),
            ],
            "queries": [
                {
                    "query_id": "explicit-fact:q1",
                    "query": "我的登山鞋穿多大尺码？",
                    "gold_answer": "欧码 43",
                    "gold_evidence_texts": ["我的登山鞋尺码是欧码 43，常用品牌是 Salomon。"],
                    "forbidden_evidence_texts": ["我给弟弟买了一双欧码 41 的跑鞋。"],
                    "capability": "explicit_fact",
                }
            ],
        },
        {
            "case_id": "relational-multi-hop",
            "source": "aml-synthetic",
            "sessions": [
                _session(
                    "people",
                    "2026-02-01T10:00:00",
                    ("user", "林夏是我大学室友，她现在住在成都。"),
                    ("assistant", "林夏是你的大学室友。"),
                ),
                _session(
                    "hobby",
                    "2026-02-18T19:00:00",
                    ("user", "林夏最近开始学习川剧变脸，每周六去锦江剧场上课。"),
                    ("assistant", "记住了林夏的新爱好和上课地点。"),
                ),
            ],
            "queries": [
                {
                    "query_id": "relational-multi-hop:q1",
                    "query": "我那位住在成都的大学室友最近学什么？",
                    "gold_answer": "川剧变脸",
                    "gold_evidence_texts": [
                        "林夏是我大学室友，她现在住在成都。",
                        "林夏最近开始学习川剧变脸，每周六去锦江剧场上课。",
                    ],
                    "capability": "relational_multi_hop",
                }
            ],
        },
        {
            "case_id": "temporal-latest-state",
            "source": "aml-synthetic",
            "sessions": [
                _session(
                    "old-address",
                    "2025-05-09T08:30:00",
                    ("user", "我的收货地址是杭州文一路 88 号。"),
                    ("assistant", "已记录杭州的收货地址。"),
                ),
                _session(
                    "new-address",
                    "2026-03-12T16:20:00",
                    ("user", "我已经搬家，收货地址改成上海愚园路 120 号，旧地址不要再用了。"),
                    ("assistant", "以后使用上海愚园路 120 号。"),
                ),
            ],
            "queries": [
                {
                    "query_id": "temporal-latest-state:q1",
                    "query": "我现在的收货地址是什么？",
                    "gold_answer": "上海愚园路 120 号",
                    "gold_evidence_texts": [
                        "我已经搬家，收货地址改成上海愚园路 120 号，旧地址不要再用了。"
                    ],
                    "forbidden_evidence_texts": ["我的收货地址是杭州文一路 88 号。"],
                    "capability": "temporal_event",
                },
                {
                    "query_id": "temporal-latest-state:q2",
                    "query": "2025 年 5 月时我的收货地址在哪里？",
                    "gold_answer": "杭州文一路 88 号",
                    "gold_evidence_texts": ["我的收货地址是杭州文一路 88 号。"],
                    "capability": "temporal_event",
                },
            ],
        },
        {
            "case_id": "memory-governance",
            "source": "aml-synthetic",
            "sessions": [
                _session(
                    "initial",
                    "2026-04-01T11:00:00",
                    ("user", "项目 Aurora 的发布负责人暂定为周宁。"),
                    ("assistant", "已记录暂定负责人周宁。"),
                ),
                _session(
                    "correction",
                    "2026-04-08T11:00:00",
                    ("user", "更正一下，Aurora 的发布负责人最终确定为赵琪，不是周宁。"),
                    ("assistant", "已更新为赵琪，周宁的记录作废。"),
                ),
            ],
            "queries": [
                {
                    "query_id": "memory-governance:q1",
                    "query": "Aurora 最终的发布负责人是谁？",
                    "gold_answer": "赵琪",
                    "gold_evidence_texts": [
                        "更正一下，Aurora 的发布负责人最终确定为赵琪，不是周宁。"
                    ],
                    "forbidden_evidence_texts": ["项目 Aurora 的发布负责人暂定为周宁。"],
                    "capability": "memory_governance",
                }
            ],
        },
        {
            "case_id": "personalization-care",
            "source": "aml-synthetic",
            "sessions": [
                _session(
                    "diet",
                    "2026-05-03T12:00:00",
                    ("user", "我对花生严重过敏，而且不吃香菜。"),
                    ("assistant", "推荐餐食时会避开花生和香菜。"),
                ),
                _session(
                    "preference",
                    "2026-05-04T12:00:00",
                    ("user", "我喜欢清淡的粤菜，尤其喜欢蒸鱼。"),
                    ("assistant", "记住了你偏好清淡粤菜。"),
                ),
            ],
            "queries": [
                {
                    "query_id": "personalization-care:q1",
                    "query": "给我推荐晚餐时需要遵守哪些饮食偏好和安全限制？",
                    "gold_answer": "清淡粤菜或蒸鱼，但必须避开花生和香菜",
                    "gold_evidence_texts": [
                        "我对花生严重过敏，而且不吃香菜。",
                        "我喜欢清淡的粤菜，尤其喜欢蒸鱼。",
                    ],
                    "capability": "personalization_care",
                }
            ],
        },
        {
            "case_id": "rules-process",
            "source": "aml-synthetic",
            "sessions": [
                _session(
                    "workflow",
                    "2026-06-06T14:00:00",
                    (
                        "user",
                        "报销规则：金额超过 5000 元时，先上传发票，再由直属主管审批，最后提交财务复核；不得跳过主管审批。",
                    ),
                    ("assistant", "记住了超过 5000 元的报销流程。"),
                )
            ],
            "queries": [
                {
                    "query_id": "rules-process:q1",
                    "query": "一笔 6800 元报销在上传发票后，下一步应该做什么？",
                    "gold_answer": "交给直属主管审批",
                    "gold_evidence_texts": [
                        "报销规则：金额超过 5000 元时，先上传发票，再由直属主管审批，最后提交财务复核；不得跳过主管审批。"
                    ],
                    "capability": "rules_process",
                }
            ],
        },
        {
            "case_id": "epistemic-safety",
            "source": "aml-synthetic",
            "sessions": [
                _session(
                    "known",
                    "2026-07-10T09:00:00",
                    ("user", "我确认下周二下午三点和陈医生复诊。"),
                    ("assistant", "已记录复诊时间。"),
                )
            ],
            "queries": [
                {
                    "query_id": "epistemic-safety:q1",
                    "query": "陈医生给我开的药每天吃几次？",
                    "gold_answer": "记忆中没有这项信息",
                    "gold_evidence_texts": [],
                    "expected_empty": True,
                    "capability": "epistemic_safety_privacy",
                }
            ],
        },
        {
            "case_id": "privacy-isolation-empty-user",
            "source": "aml-synthetic",
            "sessions": [],
            "queries": [
                {
                    "query_id": "privacy-isolation-empty-user:q1",
                    "query": "我的登山鞋尺码是多少？",
                    "gold_answer": "记忆中没有这项信息",
                    "gold_evidence_texts": [],
                    "expected_empty": True,
                    "capability": "epistemic_safety_privacy",
                }
            ],
        },
    ]
    return {
        "schema_version": "aml-shadow-v1",
        "source": "aml-synthetic",
        "description": "Synthetic regression cases for the seven AML text-memory capabilities.",
        "cases": cases,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    manifest = build_suite()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    cases = manifest["cases"]
    print(
        f"wrote cases={len(cases)} queries={sum(len(case['queries']) for case in cases)} "
        f"to {args.output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
