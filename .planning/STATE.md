---
gsd_state_version: 1.0
milestone: v1.0
milestone_name: milestone
status: unknown
last_updated: "2026-04-16T01:33:03.455Z"
progress:
  total_phases: 7
  completed_phases: 4
  total_plans: 16
  completed_plans: 15
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-04-13)

**Core value:** Given an arXiv ID or PMC ID, return clean structured JSON (sections, tables, figures, metadata) in under a second — by doing all parsing work ahead of time via a continuous ingestion pipeline.
**Current focus:** Phase 05 — rest-api

## Current Status

**Milestone:** v1 — End-to-End Platform
**Active Phase:** Phase 05 — REST API (2/3 plans complete)
**Last Action:** Completed 05-02 — All 10 endpoint handlers with real DB queries: arXiv ID resolution (version stripping + id_map fallback), citation graph queries (references/cited_by/related), hybrid BM25/pgvector search, _write_embedding in normalize_paper, 9/9 non-integration tests passing (2026-04-16)

## Phase Progress

| Phase | Status | Plans | Notes |
|-------|--------|-------|-------|
| 1 - Foundation | ○ Pending | 3 | Infrastructure, DB schema, Celery skeleton |
| 2 - Ingestion | ○ Pending | 4 | arXiv + PMC crawlers, ~10k DL papers |
| 3 - Parser Layer | ○ Pending | 4 | TEX2JSON, JATS2JSON, MinerU, GROBID |
| 4 - Normalizer + Storage | ○ Pending | 3 | deepxiv_sdk JSON contract, upsert |
| 5 - REST API | ○ Pending | 3 | FastAPI, Redis caching, all 7 endpoints |
| 6 - SDK Fork + Verification | ○ Pending | 3 | Fork deepxiv_sdk, test suite, new feature |
| 7 - Benchmark | ○ Pending | 3 | MinerU vs GROBID vs Docling |

## Key Decisions Made

