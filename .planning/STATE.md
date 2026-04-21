---
gsd_state_version: 1.0
milestone: v1.0
milestone_name: milestone
status: unknown
stopped_at: Completed 08-03-PLAN.md (LLM judge + FINDINGS.md — Phase 8 Wave 2)
last_updated: "2026-04-21T21:20:00.000Z"
progress:
  total_phases: 8
  completed_phases: 7
  total_plans: 27
  completed_plans: 26
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-04-13)

**Core value:** Given an arXiv ID or PMC ID, return clean structured JSON (sections, tables, figures, metadata) in under a second — by doing all parsing work ahead of time via a continuous ingestion pipeline.
**Current focus:** Phase 07 — benchmark

## Current Status

**Milestone:** v1 — End-to-End Platform
**Active Phase:** Phase 07 — Benchmark (2/4 plans complete — 07-02.5 inserted)
**Last Action:** Phase 8 Wave 2 complete. Paired LLM-judge scoring over 30 questions × 2 conditions yielded with_tools >> title_only at p<1e-7 on all four rubric dimensions (answer_correctness, faithfulness, citation_coverage, completeness); judge↔deterministic citation_coverage agreement Spearman ρ=0.992, exact-bucket match 93.3%. Findings in eval/FINDINGS.md; scores gitignored at eval/results/run_20260421_201456/scores.jsonl. (2026-04-21)

## Phase Progress

| Phase | Status | Plans | Notes |
|-------|--------|-------|-------|
| 1 - Foundation | ○ Pending | 3 | Infrastructure, DB schema, Celery skeleton |
| 2 - Ingestion | ○ Pending | 4 | arXiv + PMC crawlers, ~10k DL papers |
| 3 - Parser Layer | ○ Pending | 4 | TEX2JSON, JATS2JSON, MinerU, GROBID |
| 4 - Normalizer + Storage | ○ Pending | 3 | deepxiv_sdk JSON contract, upsert |
| 5 - REST API | ✓ Complete | 3 | FastAPI, Redis caching, all 9 endpoints |
| 6 - SDK Fork + Verification | ○ Pending | 3 | Fork deepxiv_sdk, test suite, new feature |
| 7 - Benchmark | ↻ In Progress | 4 | 07-01 ✓, 07-02 ✓ (v1 CSV), 07-02.5 pending (metric overhaul), 07-03 pending (analysis) |
| 8 - Agent Evaluation | ✓ Complete | 3 | 08-01 ✓ (eval/ scaffold + 30-q set), 08-02 ✓ (paired with_tools/title_only runner, D-27), 08-03 ✓ (LLM judge + FINDINGS.md; with_tools wins all 4 dims at p<1e-7; judge↔deterministic ρ=0.992) |

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
- All route handlers converted to async def; sync SQLAlchemy calls wrapped in asyncio.to_thread() — no asyncpg introduced (05-03)
- _invalidate_cache in normalize_paper uses sync redis.Redis (Celery safe) with SCAN cursor loop, wrapped in try/except (05-03)
- MockRedis autouse pytest fixture injects async dict store for all API tests — no live Redis needed in CI (05-03)
- SDK fork version=0.2.0.dev0 (PEP 440 compliant; 0.2.0-local rejected by setuptools) (06-01)
- raw() and json() aliased to full() to preserve upstream API surface while pointing at new /arxiv/{id}/full path-param endpoint (06-01)
- section() does client-side filter on /sections response (no per-section route in local backend) (06-01)
- search() uses 'size' kwarg mapped to 'limit' query param — integration test fixtures use size=10 not limit=10 (06-02)
- test_mcp_server.py gains pytest.importorskip("mcp") — skips gracefully when mcp package absent (06-02)
- test_trending.py marked skip at module level — trending/social_impact are upstream-only stubs raising NotImplementedError in fork (06-02)
- get_tools_definition() added as instance method on ToolExecutor delegating to module-level function — test API required te.get_tools_definition(); ReAct graph imports standalone (06-03)
- test_agent.py force-tracked via git add -f — upstream SDK .gitignore explicitly excludes it; project tests must be version-controlled (06-03)
- select_sample.py --dry-run check moved before SessionLocal() to avoid psycopg2.OperationalError when Postgres not running locally (07-01)
- is_two_column uses lazy pymupdf import inside function body per project Pitfall 1; no top-level ML imports in any benchmark script (07-01)
- D-05 column classification: PyMuPDF signal alone sufficient for two-column flag (parser may have recovered despite layout) (07-01)
- eval/ package scaffolded mirroring benchmark/ layout per D-01; eval extras group (openai, scipy, matplotlib, pandas, notebook) appended to pyproject optional-dependencies (08-01)
- eval/build_questions.py ships propose/promote/auto-promote-all (D-05) PLUS a new --deterministic-fill offline fallback that unblocks 08-02/08-03 when OPENAI_API_KEY is unset or docker api is down (08-01)
- eval/questions.json generated via --deterministic-fill: 30 questions, stratified 10/10/10 per D-03, all arxiv_ids drawn from benchmark/sample.json so corpus membership (D-07) holds by construction (08-01)
- 08-01 Wave 0 regenerated with REAL citation graph (2026-04-21): ingested 150 seeds + cited targets via eval/ingest_for_eval.py (host-mode GROBID), enriched paper_citations with arxiv_id regex over raw_text (unlocks 55 seeds w/ >=1 in-corpus cite, 16 w/ >=3), and redrafted eval/questions.json with gpt-4o-mini --propose --auto-promote-all: 30 questions across 10 seeds, mean 3.8 gold cites (08-01)
- D-20 (2026-04-21): gold_cited_arxiv_ids require only in_corpus=True + resolvable arxiv_id, not populated sections — 105k-corpus is metadata-mostly; agent uses reader.head() head-level metadata (08-01)

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
| Phase 05 P03 | 8min | 2 tasks | 5 files |
| Phase 06 P01 | 5min | 2 tasks | 7 files |
| Phase 06 P02 | 3min | 2 tasks | 4 files |
| Phase 06 P03 | 5min | 2 tasks | 4 files |
| Phase 07 P01 | 4min | 3 tasks | 12 files |
| Phase 08 P01 | 4min | 3 tasks | 9 files |
| Phase 08 P01 | 4min | 3 tasks | 9 files |

