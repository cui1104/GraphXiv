---
phase: 01-foundation
plan: 01
subsystem: infra
tags: [docker-compose, postgresql, pgvector, redis, celery, alembic, pydantic-settings, sqlalchemy]

# Dependency graph
requires: []
provides:
  - docker-compose.yml with 5 services (postgres pgvector:pg16, redis 7-alpine, grobid 0.8.0, celery worker with NVIDIA GPU, flower)
  - pyproject.toml with all pinned Phase 1 dependencies
  - app/config.py pydantic-settings BaseSettings
  - app/db.py SQLAlchemy engine + SessionLocal
  - app/models.py ORM models for all 5 tables
  - app/celery_app.py with fast/slow queues and task routes
  - stub task modules (ingest, parse, normalize)
  - alembic.ini + alembic/env.py reading DATABASE_URL from .env
  - tests/conftest.py with db_engine, db_session, redis_client fixtures
  - tests/test_infra.py covering INFRA-01 through INFRA-06 (19 test functions)
affects: [01-02, 01-03, 02-ingestion, 03-parser, 04-normalizer, 05-api]

# Tech tracking
tech-stack:
  added:
    - sqlalchemy==2.0.49
    - alembic==1.18.4
    - celery[redis]==5.4.0
    - redis==7.4.0
    - psycopg2-binary==2.9.11
    - pgvector==0.4.2
    - pydantic-settings==2.13.1
    - flower==2.0.1
  patterns:
    - pydantic-settings BaseSettings with lru_cache for typed .env config
    - SQLAlchemy 2.0 Mapped[T] + mapped_column() declarative ORM
    - Celery task_queues + task_routes for fast/slow queue separation
    - Docker Compose service_healthy depends_on for startup ordering
    - pyproject.toml [project] format (not Poetry) for pip-friendly packaging

key-files:
  created:
    - docker-compose.yml
    - Dockerfile
    - .env.example
    - pyproject.toml
    - alembic.ini
    - alembic/env.py
    - app/config.py
    - app/db.py
    - app/models.py
    - app/celery_app.py
    - app/tasks/ingest.py
    - app/tasks/parse.py
    - app/tasks/normalize.py
    - tests/conftest.py
    - tests/test_infra.py
  modified:
    - .planning/STATE.md

key-decisions:
  - "pyproject.toml [project] format (not Poetry) — simpler, no lock file format difference, Docker-friendly"
  - "app/models.py included in Plan 01 (not Plan 02) to allow alembic/env.py to reference Base.metadata"
  - "Celery stub tasks created in Plan 01 to satisfy test_infra.py TestCeleryQueues tests"
  - "Worker container uses runtime: nvidia for GPU-accelerated MinerU PDF parsing in Phase 3"

patterns-established:
  - "Pattern: Celery tasks use per-task time_limit/soft_time_limit in decorator, not per-queue"
  - "Pattern: Alembic env.py uses load_dotenv() + os.environ.get() for DATABASE_URL injection"
  - "Pattern: GIN tsvector index written as raw op.execute() SQL (avoids Alembic autogenerate false-positives)"

requirements-completed: [INFRA-01]

# Metrics
duration: 4min
completed: 2026-04-14
---

# Phase 01 Plan 01: Docker Compose Infrastructure and Project Scaffold Summary

**Docker Compose with 5 services (pgvector:pg16, redis:7-alpine, grobid:0.8.0, nvidia worker, flower), full Python project scaffold with pinned deps, SQLAlchemy ORM models for all 5 tables, Celery fast/slow queue config, and 19 Wave 0 test stubs covering INFRA-01 through INFRA-06**

## Performance

- **Duration:** 4 min
- **Started:** 2026-04-14T16:35:07Z
- **Completed:** 2026-04-14T16:38:43Z
- **Tasks:** 2
- **Files modified:** 19

## Accomplishments

- Full Docker Compose service definitions: postgres (pgvector/pgvector:pg16), redis (redis:7-alpine), grobid (grobid/grobid:0.8.0 with 8g RAM + 60s start_period), celery worker (NVIDIA GPU runtime), flower — all with health checks and service_healthy depends_on
- Complete Python project scaffold: pyproject.toml with all 8 pinned deps, pydantic-settings config module, SQLAlchemy engine + session factory, ORM models for all 5 Phase 1 tables (papers with vector(768) embeddings, paper_sources, id_map, crawl_state, paper_citations), Celery app with fast/slow queues and stub tasks
- Wave 0 test stubs: 19 test functions in test_infra.py covering TestSchema (7), TestPgvector (4), TestAlembic (1), TestRedis (2), TestCeleryQueues (5) — ready for Plans 02 and 03 to make pass

