---
gsd_state_version: 1.0
milestone: v1.0
milestone_name: milestone
status: unknown
last_updated: "2026-04-15T17:33:36.832Z"
progress:
  total_phases: 7
  completed_phases: 1
  total_plans: 7
  completed_plans: 6
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-04-13)

**Core value:** Given an arXiv ID or PMC ID, return clean structured JSON (sections, tables, figures, metadata) in under a second — by doing all parsing work ahead of time via a continuous ingestion pipeline.
**Current focus:** Phase 02 — ingestion

## Current Status

**Milestone:** v1 — End-to-End Platform
**Active Phase:** Phase 02 — Ingestion (3/4 plans complete)
**Last Action:** Completed 02-03 — PMC OAI-PMH crawler with sickle, DL keyword filter, token checkpointing (2026-04-15)

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

## Performance Metrics

| Phase | Plan | Duration | Tasks | Files |
|-------|------|----------|-------|-------|
| 01    | 01   | 4min     | 2     | 19    |
| Phase 01 P03 | 8min | 1 tasks | 4 files |
| Phase 01 P02 | 8min | 2 tasks | 2 files |
| Phase 02 P03 | 2min | 2 tasks | 2 files |
| Phase 02 P02 | 8min | 2 tasks | 4 files |

## Performance Metrics (continued)

| Phase | Plan | Duration | Tasks | Files |
|-------|------|----------|-------|-------|
| 02    | 01   | 3min     | 2     | 6     |

## Next Step

Execute 02-04-PLAN.md — remaining ingestion work (bulk harvest orchestration or Celery task wiring).