## Performance Metrics (continued)

| Phase | Plan | Duration | Tasks | Files |
|-------|------|----------|-------|-------|
| 02    | 01   | 3min     | 2     | 6     |
| 02    | 04   | ~2h      | 2     | 2     |
| 03    | 01   | 3min     | 3     | 7     |

## Next Step

**Execute Plan 07-02.5 — Metric & Ground-Truth Overhaul** (`.planning/phases/07-benchmark/07-02.5-PLAN.md`).

Rationale: Plan 07-02 produced a 600-row CSV on fair GPU hardware, but the metric design (precision-only heading match, no hierarchy scoring, no figure/formula/ref counts) systematically rewards GROBID and hides the router's and DL parsers' real strengths. 07-02.5 adds:

1. heading precision/recall/F1 (replaces precision-only match rate)
2. hierarchy_f1 via dot-count depth builder in router (the router's actual differentiator)
3. body_token_count, figure_count, formula_count, reference_count (content-richness metrics)
4. GT schema v2 (per-heading sec_num + structural counts) — requires re-extracting 150 GT files (~$15 Opus)
5. Re-run all 4 conditions on RunPod RTX 4090 against v2 schema

Blocks 07-03 (analyze_results + FINDINGS.md + notebook). Archive current CSV as `benchmark.v1.csv` before re-run.

## Session

Last updated: 2026-04-21
Stopped at: Completed 08-01 Wave 0 regeneration (real citation graph; eval/questions.json = 30 q, 10/10/10, mean 3.8 gold cites)