- Corpus: ~10,000 deep learning papers (arXiv cs.LG/AI/CV/CL/stat.ML + PMC DL subset)
- Parser routing: LaTeX → s2orc-doc2json, JATS → s2orc-doc2json, PDF → MinerU + GROBID refs
- Storage: PostgreSQL 16 + JSONB, hybrid schema (structured columns + jsonb payload)
- Job queue: Celery 5.4 + Redis 7 (fast queue for LaTeX/JATS, slow queue for ML PDF parsing)
- API: FastAPI, must exactly match deepxiv_sdk field names
- SDK: Fork deepxiv_sdk, verify all existing features work, add at least one new capability
- pyproject.toml [project] format (not Poetry) — simpler, no lock file format difference, Docker-friendly (01-01)
- app/models.py created in Plan 01 to allow alembic/env.py to reference Base.metadata before Plan 02 (01-01)
- worker_prefetch_multiplier=1 to prevent GPU task starvation on slow queue (01-01)
- shared_task decorator for all Celery tasks (not celery_app.task) to avoid circular imports and enable auto-registration via include list (01-03)
- ingest_paper uses paper_id (not arxiv_id) for source-agnostic pipeline; normalize_paper takes parse_source param for Phase 4 routing (01-03)
- PaperSource/IdMap/CrawlState/PaperCitation use Integer autoincrement PKs per schema spec (01-02)
- SQLAlchemy 2.0.49 removed TIMESTAMPTZ alias; use TIMESTAMP(timezone=True) instead (01-02)
- Hand-written Alembic migration avoids GIN index autogenerate false-positive bug alembic#1390 (01-02)
- mock_db_session uses raw SQL DDL (not Base.metadata.create_all) because Paper model contains JSONB/Vector types incompatible with SQLite (02-01)
- ARXIV_OAI_BASE uses new March 2025 endpoint oaipmh.arxiv.org/oai; ARXIV_SETS uses colon format cs:cs:LG (02-01)
- crawl_state upsert uses pg_insert().on_conflict_do_update(index_elements=["source"]) (02-01)
- Use pmc_fm metadataPrefix for PMC OAI harvest (front-matter only, avoids token timeout during slow full-JATS iteration) (02-03)
- Two-phase PMC crawler: bulk ID collection (harvest_pmc_ids) then per-record DL keyword filter + insert (process_pmc_record) (02-03)
- Lazy import of pmc_oai.harvest_pmc inside ingest_paper function body avoids ImportError at module load time, allowing parallel development of 02-02 and 02-03 (02-02)
- lxml {*} wildcard namespace matching in _parse_arxiv_records is robust to both OAI-namespace-qualified and bare arXivRaw child elements (02-02)
- import app.celery_app at top of run_harvest.py to force broker initialization before any task imports — without this Redis broker raises ImportError on task dispatch (02-04)
- UNIQUE constraint on crawl_state.source applied via migration 0002; full arXiv cs:LG harvest yielded 105,300 papers since 2024-01-01 (far exceeds 10k target) (02-04)
- parse_helpers.py is shared helper module consumed by all Phase 3 tasks (03-01); not inline per-task
- D-01 arXiv ID stem matching strips version suffix (2401.12345v2 -> 2401.12345) before filename comparison (03-01)
- PyMuPDF added in 03-01 (not 03-03) because D-03 table-count heuristic needed by parse_latex (03-01)
- process_tex_stream lazily imported inside task body to prevent ImportError at worker startup (03-01)
- process_jats_stream lazily imported inside parse_jats task body; _strip_jats_doctype from parse_helpers prevents lxml DTD fetch hangs; D-04 cascade queries pmc_pdf/arxiv_pdf/pdf source_types (03-02)
- All magic-pdf imports are lazy inside parse_pdf_mineru body to prevent ImportError on fast workers (03-03)
- text_level_broken=True flag stored in content dict to warn Phase 4 that OSS MinerU always returns text_level=1 with no heading hierarchy (03-03)
- GROBID non-blocking (D-07): extract_references returns [] on any exception -- never fails parse chain (03-04)
- parse_pdf_grobid sets parse_source=pdf_grobid only when ps.parse_status==cascade_to_pdf_grobid (D-03 cascade path is PRIMARY parser, not enrichment) (03-04)
- Router does NOT have D-03 branch -- parse_latex handles it internally; app/parsers/ package established for parser HTTP client modules (03-04)
- tiktoken>=0.7.0 (not pinned to 0.12.0) for broad compatibility; cl100k_base pre-cached in Docker layer (04-01)
- extract_fulltext timeout=60 (vs 30 for extract_references) because processFulltextDocument processes entire PDF document (04-01)
- parse_pdf_grobid branches on cascade_to_pdf_grobid for primary (extract_fulltext -> grobid_sections + grobid_citations) vs secondary (extract_references -> grobid_citations only) mode (04-01)
- _normalize_s2orc signature takes (raw, parse_quality=None) not (raw, paper) to match pre-written test stubs from 04-01; pure _compute_* helpers alongside in-place _add_* wrappers for test/task interface separation (04-02)
- normalize_paper reads actual_parse_source from paper.parse_source (DB) not from router argument — handles D-03 cascade staleness (Pitfall 1) (04-02)
- Lazy embedding model: app.state.embedding_model = None at startup, loaded on first /search to avoid 30s startup delay (05-01)
- BriefResponse = HeadResponse alias (not subclass) — schema identical, distinction is routing-only (05-01)
- Sync def route handlers for all DB-touching endpoints — FastAPI threadpool handles sync SQLAlchemy safely (05-01)
- exclude_none=True NOT used on model_config — deepxiv_sdk expects tldr key present as null, not omitted (05-01)
- _paper_to_head imported from arxiv.py into pmc.py — shared helper, single source of truth (05-02)
- vec_str built as Python string [v1,v2,...] for pgvector CAST(:vec AS vector) — avoids psycopg2 array binding issues (05-02)
- Hybrid/vector search falls back to BM25 when no embeddings in DB — graceful degradation without failure (05-02)

## Performance Metrics

| Phase | Plan | Duration | Tasks | Files |
|-------|------|----------|-------|-------|
| 01    | 01   | 4min     | 2     | 19    |
| Phase 01 P03 | 8min | 1 tasks | 4 files |
| Phase 01 P02 | 8min | 2 tasks | 2 files |
| Phase 02 P03 | 2min | 2 tasks | 2 files |
| Phase 02 P02 | 8min | 2 tasks | 4 files |
| Phase 03 P02 | 5min | 1 tasks | 2 files |
| Phase 03 P03 | 2min | 2 tasks | 4 files |
| Phase 03 P04 | 2min | 2 tasks | 6 files |
| Phase 04 P01 | 15 | 2 tasks | 6 files |
| Phase 04 P02 | 15 | 2 tasks | 2 files |
| Phase 05 P01 | 3 | 2 tasks | 13 files |
| Phase 05 P02 | 10 | 2 tasks | 5 files |

## Performance Metrics (continued)

| Phase | Plan | Duration | Tasks | Files |
|-------|------|----------|-------|-------|
| 02    | 01   | 3min     | 2     | 6     |
| 02    | 04   | ~2h      | 2     | 2     |
| 03    | 01   | 3min     | 3     | 7     |

## Next Step

Phase 05 Plan 02 complete. Execute Phase 05 Plan 03 — Redis cache-aside layer for all endpoints.