## Task Commits

Each task was committed atomically:

1. **Task 1: Project scaffold, Docker Compose, and Dockerfile** - `772e981` (feat)
2. **Task 2: Wave 0 test stubs (conftest.py and test_infra.py)** - `10dcbae` (feat)

**Plan metadata:** _(to be set after final commit)_

## Files Created/Modified

- `docker-compose.yml` - 5-service Docker Compose: postgres/redis/grobid/worker/flower with health checks
- `Dockerfile` - python:3.11-slim with celery worker CMD
- `.env.example` - all required env vars with placeholder values
- `.env` - copy of .env.example (gitignored)
- `pyproject.toml` - [project] format with 8 pinned deps + pytest dev deps
- `alembic.ini` - standard Alembic config with empty sqlalchemy.url
- `alembic/env.py` - reads DATABASE_URL from .env, imports app.models.Base
- `app/__init__.py` - empty package marker
- `app/config.py` - pydantic-settings BaseSettings + get_settings() lru_cache
- `app/db.py` - SQLAlchemy create_engine + SessionLocal
- `app/models.py` - ORM models: Paper, PaperSource, IdMap, CrawlState, PaperCitation
- `app/celery_app.py` - Celery app with fast/slow queues, task_routes, worker_prefetch_multiplier=1
- `app/tasks/ingest.py` - stub ingest_paper task (time_limit=60, fast queue)
- `app/tasks/parse.py` - stub parse tasks (parse_latex, parse_jats fast; parse_pdf_mineru, parse_pdf_grobid slow, time_limit=300)
- `app/tasks/normalize.py` - stub normalize_paper task
- `app/api/__init__.py` - empty package marker (Phase 5 fills)
- `app/crawler/__init__.py` - empty package marker (Phase 2 fills)
- `tests/conftest.py` - db_engine, db_session, redis_client session-scoped fixtures
- `tests/test_infra.py` - 19 Wave 0 test stubs for INFRA-01 through INFRA-06

## Decisions Made

- **pyproject.toml [project] format** — not Poetry. Simpler, Docker-friendly, no lock file format concerns.
- **app/models.py in Plan 01** — alembic/env.py needs to import Base; creating models upfront avoids circular dependency issues in Plan 02.
- **Celery stub tasks in Plan 01** — TestCeleryQueues tests reference `app.tasks.ingest.ingest_paper` and `app.tasks.parse.parse_pdf_mineru` directly; stubs must exist for tests to parse/import.
- **worker_prefetch_multiplier=1** — prevents GPU task starvation on the slow queue (Pitfall 4 from RESEARCH.md).

## Deviations from Plan

None - plan executed exactly as written. One minor addition: `app/models.py` was created in this plan (not listed in plan's `files_modified` but required by alembic/env.py). This is consistent with the plan's context (CONTEXT.md lists models.py in the project layout) and does not change any plan specifications.

## Issues Encountered

None — all verification checks passed on first run.

## User Setup Required

None - no external service configuration required for scaffold phase. When running `docker compose up`, the NVIDIA Container Toolkit must be installed on the host for the worker service (`runtime: nvidia`). This is documented in RESEARCH.md Pitfall 1.

## Known Stubs

The following stub tasks return immediately and will be replaced in later phases:

- `app/tasks/ingest.py::ingest_paper` — Phase 2 fills with actual arXiv/PMC ingestion logic
- `app/tasks/parse.py::parse_latex` — Phase 3 fills with LaTeXML/s2orc parsing
- `app/tasks/parse.py::parse_jats` — Phase 3 fills with JATS XML parsing
- `app/tasks/parse.py::parse_pdf_mineru` — Phase 3 fills with MinerU GPU parsing
- `app/tasks/parse.py::parse_pdf_grobid` — Phase 3 fills with GROBID reference extraction
- `app/tasks/normalize.py::normalize_paper` — Phase 4 fills with deepxiv_sdk JSON normalization

These stubs are **intentional** — they exist to satisfy TestCeleryQueues tests (time_limit assertions) while Plans 02-04 fill in the actual implementation.

## Next Phase Readiness

- Plan 02 (DB schema + Alembic migration) can proceed: models.py ORM is defined, alembic/env.py is configured, test stubs are in place
- Plan 03 (Celery skeleton) can proceed: celery_app.py is configured, task stub files exist with correct names, queues and routes are defined
- Plans 02 and 03 can run in parallel — no file conflicts
- `docker compose up` will bring all 5 services healthy once NVIDIA Container Toolkit is installed on host

---
*Phase: 01-foundation*
*Completed: 2026-04-14*
