#!/usr/bin/env python3
"""Run a normalized public-data shadow suite against a deployed AML API."""

from __future__ import annotations

import argparse
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
from statistics import median
import sys
import time
from typing import Any
from uuid import uuid4

import httpx

from eval_aml_locomo_remote import _clean_text, _headers, _percentile, _post_json


def _word_count(text: str) -> int:
    """Approximate AML adapter words while keeping CJK text bounded."""
    import re

    return len(re.findall(r"[a-zA-Z0-9_]+|[\u3400-\u9fff]", text))


def _chunk_messages(
    messages: list[dict[str, Any]], *, max_messages: int, max_words: int
) -> list[list[dict[str, Any]]]:
    chunks: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    current_words = 0
    for message in messages:
        words = _word_count(str(message.get("content") or ""))
        if current and (len(current) >= max_messages or current_words + words > max_words):
            chunks.append(current)
            current = []
            current_words = 0
        current.append(message)
        current_words += words
    if current:
        chunks.append(current)
    return chunks


def _matches(returned_content: str, gold_text: str) -> bool:
    returned = _clean_text(returned_content)
    gold = _clean_text(gold_text)
    return bool(gold) and (gold in returned or returned in gold)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--base-url", default=os.getenv("AML_BASE_URL", ""))
    parser.add_argument("--api-key", default=os.getenv("AML_MEMORY_SYSTEM_KEY", ""))
    parser.add_argument(
        "--auth-mode",
        choices=("bearer", "token", "x-api-key"),
        default=os.getenv("AML_AUTH_MODE", "bearer"),
    )
    parser.add_argument("--case-limit", type=int, default=0)
    parser.add_argument("--query-limit", type=int, default=0)
    parser.add_argument("--top-k", type=int, default=100)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--retry-backoff", type=float, default=1.0)
    parser.add_argument("--max-messages-per-add", type=int, default=20)
    parser.add_argument("--max-words-per-add", type=int, default=2000)
    parser.add_argument("--diagnostic-top-k", type=int, default=10)
    parser.add_argument("--output-json", type=Path)
    parser.add_argument("--keep-data", action="store_true")
    args = parser.parse_args()
    if not args.base_url or not args.api_key:
        parser.error("set AML_BASE_URL and AML_MEMORY_SYSTEM_KEY, or pass explicit values")
    if not 1 <= args.top_k <= 100:
        parser.error("--top-k must be between 1 and 100")
    if not 1 <= args.concurrency <= 32:
        parser.error("--concurrency must be between 1 and 32")

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    cases = manifest.get("cases") or []
    if args.case_limit:
        cases = cases[: args.case_limit]
    run_id = uuid4().hex[:12]
    headers = _headers(args.api_key, args.auth_mode)
    user_ids: list[str] = []
    diagnostics: list[dict[str, Any]] = []
    by_capability: dict[str, list[int]] = defaultdict(list)
    any_hits = defaultdict(int)
    all_hits = defaultdict(int)
    add_latencies: list[float] = []
    search_latencies: list[float] = []
    total = 0
    retrieval_questions = 0
    reciprocal_rank = 0.0
    all_evidence_eligible = 0
    negative_queries = 0
    negative_queries_passed = 0
    forbidden_top_1 = 0
    forbidden_top_10 = 0
    started = time.perf_counter()

    try:
        with httpx.Client(
            base_url=args.base_url.rstrip("/"), headers=headers, timeout=args.timeout
        ) as client:
            health = client.get("/aml/health")
            health.raise_for_status()
            if health.json().get("status") != "ok":
                raise RuntimeError(f"AML health is not ok: {health.text}")

        queries_seen = 0
        for case_index, case in enumerate(cases):
            case_id = str(case.get("case_id") or case_index)
            user_id = f"shadow:{run_id}:{case_id}"
            user_ids.append(user_id)
            add_jobs = []
            for session_index, session in enumerate(case.get("sessions") or []):
                session_id = str(session.get("session_id") or f"session-{session_index}")
                chunks = _chunk_messages(
                    list(session.get("messages") or []),
                    max_messages=args.max_messages_per_add,
                    max_words=args.max_words_per_add,
                )
                for chunk_index, chunk in enumerate(chunks):
                    add_jobs.append(
                        {
                            "request_id": (
                                f"shadow:{run_id}:{case_id}:{session_index}:{chunk_index}"
                            ),
                            "user_id": user_id,
                            "session_id": session_id,
                            "messages": chunk,
                        }
                    )
            with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
                futures = [
                    pool.submit(
                        _post_json,
                        args.base_url,
                        headers,
                        "/aml/add",
                        payload,
                        args.timeout,
                        args.retries,
                        args.retry_backoff,
                    )
                    for payload in add_jobs
                ]
                for future in futures:
                    _response, elapsed = future.result()
                    add_latencies.append(elapsed)

            search_jobs = []
            for query in case.get("queries") or []:
                if args.query_limit and queries_seen >= args.query_limit:
                    break
                gold_texts = [str(value) for value in query.get("gold_evidence_texts") or []]
                expected_empty = bool(query.get("expected_empty"))
                if not str(query.get("query") or "").strip() or (
                    not gold_texts and not expected_empty
                ):
                    continue
                queries_seen += 1
                payload = {
                    "query": str(query["query"]),
                    "user_id": user_id,
                    "top_k": args.top_k,
                }
                options = query.get("options")
                if options:
                    payload["options"] = options
                search_jobs.append((payload, query, gold_texts, expected_empty))

            with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
                futures = [
                    pool.submit(
                        _post_json,
                        args.base_url,
                        headers,
                        "/aml/search",
                        payload,
                        args.timeout,
                        args.retries,
                        args.retry_backoff,
                    )
                    for payload, _query, _gold_texts, _expected_empty in search_jobs
                ]
                results = [future.result() for future in futures]

            for (payload, query, gold_texts, expected_empty), (response, elapsed) in zip(
                search_jobs, results, strict=True
            ):
                returned = response.get("data") or []
                forbidden_texts = [
                    str(value) for value in query.get("forbidden_evidence_texts") or []
                ]
                ranks = [
                    rank
                    for rank, item in enumerate(returned, start=1)
                    if any(_matches(str(item.get("content") or ""), gold) for gold in gold_texts)
                ]
                best_rank = min(ranks) if ranks else 0
                capability = str(query.get("capability") or "unknown")
                total += 1
                search_latencies.append(elapsed)
                if expected_empty:
                    negative_queries += 1
                    if not returned:
                        negative_queries_passed += 1
                else:
                    retrieval_questions += 1
                    by_capability[capability].append(best_rank)
                    if best_rank:
                        reciprocal_rank += 1 / best_rank
                if forbidden_texts and returned:
                    if any(
                        _matches(str(returned[0].get("content") or ""), forbidden)
                        for forbidden in forbidden_texts
                    ):
                        forbidden_top_1 += 1
                    if any(
                        _matches(str(item.get("content") or ""), forbidden)
                        for item in returned[:10]
                        for forbidden in forbidden_texts
                    ):
                        forbidden_top_10 += 1
                if not expected_empty:
                    for k in (1, 5, 10, 20, 50, 100):
                        top_items = returned[:k]
                        if any(
                            _matches(str(item.get("content") or ""), gold)
                            for item in top_items
                            for gold in gold_texts
                        ):
                            any_hits[k] += 1
                evidence_granularity = str(query.get("evidence_granularity") or "message")
                if evidence_granularity == "message" and not expected_empty:
                    all_evidence_eligible += 1
                    for k in (1, 5, 10, 20, 50, 100):
                        top_items = returned[:k]
                        if all(
                            any(
                                _matches(str(item.get("content") or ""), gold) for item in top_items
                            )
                            for gold in gold_texts
                        ):
                            all_hits[k] += 1
                diagnostics.append(
                    {
                        "case_id": case_id,
                        "source": case.get("source"),
                        "query_id": query.get("query_id"),
                        "capability": capability,
                        "query": payload["query"],
                        "gold_answer": query.get("gold_answer"),
                        "evidence_granularity": evidence_granularity,
                        "best_rank": best_rank,
                        "matching_ranks": ranks,
                        "expected_empty": expected_empty,
                        "empty_result": not returned,
                        "forbidden_in_top_1": any(
                            _matches(str(item.get("content") or ""), forbidden)
                            for item in returned[:1]
                            for forbidden in forbidden_texts
                        ),
                        "forbidden_in_top_10": any(
                            _matches(str(item.get("content") or ""), forbidden)
                            for item in returned[:10]
                            for forbidden in forbidden_texts
                        ),
                        "search_seconds": elapsed,
                        "top_evidence": [
                            {
                                "rank": index + 1,
                                "id": item.get("id"),
                                "score": item.get("score"),
                                "content": str(item.get("content") or "")[:1000],
                            }
                            for index, item in enumerate(returned[: args.diagnostic_top_k])
                        ],
                    }
                )
            print(
                f"processed case={case_id} questions={total} adds={len(add_latencies)}",
                flush=True,
            )
    finally:
        if not args.keep_data and user_ids:
            with httpx.Client(
                base_url=args.base_url.rstrip("/"), headers=headers, timeout=args.timeout
            ) as client:
                for user_id in user_ids:
                    try:
                        response = client.post("/aml/clear", json={"user_id": user_id})
                        response.raise_for_status()
                    except Exception as exc:
                        print(f"cleanup failed for {user_id}: {exc}", file=sys.stderr)

    wall_seconds = time.perf_counter() - started
    metrics = {
        "questions": total,
        "retrieval_questions": retrieval_questions,
        "mrr": reciprocal_rank / max(1, retrieval_questions),
        "any_evidence_recall": {
            str(k): any_hits[k] / max(1, retrieval_questions) for k in (1, 5, 10, 20, 50, 100)
        },
        "all_evidence_recall": {
            str(k): all_hits[k] / max(1, all_evidence_eligible) for k in (1, 5, 10, 20, 50, 100)
        },
        "all_evidence_eligible_questions": all_evidence_eligible,
        "negative_queries": negative_queries,
        "negative_query_empty_rate": negative_queries_passed / max(1, negative_queries),
        "forbidden_evidence_top_1_count": forbidden_top_1,
        "forbidden_evidence_top_10_count": forbidden_top_10,
        "capabilities": {
            capability: {
                "questions": len(ranks),
                "mrr": sum(1 / rank for rank in ranks if rank) / max(1, len(ranks)),
                "recall_at_10": sum(1 for rank in ranks if 0 < rank <= 10) / max(1, len(ranks)),
            }
            for capability, ranks in sorted(by_capability.items())
        },
        "add_latency_seconds": {
            "p50": median(add_latencies) if add_latencies else 0.0,
            "p95": _percentile(add_latencies, 0.95),
        },
        "search_latency_seconds": {
            "p50": median(search_latencies) if search_latencies else 0.0,
            "p95": _percentile(search_latencies, 0.95),
        },
        "wall_seconds": wall_seconds,
    }
    print(json.dumps(metrics, ensure_ascii=False, indent=2))
    if args.output_json:
        args.output_json.parent.mkdir(parents=True, exist_ok=True)
        args.output_json.write_text(
            json.dumps(
                {
                    "run_id": run_id,
                    "manifest": str(args.manifest),
                    "base_url": args.base_url,
                    "metrics": metrics,
                    "diagnostics": diagnostics,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"report={args.output_json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
