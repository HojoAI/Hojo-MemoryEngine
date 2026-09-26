# Agent Memory Leaderboard adapter

MemoryEngine exposes an evidence-only implementation of the AML synchronous Add/Search contract.
The adapter stores original conversational turns, preserves role and timestamp in returned
evidence, and combines lexical BM25-style recall with dense retrieval through reciprocal rank
fusion. It never generates a final answer.

## Endpoints

| Method | Path | Authentication | Purpose |
| --- | --- | --- | --- |
| `GET` | `/aml/health` | none | Mongo/Qdrant readiness |
| `POST` | `/aml/add` | Bearer, Token, or X-Api-Key | synchronous evidence ingestion |
| `POST` | `/aml/search` | Bearer, Token, or X-Api-Key | ranked evidence retrieval |
| `POST` | `/aml/clear` | Bearer, Token, or X-Api-Key | operational deletion for one `user_id` |

The Memory System Key is a normal MemoryEngine API key. Use a dedicated tenant and key for AML.
Do not place either the Memory System Key or the AML Leaderboard Key in source control, URLs,
screenshots, email, or chat.

## Runtime behavior

- Add is idempotent by `request_id`. Reusing an ID with another payload returns HTTP 409.
- Every message is persisted before success is returned.
- Vector indexing is synchronous by default. Set `AML_REQUIRE_VECTOR_INDEX=false` only for local
  lexical-only development; formal runs should keep the default.
- Search is hard-filtered by tenant, organization, and the exact AML `user_id`.
- Multiple-choice options are used only as an additional retrieval channel.
- Lexical recall normalizes simple English inflections and indexes Chinese phrase bigrams.
- Exact entity/value coverage, current-state temporal ranking, aggregation operands, adjacent raw
  turns, and cross-session diversity are independently configurable retrieval channels. They never
  rewrite source evidence. Temporal ranking activates only for explicit current/latest/final-state
  queries, so dated historical questions retain normal relevance ranking.
- A small configurable role bias keeps first-person user facts above generic assistant
  acknowledgements while preserving assistant evidence in the candidate list.
- Search returns source evidence, never a generated answer.
- `/aml/clear` physically deletes Mongo records and Qdrant points for one AML `user_id`.
- When enabled, `gpt-4o-mini` extracts auxiliary retrieval terms during Add and reranks
  retrieved evidence during Search; the original evidence remains authoritative and is the only
  content returned by Search.

## Configuration

| Environment variable | Default | Description |
| --- | --- | --- |
| `AML_REQUIRE_VECTOR_INDEX` | `true` | fail Add when synchronous vector indexing fails |
| `AML_CANDIDATE_LIMIT` | `400` | dense candidates per retrieval channel |
| `AML_MAX_USER_UNITS` | `10000` | maximum raw turns considered by lexical retrieval |
| `AML_RRF_K` | `60` | reciprocal-rank-fusion damping constant |
| `AML_VECTOR_WEIGHT` | `1.0` | dense channel weight |
| `AML_LEXICAL_WEIGHT` | `1.0` | lexical channel weight |
| `AML_OPTION_WEIGHT` | `0.35` | optional answer-choice retrieval channel weight |
| `AML_EXACT_MATCH_ENABLED` | `true` | rank explicit query terms, numbers, amounts, and dates |
| `AML_EXACT_MATCH_WEIGHT` | `0.45` | RRF weight for the exact-match channel |
| `AML_TEMPORAL_RANKING_ENABLED` | `true` | prefer updated recent evidence for current-state queries |
| `AML_TEMPORAL_WEIGHT` | `0.35` | RRF weight for the current-state temporal channel |
| `AML_AGGREGATION_WEIGHT` | `0.35` | retain concrete amounts, counts, and durations for totals |
| `AML_USER_EVIDENCE_BOOST` | `0.06` | multiplicative boost for source user turns |
| `AML_ASSISTANT_EVIDENCE_PENALTY` | `0.12` | multiplicative penalty for assistant turns |
| `AML_NEIGHBOR_EVIDENCE_ENABLED` | `true` | recall adjacent raw turns around strong seeds |
| `AML_NEIGHBOR_SEED_LIMIT` | `8` | maximum top-ranked seeds used for neighbor expansion |
| `AML_NEIGHBOR_WINDOW` | `1` | adjacent messages recalled on either side of a seed |
| `AML_NEIGHBOR_WEIGHT` | `0.35` | RRF-style weight for adjacent evidence |
| `AML_SESSION_DIVERSITY_ENABLED` | `true` | prefer evidence from multiple source sessions |
| `AML_SESSION_MAX_ITEMS` | `4` | first-pass maximum evidence records per session |
| `AML_LLM_MODEL` | `gpt-4o-mini` | model used by the optional Add/Search LLM steps |
| `AML_LLM_ADD_AUGMENT_ENABLED` | `false` | use the model to add auxiliary retrieval terms during Add |
| `AML_LLM_RERANK_ENABLED` | `false` | use the model to rerank retrieved evidence during Search |
| `AML_LLM_REQUIRED` | `false` | fail Add/Search when an enabled LLM step fails |
| `AML_LLM_RERANK_CANDIDATES` | `50` | maximum candidates sent to the Search reranker |

