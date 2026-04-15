---
status: partial
phase: 04-normalizer-storage
source: [04-VERIFICATION.md]
started: 2026-04-15T00:00:00Z
updated: 2026-04-15T00:00:00Z
---

## Current Test

[awaiting human testing]

## Tests

### 1. PostgreSQL DB write — token_count, tldr, dedup_fingerprint populated
expected: After running a paper through the full pipeline (arXiv → parse → normalize), a `SELECT content->'token_count', content->'tldr', content->'dedup_fingerprint' FROM papers WHERE arxiv_id=...` returns non-null values for all three fields.
result: [pending]

### 2. IdMap cross-source resolution — cited paper linked via target_paper_id
expected: When a cited paper's arxiv_id is already in the `papers` table, the `paper_citations.target_paper_id` FK is populated (not null) rather than left as NULL; confirmed by checking `SELECT target_paper_id FROM paper_citations WHERE source_paper_id=... LIMIT 5`.
result: [pending]

## Summary

total: 2
passed: 0
issues: 0
pending: 2
skipped: 0
blocked: 0

## Gaps
