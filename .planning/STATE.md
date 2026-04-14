---
gsd_state_version: 1.0
milestone: v1.0
milestone_name: milestone
status: in_progress
last_updated: "2026-04-14T16:39:00.000Z"
progress:
  total_phases: 7
  completed_phases: 0
  total_plans: 3
  completed_plans: 1
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-04-13)

**Core value:** Given an arXiv ID or PMC ID, return clean structured JSON (sections, tables, figures, metadata) in under a second — by doing all parsing work ahead of time via a continuous ingestion pipeline.
**Current focus:** Phase 01 — foundation (Plan 2 of 3 next)

## Current Status

**Milestone:** v1 — End-to-End Platform
**Active Phase:** Phase 01 — Foundation (1/3 plans complete)
**Last Action:** Completed 01-01 — Docker Compose infrastructure and project scaffold (2026-04-14)

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

## Performance Metrics

| Phase | Plan | Duration | Tasks | Files |
|-------|------|----------|-------|-------|
| 01    | 01   | 4min     | 2     | 19    |

## Next Step

Execute 01-02-PLAN.md — PostgreSQL schema Alembic migration and 01-03-PLAN.md — Celery skeleton (can run in parallel).
