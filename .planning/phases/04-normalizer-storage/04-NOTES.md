# Phase 4 Pre-Planning Notes

**Source:** Captured during Phase 3 discuss-phase (2026-04-15)

These are mandatory constraints the Phase 4 planner must carry in from Phase 3 decisions.
Run `/gsd:discuss-phase 4` — these notes will be referenced as prior context.

## Critical: Section Hierarchy Reconstruction

MinerU JSON and GROBID TEI XML output **flat section lists** — section 3 and section 3.1
appear as siblings, not parent/child. The Phase 4 normalizer MUST reconstruct the hierarchy:

- Parse `sec_num` strings ("3", "3.1", "3.1.2") to infer the tree structure.
- Nest child sections under their parent before writing to the `papers.content` JSONB blob.
- Verify whether s2orc-doc2json (TEX2JSON/JATS2JSON) already preserves hierarchy or also needs reconstruction.

## Critical: Unified Output Schema

All three parser raw outputs must normalize to the same PaperJSON schema:
- s2orc-doc2json → S2ORC JSON format
- MinerU → `magic-pdf` JSON format
- GROBID → TEI XML format

The normalizer is the single point that handles all three. Do NOT attempt partial normalization in Phase 3 tasks.

## Parallelization Note

The 10k batch run will use Celery group / potential PySpark for parsing throughput.
The normalizer should be designed to handle batched upserts efficiently (not one DB round-trip per paper).
Consider `executemany` / bulk upsert patterns for the PostgreSQL write path.
