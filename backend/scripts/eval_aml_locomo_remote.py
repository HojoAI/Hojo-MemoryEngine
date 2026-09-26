#!/usr/bin/env python3
"""Evaluate a deployed AML service on public LoCoMo evidence annotations."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from uuid import uuid4

import httpx


def _headers(api_key: str, auth_mode: str) -> dict[str, str]:
    if auth_mode == "x-api-key":
        return {"X-Api-Key": api_key}
    return {"Authorization": f"{auth_mode.title()} {api_key}"}


def _sessions(sample: dict) -> list[tuple[str, str, list[dict]]]:
    conversation = sample["conversation"]
    speaker_a = str(conversation.get("speaker_a") or "")
    result: list[tuple[str, str, list[dict]]] = []
    names = sorted(
        (
            key
            for key, value in conversation.items()
            if key.startswith("session_")
            and not key.endswith("_date_time")
            and isinstance(value, list)
        ),
        key=lambda key: int(key.split("_")[1]),
    )
    for name in names:
        date = str(conversation.get(f"{name}_date_time") or "unknown time")
        messages = []
        for turn in conversation[name]:
            text = str(turn.get("text") or turn.get("blip_caption") or "").strip()
            evidence_id = str(turn.get("dia_id") or "")
            speaker = str(turn.get("speaker") or "")
            if not text or not evidence_id:
                continue
            messages.append(
                {
                    "role": "user" if speaker == speaker_a else "assistant",
                    "content": text,
                    "_evidence_id": evidence_id,
                    "_search_text": f"[{date}] {speaker}: {text}",
                }
            )
        if messages:
            result.append((name, date, messages))
    return result


def _clean_text(value: str) -> str:
    return " ".join(value.lower().split())


def _locomo_timestamp_ms(value: str) -> int | None:
    try:
        parsed = datetime.strptime(value, "%I:%M %p on %d %B, %Y").replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    return int(parsed.timestamp() * 1000)


def _post_json(
    base_url: str,
    headers: dict[str, str],
    path: str,
    payload: dict,
    timeout: float,
    retries: int,
    retry_backoff: float,
) -> tuple[dict, float]:
    started = time.perf_counter()
    with httpx.Client(base_url=base_url.rstrip("/"), headers=headers, timeout=timeout) as client:
        for attempt in range(retries + 1):
            response = client.post(path, json=payload)
            if response.status_code not in {429, 502, 503, 504} or attempt >= retries:
                response.raise_for_status()
                return response.json(), time.perf_counter() - started
            time.sleep(retry_backoff * (2**attempt))
    raise RuntimeError("unreachable")


def _evidence_texts(sample: dict, evidence_ids: set[str]) -> list[str]:
    texts = []
    for _name, _date, messages in _sessions(sample):
        for message in messages:
            if message["_evidence_id"] in evidence_ids:
                texts.append(_clean_text(message["content"]))
    return texts


def _evidence_ids(raw_values: list[object]) -> set[str]:
    return {part.strip() for value in raw_values for part in str(value).split(";") if part.strip()}


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    position = (len(ordered) - 1) * percentile
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] * (1 - fraction) + ordered[upper] * fraction


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--base-url", default=os.getenv("AML_BASE_URL", ""))
    parser.add_argument("--api-key", default=os.getenv("AML_MEMORY_SYSTEM_KEY", ""))
    parser.add_argument(
        "--auth-mode",
        choices=("bearer", "token", "x-api-key"),
        default=os.getenv("AML_AUTH_MODE", "bearer"),
    )
    parser.add_argument("--sample-limit", type=int, default=0)
    parser.add_argument("--question-limit", type=int, default=0)
    parser.add_argument("--top-k", type=int, default=100)
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--retry-backoff", type=float, default=1.0)
    parser.add_argument(
        "--concurrency",
        type=int,
        default=1,
        help="parallel Add/Search requests; start with 4 and increase cautiously",
    )
    parser.add_argument("--include-adversarial", action="store_true")
    parser.add_argument("--keep-data", action="store_true")
    parser.add_argument(
        "--output-json",
        type=Path,
        help="write aggregate metrics and per-question retrieval diagnostics",
    )
    parser.add_argument(
        "--diagnostic-top-k",
        type=int,
        default=10,
        help="number of returned evidence snippets saved per question",
    )
    args = parser.parse_args()
    if not args.base_url or not args.api_key:
        parser.error("set AML_BASE_URL and AML_MEMORY_SYSTEM_KEY, or pass --base-url and --api-key")
    if not 1 <= args.top_k <= 100:
        parser.error("--top-k must be between 1 and 100")
    if not 1 <= args.concurrency <= 32:
        parser.error("--concurrency must be between 1 and 32")
    if not 0 <= args.retries <= 10:
        parser.error("--retries must be between 0 and 10")
    if not 0 <= args.diagnostic_top_k <= 100:
        parser.error("--diagnostic-top-k must be between 0 and 100")
    run_started = time.perf_counter()

    samples = json.loads(args.dataset.read_text(encoding="utf-8"))
    if isinstance(samples, dict):
        samples = samples.get("samples") or samples.get("data") or []
    if args.sample_limit:
        samples = samples[: args.sample_limit]

    run_id = uuid4().hex[:12]
    headers = _headers(args.api_key, args.auth_mode)
    user_ids: list[str] = []
    total = 0
    reciprocal_rank = 0.0
    any_hits = defaultdict(int)
    all_hits = defaultdict(int)
    by_category: dict[str, list[int]] = defaultdict(list)
    add_count = 0
    search_count = 0
    add_seconds = 0.0
    search_seconds = 0.0
    add_latencies: list[float] = []
    search_latencies: list[float] = []
    questions_seen = 0
    diagnostics: list[dict] = []

    try:
        with httpx.Client(
            base_url=args.base_url.rstrip("/"), headers=headers, timeout=args.timeout
        ) as client:
            health = client.get("/aml/health")
            health.raise_for_status()
            if health.json().get("status") != "ok":
                raise RuntimeError(f"AML health is not ok: {health.text}")

            for sample_index, sample in enumerate(samples):
                sample_id = str(sample.get("sample_id") or sample_index)
                user_id = f"locomo:{run_id}:{sample_id}"
                user_ids.append(user_id)
                add_jobs: list[dict] = []
                for session_index, (session_name, date, messages) in enumerate(_sessions(sample)):
                    timestamp_ms = _locomo_timestamp_ms(date)
                    payload_messages = [
                        {
                            "role": item["role"],
                            "content": item["content"],
                            **({"timestamp": timestamp_ms} if timestamp_ms is not None else {}),
                        }
                        for item in messages
                    ]
                    payload = {
                        "request_id": f"locomo:{run_id}:{sample_id}:{session_name}",
                        "user_id": user_id,
                        "session_id": f"{sample_id}:{session_index}",
                        "messages": payload_messages,
                    }
                    add_jobs.append(payload)

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
                        add_seconds += elapsed
                        add_latencies.append(elapsed)
                        add_count += 1

                search_jobs: list[tuple[dict, set[str], str]] = []
                for question in sample.get("qa") or []:
                    if args.question_limit and questions_seen >= args.question_limit:
                        break
                    category = str(question.get("category") or "unknown")
                    evidence = _evidence_ids(question.get("evidence") or [])
                    if not evidence or (category == "5" and not args.include_adversarial):
                        continue
                    questions_seen += 1
                    search_jobs.append(
                        (
                            {
                                "query": question["question"],
                                "user_id": user_id,
                                "top_k": args.top_k,
                            },
                            evidence,
                            category,
                        )
                    )
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
                        for payload, _evidence, _category in search_jobs
                    ]
                    results = [future.result() for future in futures]

                for (payload, evidence, category), (response_json, elapsed) in zip(
                    search_jobs, results, strict=True
                ):
                    search_seconds += elapsed
                    search_latencies.append(elapsed)
                    search_count += 1
                    returned = response_json.get("data") or []
                    returned_texts = [
                        _clean_text(str(item.get("content") or "")) for item in returned
                    ]
                    gold_texts = _evidence_texts(sample, evidence)
                    ranks = [
                        index + 1
                        for index, content in enumerate(returned_texts)
                        if any(gold and gold in content for gold in gold_texts)
                    ]
                    total += 1
                    best_rank = min(ranks) if ranks else 0
                    by_category[category].append(best_rank)
                    if best_rank:
                        reciprocal_rank += 1 / best_rank
                    for k in (1, 5, 10, 20, 50, 100):
                        retrieved = returned_texts[:k]
                        if any(
                            any(gold and gold in content for gold in gold_texts)
                            for content in retrieved
                        ):
                            any_hits[k] += 1
                        if gold_texts and all(
                            any(gold and gold in content for content in retrieved)
                            for gold in gold_texts
                        ):
                            all_hits[k] += 1
                    diagnostics.append(
                        {
                            "sample_id": sample_id,
                            "category": category,
                            "query": payload["query"],
                            "gold_evidence_ids": sorted(evidence),
                            "gold_evidence_texts": gold_texts,
                            "best_rank": best_rank,
                            "matching_ranks": ranks,
                            "returned_count": len(returned),
                            "search_seconds": elapsed,
                            "top_evidence": [
                                {
                                    "rank": index + 1,
                                    "id": str(item.get("id") or ""),
                                    "score": item.get("score"),
                                    "content": str(item.get("content") or "")[:1000],
                                }
                                for index, item in enumerate(returned[: args.diagnostic_top_k])
                            ],
                        }
                    )

                print(
                    f"processed sample={sample_id} questions={total} adds={add_count} "
                    f"concurrency={args.concurrency}",
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
                    except Exception as exc:  # cleanup failure must remain visible
                        print(f"cleanup failed for {user_id}: {exc}", file=sys.stderr)

    mrr = reciprocal_rank / max(1, total)
    print(f"questions={total} mrr={mrr:.4f}")
    for k in (1, 5, 10, 20, 50, 100):
        print(
            f"k={k:>3} any_evidence_recall={any_hits[k] / max(1, total):.4f} "
            f"all_evidence_recall={all_hits[k] / max(1, total):.4f}"
        )
    for category in sorted(by_category):
        ranks = by_category[category]
        hit_at_10 = sum(1 for rank in ranks if 0 < rank <= 10) / max(1, len(ranks))
        category_mrr = sum(1 / rank for rank in ranks if rank) / max(1, len(ranks))
        print(
            f"category={category} questions={len(ranks)} mrr={category_mrr:.4f} "
            f"any_evidence_recall@10={hit_at_10:.4f}"
        )
    print(f"adds={add_count} avg_add_seconds={add_seconds / max(1, add_count):.3f}")
    print(f"searches={search_count} avg_search_seconds={search_seconds / max(1, search_count):.3f}")
    print(
        f"add_latency_p50={median(add_latencies) if add_latencies else 0.0:.3f} "
        f"p95={_percentile(add_latencies, 0.95):.3f}"
    )
    print(
        f"search_latency_p50={median(search_latencies) if search_latencies else 0.0:.3f} "
        f"p95={_percentile(search_latencies, 0.95):.3f}"
    )
    wall_seconds = time.perf_counter() - run_started
    print(f"wall_seconds={wall_seconds:.1f}")
    if args.output_json:
        category_metrics = {}
        for category, ranks in sorted(by_category.items()):
            category_metrics[category] = {
                "questions": len(ranks),
                "mrr": sum(1 / rank for rank in ranks if rank) / max(1, len(ranks)),
                "any_evidence_recall_at_10": (
                    sum(1 for rank in ranks if 0 < rank <= 10) / max(1, len(ranks))
                ),
            }
        report = {
            "run_id": run_id,
            "dataset": str(args.dataset),
            "base_url": args.base_url,
            "configuration": {
                "sample_limit": args.sample_limit,
                "question_limit": args.question_limit,
                "top_k": args.top_k,
                "concurrency": args.concurrency,
                "include_adversarial": args.include_adversarial,
            },
            "metrics": {
                "questions": total,
                "mrr": mrr,
                "any_evidence_recall": {
                    str(k): any_hits[k] / max(1, total) for k in (1, 5, 10, 20, 50, 100)
                },
                "all_evidence_recall": {
                    str(k): all_hits[k] / max(1, total) for k in (1, 5, 10, 20, 50, 100)
                },
                "categories": category_metrics,
                "adds": add_count,
                "searches": search_count,
                "add_latency_seconds": {
                    "average": add_seconds / max(1, add_count),
                    "p50": median(add_latencies) if add_latencies else 0.0,
                    "p95": _percentile(add_latencies, 0.95),
                },
                "search_latency_seconds": {
                    "average": search_seconds / max(1, search_count),
                    "p50": median(search_latencies) if search_latencies else 0.0,
                    "p95": _percentile(search_latencies, 0.95),
                },
                "wall_seconds": wall_seconds,
            },
            "diagnostics": diagnostics,
        }
        args.output_json.parent.mkdir(parents=True, exist_ok=True)
        args.output_json.write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"report={args.output_json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
