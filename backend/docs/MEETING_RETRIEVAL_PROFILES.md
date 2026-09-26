# Meeting retrieval profiles (V2 P0)

`POST /api/v2/memory/retrieve` remains backward compatible. When `rule_name` is omitted,
the request's method, dimensions and limits are used exactly as before. When it is present,
MemoryEngine loads the latest implicit `retrieve_rule` with that name and makes the stored policy
authoritative for `method`, `required_dimensions`, `top_k`, `candidate_limit`, `max_tokens`
and `min_score`.

Meeting callers use the stable name format:

```text
meeting.<industry>.<module>.v1
```

Example profile creation:

```json
{
  "rule_name": "meeting.consumer-electronics.MeetingDetailedSummary.v1",
  "memory_field_name": null,
  "retrieve_method": "SEMANTIC",
  "rule_config_json": {
    "top_k": 3,
    "candidate_limit": 40,
    "max_tokens": 500,
    "min_score": 0.55,
    "max_increment_items": 2,
    "usage_mode": "explicit_history_comparison_only",
    "allowed_namespace_types": ["product_project"],
    "allowed_modules": ["MeetingDetailedSummary"],
    "allowed_scenarios": ["product_review"],
    "allowed_roles": ["consumer_electronics_pm"]
  }
}
```

Create it through `POST /api/v1/schema/retrieve/create`. Updating a policy creates a new
version through `POST /api/v1/schema/retrieve/update?rule_name=...`; Bundle responses expose
both `profile_id` and `profile_version`, so evaluation results can be tied to an immutable
policy version.

The four `allowed_*` arrays are optional and backward compatible. Once present, they are
server-owned hard boundaries: a caller cannot reuse a profile with another namespace type,
module, scenario, or role. Namespace values never accept wildcards.

`method=HYBRID` combines vector and lexical relevance before thresholding. Existing
`SEMANTIC` and `LLM` behavior remains unchanged; `LLM` continues to perform the authorized
rerank over its existing candidate scores.

Recommended initial values (do not enable the caller flag until these records exist):

| industry | module | method | top_k | max_tokens | min_score | max_increment_items | usage_mode |
|---|---|---:|---:|---:|---:|---:|---|
| executive | MeetingBasicInfo | LLM | 4 | 800 | 0.50 | 3 | reasoning_only_do_not_output_historical_fact |
| executive | MeetingDetailedSummary | SEMANTIC | 3 | 600 | 0.10 | 2 | explicit_history_comparison_only |
| executive | MeetingToDo | SEMANTIC | 3 | 400 | 0.10 | 2 | reference_only_do_not_create_todo |
| investment | MeetingBasicInfo | LLM | 4 | 800 | 0.50 | 3 | reasoning_only_do_not_output_historical_fact |
| investment | MeetingDetailedSummary | SEMANTIC | 3 | 600 | 0.10 | 2 | explicit_history_comparison_only |
| investment | MeetingToDo | SEMANTIC | 3 | 400 | 0.10 | 2 | reference_only_do_not_create_todo |
| consumer-electronics | MeetingBasicInfo | LLM | 4 | 800 | 0.50 | 3 | reasoning_only_do_not_output_historical_fact |
| consumer-electronics | MeetingDetailedSummary | SEMANTIC | 3 | 500 | 0.55 | 2 | explicit_history_comparison_only |
| consumer-electronics | MeetingToDo | SEMANTIC | 2 | 300 | 0.60 | 2 | reference_only_do_not_create_todo |

`current_context` is optional. When supplied, exact current-meeting duplicates and structured
same-key conflicts are removed before embedding/LLM reranking. The response reports their IDs
in `dropped_current_duplicate_claim_ids` and `conflicting_claim_ids`. Conflicts are deliberately
not injected in P0; a later version may expose a separately authorized conflict-report channel.

Every Bundle returns `policy_version`, `claim_schema_version`, `expires_at`, and a
`retrieval_trace`. The trace reports stage counters and normalized query terms for debugging.
It does not include rejected claim text. Standard server logs record counters;
opt-in diagnostics can additionally log claim IDs for a controlled evaluation.