The dense channel currently uses `text-embedding-3-small`. Optional `gpt-4o-mini` steps only enrich
or rerank retrieval; Search still returns original evidence. The platform remains responsible for
answer generation and scoring.

## Build and run

Build the API-only image from the repository root:

```bash
docker build --target api -t memory_engine-aml:dev .
docker run --rm -p 6030:6030 \
  -e MEMORY_ENGINE_ROLE=api \
  -e MYSQL_HOST=... \
  -e MYSQL_USER=... \
  -e MYSQL_PASSWORD=... \
  -e MYSQL_DATABASE=... \
  -e MONGODB_DSN=... \
  -e MONGODB_DATABASE=... \
  -e QDRANT_URL=... \
  -e OPENAI_API_KEY=... \
  memory_engine-aml:dev
```

Run the local contract smoke test:

```bash
cd backend
AML_BASE_URL=http://127.0.0.1:6030 \
AML_MEMORY_SYSTEM_KEY='replace-me' \
.venv/bin/python scripts/aml_smoke.py
```

## Evaluation data availability

The official AML repository publishes evaluation contracts but explicitly excludes benchmark
corpora, held-out questions, gold answers, annotations, participant outputs, and run artifacts.
Consequently, a previous formal AML run cannot be reproduced locally from public AML files.

For development-only retrieval checks, download upstream public datasets under their own licenses,
for example LoCoMo and LongMemEval. Keep those files outside this repository and do not use hidden
answers, AML traces, or leaderboard outputs to tune retrieval behavior.

LoCoMo lexical-channel diagnostic:

```bash
curl -L https://raw.githubusercontent.com/snap-research/locomo/main/data/locomo10.json \
  -o /tmp/aml-locomo10.json
cd backend
.venv/bin/python scripts/eval_aml_locomo_retrieval.py /tmp/aml-locomo10.json
```

This reports evidence retrieval recall rather than AML answer accuracy. It is useful for regression
testing, but it is not comparable to an official AML Full score.

For deployed retrieval experiments, build an external-data shadow manifest and run the AML-shaped
remote evaluator. The builder currently supports public LoCoMo and LongMemEval-S formats:

```bash
cd backend
.venv/bin/python scripts/build_aml_shadow_suite.py \
  locomo /tmp/aml-locomo10.json /tmp/aml-shadow-locomo.json

AML_BASE_URL=https://memory.example.com \
AML_MEMORY_SYSTEM_KEY='replace-me' \
.venv/bin/python scripts/eval_aml_shadow_remote.py \
  /tmp/aml-shadow-locomo.json \
  --concurrency 4 \
  --output-json /tmp/aml-shadow-locomo-report.json
```

The shadow runner mirrors the public AML envelope, deterministic 20-message/2,000-word chunk
boundaries, `top_k=100`, isolation, cleanup, retry behavior, and capability-level retrieval
diagnostics. It is not an official AML score. Keep generated manifests and reports out of Git and
follow each upstream dataset license.

Generate and run the small repository-owned capability suite before longer public-data runs:

```bash
cd backend
.venv/bin/python scripts/generate_aml_capability_suite.py \
  /tmp/aml-capability-suite.json

AML_BASE_URL=https://memory.example.com \
AML_MEMORY_SYSTEM_KEY='replace-me' \
.venv/bin/python scripts/eval_aml_shadow_remote.py \
  /tmp/aml-capability-suite.json \
  --concurrency 4 \
  --output-json /tmp/aml-capability-report.json
```

Besides retrieval metrics, this suite reports current-versus-stale evidence conflicts and negative
query empty-result behavior. It is a deterministic regression gate, not a substitute for public
benchmark coverage or the official AML evaluator.

## Data retention

Evaluation content and derived indexes are only for the active evaluation. Do not use them for
training, product analytics, or dataset reconstruction. Delete run partitions with `/aml/clear`
and remove all remaining evaluation data within 30 days of the run.
