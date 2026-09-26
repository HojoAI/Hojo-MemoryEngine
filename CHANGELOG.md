# Changelog

## 0.6.0 — 2026-09-26

- Add V2 atomic claims with source meeting provenance, revision history, conflict handling, policy filtering, expiring bundles, and retrieval traces.
- Improve cross-session retrieval with lexical and vector recall, query facets, temporal and aggregation handling, and evidence diversity.
- Add the Agent Memory Leaderboard Add/Search/Clear evidence adapter and regression tools.
- Expose V2 clients in the Python and Java SDKs.
- Add a review-gated Recursive Self-Improvement workflow for candidate comparison, conflict review, versioned rule updates, and repeatable evaluation.
- Keep V1-to-V2 dual write and detailed value logging disabled by default. Apply `backend/migrations/mysql/005_memory_claim_v2.sql` before enabling dual write.
