# Phase 1: Foundation - Research

**Researched:** 2026-04-13
**Domain:** Docker Compose infrastructure, PostgreSQL + pgvector, Celery + Redis, Alembic migrations
**Confidence:** HIGH

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- Single flat Python package named `app/` at project root
- Layout: docker-compose.yml, .env, .env.example, pyproject.toml, alembic.ini, alembic/versions/, app/{celery_app.py, config.py, db.py, models.py, tasks/, api/, crawler/}, tests/
- `.env` + `.env.example` pattern; docker-compose.yml reads from `.env` via `env_file: .env`
- Single compose file, no docker-compose.override.yml
- Services: PostgreSQL 16, Redis 7, Celery worker (fast + slow queues), Flower, GROBID 0.8
- All services always-on when `docker compose up` runs
- GROBID: always-on, health check polling `/api/isalive`, `mem_limit: 8g`
- NVIDIA GPU: Celery worker uses `runtime: nvidia` + `NVIDIA_VISIBLE_DEVICES=all`
- `./data/` bind mount into worker container
- PostgreSQL persisted via named volume `pgdata`; Redis via named volume `redisdata`
- papers table: structured columns listed in CONTEXT.md + `content JSONB`
- Five tables in initial migration: papers, paper_sources, id_map, crawl_state, paper_citations
- pgvector: `CREATE EXTENSION IF NOT EXISTS vector` in migration; `embeddings vector(768)` on papers
- Celery: `fast` queue (time_limit=60), `slow`/`gpu` queue (time_limit=300), max_retries=3
- Both queues in a single worker container

### Claude's Discretion
- Exact SQLAlchemy ORM model style (declarative vs dataclass)
- Health check intervals and retry counts in docker-compose.yml
- Celery concurrency setting per queue (can tune after Phase 2)
- Python dependency management tool (poetry vs pip + pyproject.toml)

### Deferred Ideas (OUT OF SCOPE)
- pgvector embeddings population — Phase 5 populates the `embeddings` column; column exists but NULL
- Celery beat / scheduled tasks — not needed in Phase 1
- Horizontal scaling / multiple workers — single worker container is sufficient
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| INFRA-01 | Docker Compose brings up all services (PostgreSQL 16, Redis 7, Celery workers, Flower, GROBID) with `docker compose up` | Docker Compose service definitions, health checks, depends_on, GPU runtime |
| INFRA-02 | PostgreSQL schema includes papers, paper_sources, id_map, crawl_state tables with correct indexes and UUID canonical IDs | SQLAlchemy 2.0 declarative ORM, Alembic migration, GIN index for FTS, UNIQUE constraints |
| INFRA-03 | Redis configured as both Celery broker and API response cache (TTL 3600s/300s) | redis-py 7.x, Celery broker_url, cache key patterns |
| INFRA-04 | Celery task skeleton with fast queue (60s limit) and gpu/slow queue (5min limit), max_retries=3 | Celery 5.x task_queues, task_routes, time_limit, soft_time_limit |
| INFRA-05 | Alembic migration tracks initial schema; schema rebuilds cleanly | Alembic 1.18, env.py setup, `alembic upgrade head` flow |
| INFRA-06 | paper_citations edge table + pgvector extension with embeddings column | pgvector 0.4 Python package, pgvector/pgvector:pg16 Docker image, CREATE EXTENSION vector |
</phase_requirements>

---

## Summary

Phase 1 is a pure infrastructure phase: stand up Docker Compose services and lock in the full database schema with Alembic. No data flows through any of these components in this phase — subsequent phases build on top of what is established here.

The standard Python stack for this type of project is well-established and all components are mature. The two non-trivial concerns are: (1) the NVIDIA GPU runtime configuration for the Celery worker container, which requires the host to have the NVIDIA Container Toolkit installed; and (2) Alembic's known limitation with functional indexes (tsvector GIN indexes) causing false-positive change detection on re-run — these indexes must be written as explicit DDL in the migration rather than relying on autogenerate.

The project's decision to pin PostgreSQL 16 means using `pgvector/pgvector:pg16` as the Docker image (which ships with pgvector pre-installed), avoiding a custom Dockerfile. GROBID 0.8 uses image `grobid/grobid:0.8.0` on port 8070 and requires a `start_period` of at least 60s in the health check since model loading is slow.

**Primary recommendation:** Use `pgvector/pgvector:pg16` for PostgreSQL (avoids custom Dockerfile), write the tsvector GIN index as raw SQL in the Alembic migration (avoids autogenerate false-positives), and start Celery with `celery multi` or a single `celery worker -Q fast,slow` command consuming both queues with per-task time limits.

---

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| pgvector/pgvector | pg16 (Docker image) | PostgreSQL 16 with pgvector extension pre-installed | Official image; avoids custom Dockerfile |
| redis (Docker) | 7-alpine | Redis broker + KV cache | Official image; minimal footprint |
| grobid/grobid | 0.8.0 | Reference extraction service | Only official GROBID image |
| mher/flower | latest (2.0.1) | Celery monitoring web UI | Only Flower Docker image; ships with Celery 5 compat |
| SQLAlchemy | 2.0.49 | ORM + database abstraction | Standard Python ORM; 2.x API is current |
| Alembic | 1.18.4 | Database migration management | Standard SQLAlchemy migration tool |
| celery | 5.4.0 | Distributed task queue | Locked to 5.4.0 per project decision |
| redis (Python) | 7.4.0 | Redis client for broker + cache | Standard redis-py; version 7 matches Celery needs |
| psycopg2-binary | 2.9.11 | PostgreSQL driver (sync) | Standard for SQLAlchemy sync sessions |
| pgvector (Python) | 0.4.2 | SQLAlchemy type for vector columns | Official pgvector Python integration |
| pydantic-settings | 2.13.1 | .env config loading with type validation | Standard for FastAPI-style apps |
| flower | 2.0.1 | Celery monitoring (pip package) | Required for mher/flower image |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| kombu | (Celery dep) | Queue transport abstraction | Used by Celery internally; Queue() comes from kombu |
| python-dotenv | (pydantic-settings dep) | .env file parsing | Pulled in by pydantic-settings automatically |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| pgvector/pgvector:pg16 | postgres:16 + custom Dockerfile | Custom Dockerfile adds complexity; official pgvector image is simpler |
| psycopg2-binary | psycopg[binary] 3.x | psycopg3 has async support but psycopg2 is more stable with SQLAlchemy sync |
| celery 5.4.0 (pinned) | celery 5.6.3 (latest) | 5.6.x is available; 5.4.0 is project decision — pin exactly |
| pydantic-settings | python-dotenv only | pydantic-settings gives type validation; cleaner for structured config |

**Installation:**
```bash
pip install \
  sqlalchemy==2.0.49 \
  alembic==1.18.4 \
  "celery[redis]==5.4.0" \
  redis==7.4.0 \
  psycopg2-binary==2.9.11 \
  pgvector==0.4.2 \
  pydantic-settings==2.13.1 \
  flower==2.0.1
```

**Version verification (confirmed 2026-04-13 via PyPI):**
- celery: 5.4.0 (pinned per project decision; latest is 5.6.3)
- sqlalchemy: 2.0.49
- alembic: 1.18.4
- redis: 7.4.0
- psycopg2-binary: 2.9.11
- pgvector: 0.4.2
- pydantic-settings: 2.13.1
- flower: 2.0.1

---

## Architecture Patterns

### Recommended Project Structure
```
project_root/
├── docker-compose.yml
├── .env                    # gitignored
├── .env.example            # committed, placeholder values
├── pyproject.toml          # dependencies + tool config
├── alembic.ini
├── alembic/
│   ├── env.py              # reads DATABASE_URL from .env
│   └── versions/
│       └── 0001_initial_schema.py
├── app/
│   ├── __init__.py
│   ├── celery_app.py       # Celery app + queue/route config
│   ├── config.py           # pydantic-settings BaseSettings
│   ├── db.py               # SQLAlchemy engine + Session factory
│   ├── models.py           # ORM models for all 5 tables
│   ├── tasks/
│   │   ├── __init__.py
│   │   ├── ingest.py       # stub tasks (Phase 2 fills)
│   │   ├── parse.py        # stub tasks (Phase 3 fills)
│   │   └── normalize.py    # stub tasks (Phase 4 fills)
│   ├── api/
│   │   └── __init__.py     # empty; Phase 5 fills
│   └── crawler/
│       └── __init__.py     # empty; Phase 2 fills
└── tests/
    ├── conftest.py
    └── test_infra.py       # INFRA-01 through INFRA-06 smoke tests
```

### Pattern 1: Docker Compose services with health checks and depends_on

**What:** All services define health checks; downstream services use `depends_on: condition: service_healthy` to prevent race conditions during startup.

**When to use:** Any multi-service Docker Compose where order of readiness matters (Celery and Flower must wait for Redis; worker must wait for PostgreSQL).

**Example:**
```yaml
# Source: Docker official docs + GROBID docs
services:
  postgres:
    image: pgvector/pgvector:pg16
    environment:
      POSTGRES_USER: ${POSTGRES_USER}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
      POSTGRES_DB: ${POSTGRES_DB}
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER}"]
      interval: 5s
      timeout: 5s
      retries: 5
      start_period: 10s

  redis:
    image: redis:7-alpine
    volumes:
      - redisdata:/data
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 3s
      retries: 5

  grobid:
    image: grobid/grobid:0.8.0
    mem_limit: 8g
    ports:
      - "8070:8070"
    healthcheck:
      test: ["CMD-SHELL", "curl -f http://localhost:8070/api/isalive || exit 1"]
      interval: 30s
      timeout: 10s
      retries: 5
      start_period: 60s   # GROBID model loading is slow

  worker:
    build: .
    runtime: nvidia
    environment:
      - NVIDIA_VISIBLE_DEVICES=all
    env_file: .env
    volumes:
      - ./data:/data
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
    command: >
      celery -A app.celery_app worker
        -Q fast,slow
        --concurrency=4
        --loglevel=info

  flower:
    image: mher/flower
    command: ["celery", "--broker=${REDIS_URL}", "flower", "--port=5555"]
    ports:
      - "5555:5555"
    depends_on:
      redis:
        condition: service_healthy

volumes:
  pgdata:
  redisdata:
```

### Pattern 2: pydantic-settings config with .env

**What:** `BaseSettings` subclass that reads `.env` file and environment variables with type validation. Single settings instance cached with `@lru_cache`.

**When to use:** Any Python app that needs typed configuration from environment variables.

**Example:**
```python
# Source: pydantic-settings docs (docs.pydantic.dev/latest/concepts/pydantic_settings/)
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    database_url: str
    redis_url: str
    postgres_user: str = "app"
    postgres_password: str
    postgres_db: str = "papers"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

@lru_cache
def get_settings() -> Settings:
    return Settings()
```

### Pattern 3: SQLAlchemy 2.0 Declarative ORM with mapped_column

**What:** Use `DeclarativeBase` + `Mapped[T]` + `mapped_column()` for type-safe ORM models. JSONB columns use `postgresql.JSONB`. Vector columns use `pgvector.sqlalchemy.Vector`.

**When to use:** All ORM models in this project.

**Example:**
```python
# Source: SQLAlchemy 2.0 docs + pgvector Python package
import uuid
from datetime import datetime
from sqlalchemy import String, Integer, Text, Index, func
from sqlalchemy.dialects.postgresql import UUID, JSONB, TIMESTAMPTZ
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from pgvector.sqlalchemy import Vector

class Base(DeclarativeBase):
    pass

class Paper(Base):
    __tablename__ = "papers"

    canonical_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    arxiv_id: Mapped[str | None] = mapped_column(Text, unique=True, nullable=True)
    pmc_id: Mapped[str | None] = mapped_column(Text, unique=True, nullable=True)
    doi: Mapped[str | None] = mapped_column(Text, nullable=True)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    abstract: Mapped[str | None] = mapped_column(Text, nullable=True)
    year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    venue: Mapped[str | None] = mapped_column(Text, nullable=True)
    parse_source: Mapped[str | None] = mapped_column(Text, nullable=True)
    parse_quality: Mapped[str | None] = mapped_column(Text, nullable=True)
    token_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tldr: Mapped[str | None] = mapped_column(Text, nullable=True)
    embeddings: Mapped[list | None] = mapped_column(Vector(768), nullable=True)
    content: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMPTZ, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMPTZ, server_default=func.now(), onupdate=func.now()
    )
```

### Pattern 4: Celery app with task_queues and task_routes

**What:** Define named queues with per-task time limits via task annotations. `task_routes` maps task module paths to queues. Time limits are set per-task in the decorator, not per-queue in the Queue() definition.

**When to use:** Any Celery setup requiring queue separation.

**Example:**
```python
# Source: Celery 5.4 docs (docs.celeryq.dev/en/v5.4.0)
from celery import Celery
from kombu import Queue

app = Celery("app")

app.conf.update(
    broker_url=settings.redis_url,
    result_backend=settings.redis_url,
    task_queues=(
        Queue("fast"),
        Queue("slow"),
    ),
    task_default_queue="fast",
    task_routes={
        "app.tasks.ingest.*": {"queue": "fast"},
        "app.tasks.parse.parse_latex": {"queue": "fast"},
        "app.tasks.parse.parse_pdf_mineru": {"queue": "slow"},
        "app.tasks.normalize.*": {"queue": "fast"},
    },
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    broker_connection_retry_on_startup=True,
    worker_prefetch_multiplier=1,   # important for slow GPU tasks
)
```

Per-task time limits via decorator:
```python
@app.task(bind=True, max_retries=3, time_limit=60, soft_time_limit=50)
def fast_task(self, paper_id: str):
    ...

@app.task(bind=True, max_retries=3, time_limit=300, soft_time_limit=270)
def slow_task(self, paper_id: str):
    ...
```

### Pattern 5: Alembic initial migration with raw SQL for functional indexes

**What:** Write the initial migration as `op.execute()` raw SQL for tsvector GIN indexes, since Alembic autogenerate has a known bug where it always detects GIN functional indexes as changed (issue #1390).

**When to use:** Any GIN index on a `to_tsvector()` expression.

**Example:**
```python
# Source: Alembic docs + known autogenerate limitation (github.com/sqlalchemy/alembic/issues/1390)
def upgrade() -> None:
    # Standard table creation via op.create_table(...)
    # ...

    # pgvector extension - must be before vector column
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # FTS index must be raw SQL — Alembic autogenerate false-positives on functional indexes
    op.execute("""
        CREATE INDEX idx_papers_fts
        ON papers
        USING GIN (to_tsvector('english', coalesce(title, '') || ' ' || coalesce(abstract, '')))
    """)
```

### Anti-Patterns to Avoid

- **Using `postgres:16` directly:** Requires custom Dockerfile to install pgvector. Use `pgvector/pgvector:pg16` instead.
- **`runtime: nvidia` without NVIDIA Container Toolkit on host:** Will fail silently or crash. Document the prerequisite. Use the `deploy.resources.reservations` syntax as an alternative for Docker Compose v3.8+.
- **Setting `time_limit` on the Queue() object:** Celery time limits are per-task, not per-queue. Setting it on Queue() has no effect. Set `time_limit` and `soft_time_limit` in the `@app.task()` decorator.
- **`worker_prefetch_multiplier` default (4) with slow GPU tasks:** The worker pre-fetches 4 tasks before completing one, starving other workers. Set to 1 for queues with GPU or long-running tasks.
- **Relying on Alembic autogenerate for GIN/tsvector indexes:** Known bug causes spurious migrations. Write these as `op.execute()` raw SQL and add them to `include_name` exclusions in `env.py` if needed.
- **Starting Flower before Redis is healthy:** Flower will crash and not restart. Use `depends_on: condition: service_healthy`.
- **Not setting `start_period` on GROBID health check:** GROBID loads ML models on startup and takes 30-60s. Without `start_period`, health checks fail immediately, and Docker marks the container unhealthy before it is ready.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| .env config loading | Custom os.environ parsing | pydantic-settings BaseSettings | Type validation, nested config, multiple env sources |
| Database migrations | Manual ALTER TABLE scripts | Alembic | Rollback, history, autogenerate from models |
| PostgreSQL driver | Raw socket code | psycopg2-binary | PGPASSWORD handling, SSL, connection pooling |
| Vector column type | Raw TEXT with JSON | pgvector Python package + vector(768) column | Native index support, cosine/L2/inner product operators |
| Celery task retry logic | try/except with sleep | `@app.task(max_retries=3, bind=True)` + `self.retry()` | Exponential backoff, jitter, max retry cap |
| Redis connection management | Raw socket client | redis-py with connection pool | Connection pooling, automatic reconnect |
| Service startup ordering | Sleep loops | Docker Compose `depends_on: condition: service_healthy` | Deterministic, no arbitrary sleep |

**Key insight:** All complex infrastructure concerns (connection pooling, schema versioning, task retry, config loading) have well-maintained Python libraries. Using them is not just convenience — they handle edge cases (SSL, connection drops, partial failures) that are genuinely difficult to get right.

---

## Common Pitfalls

### Pitfall 1: NVIDIA Container Toolkit not installed on host
**What goes wrong:** `docker compose up` fails with "Unknown runtime specified nvidia" error.
**Why it happens:** The `runtime: nvidia` directive requires the NVIDIA Container Toolkit to be installed on the host OS, not inside the container.
**How to avoid:** Document as a prerequisite. The toolkit is separate from NVIDIA drivers. Install with `distribution=$(. /etc/os-release;echo $ID$VERSION_ID) && curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg`.
**Warning signs:** Error message contains "Unknown runtime" or "cannot find runtime".

### Pitfall 2: Alembic autogenerate re-creates GIN indexes on every run
**What goes wrong:** `alembic revision --autogenerate` always generates a migration to drop and recreate GIN tsvector indexes, even when nothing has changed.
**Why it happens:** Known Alembic bug (#1390): the migration engine cannot reliably compare functional index expressions, so it always sees them as different.
**How to avoid:** Write GIN functional indexes as `op.execute()` raw SQL in the migration. Do not let autogenerate manage them. Optionally exclude them in `env.py` via `include_name`.
**Warning signs:** Running autogenerate twice produces a non-empty migration with only index operations.

### Pitfall 3: pgvector extension not created before vector column
**What goes wrong:** `alembic upgrade head` fails with "type vector does not exist".
**Why it happens:** The `vector` type is only available after `CREATE EXTENSION vector` runs. The extension creation must appear before any table using the type.
**How to avoid:** Put `op.execute("CREATE EXTENSION IF NOT EXISTS vector")` at the top of the `upgrade()` function, before any `op.create_table()` calls that include vector columns.
**Warning signs:** Migration fails on a fresh database but succeeds on one that already had pgvector installed.

### Pitfall 4: Celery worker_prefetch_multiplier=4 (default) with slow GPU tasks
**What goes wrong:** GPU tasks are pre-fetched and held in the worker, making the task appear to run for much longer than the actual execution time. The task occupies the worker even while waiting in memory.
**Why it happens:** Default `worker_prefetch_multiplier=4` means a worker fetches 4 tasks immediately even if it can only execute one at a time.
**How to avoid:** Set `worker_prefetch_multiplier=1` in the Celery config. This is especially important for the slow/gpu queue.
**Warning signs:** Tasks appear to be "running" for minutes in Flower before any GPU activity occurs.

### Pitfall 5: GROBID health check start_period too short
**What goes wrong:** Celery worker (or other services depending on GROBID) starts before GROBID is ready, and the first real task fails with a connection refused error.
**Why it happens:** GROBID loads CRF/DL models during startup, which takes 30-90 seconds depending on hardware. Default `start_period` is 0s.
**How to avoid:** Set `start_period: 60s` (or 90s on slower hardware) on GROBID's health check. Note: GROBID is not directly depended on by the worker in Phase 1 (no tasks call it yet), but set it correctly now.
**Warning signs:** GROBID logs show "loading models" while health check is already failing.

### Pitfall 6: Redis `result_backend` not set for Celery
**What goes wrong:** Task results are lost; `AsyncResult.get()` hangs or returns None.
**Why it happens:** Celery uses the broker for sending tasks but needs a separate `result_backend` to store results. By default there is no backend.
**How to avoid:** Set both `broker_url` and `result_backend` to the Redis URL. Use `redis://redis:6379/0` for broker and `redis://redis:6379/1` (different database) or same URL for results.
**Warning signs:** `AsyncResult(task_id).status` always returns PENDING.

---

## Code Examples

Verified patterns from official sources:

### docker-compose.yml GPU worker service
```yaml
# Source: Docker Compose GPU docs (docs.docker.com/compose/how-tos/gpu-support/)
# Note: runtime: nvidia (legacy) and deploy.resources (modern) are both valid;
#       runtime: nvidia is simpler for single-GPU single-container setups
worker:
  build: .
  runtime: nvidia
  environment:
    - NVIDIA_VISIBLE_DEVICES=all
    - NVIDIA_DRIVER_CAPABILITIES=compute,utility
  env_file: .env
  volumes:
    - ./data:/data
  command: >
    celery -A app.celery_app worker
      -Q fast,slow
      --concurrency=4
      --loglevel=info
  depends_on:
    postgres:
      condition: service_healthy
    redis:
      condition: service_healthy
  restart: unless-stopped
```

### Alembic env.py reading DATABASE_URL from .env
```python
# Source: Alembic tutorial (alembic.sqlalchemy.org/en/latest/tutorial.html)
import os
from dotenv import load_dotenv
from alembic import context
from app.models import Base

load_dotenv()

config = context.config
config.set_main_option("sqlalchemy.url", os.environ["DATABASE_URL"])
target_metadata = Base.metadata
```

### SQLAlchemy db.py engine + session factory
```python
# Source: SQLAlchemy 2.0 docs
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.config import get_settings

settings = get_settings()

engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,       # verify connections before use
    pool_size=10,
    max_overflow=20,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
```

### Celery app initialization
```python
# Source: Celery 5.4 docs
from celery import Celery
from kombu import Queue
from app.config import get_settings

settings = get_settings()

celery_app = Celery("app", include=["app.tasks.ingest", "app.tasks.parse", "app.tasks.normalize"])

celery_app.conf.update(
    broker_url=settings.redis_url,
    result_backend=settings.redis_url,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_queues=(Queue("fast"), Queue("slow")),
    task_default_queue="fast",
    task_routes={
        "app.tasks.ingest.*": {"queue": "fast"},
        "app.tasks.parse.parse_latex": {"queue": "fast"},
        "app.tasks.parse.parse_jats": {"queue": "fast"},
        "app.tasks.parse.parse_pdf_mineru": {"queue": "slow"},
        "app.tasks.parse.parse_pdf_grobid": {"queue": "slow"},
        "app.tasks.normalize.*": {"queue": "fast"},
    },
    worker_prefetch_multiplier=1,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    broker_connection_retry_on_startup=True,
)
```

### Stub task with correct queue and time limit
```python
# app/tasks/ingest.py
from celery import shared_task

@shared_task(
    bind=True,
    name="app.tasks.ingest.ingest_paper",
    max_retries=3,
    time_limit=60,
    soft_time_limit=50,
    default_retry_delay=10,
)
def ingest_paper(self, arxiv_id: str) -> dict:
    """Stub: Phase 2 implements. Returns immediately for Phase 1 verification."""
    return {"status": "stub", "arxiv_id": arxiv_id}
```

### Redis cache write/read (Phase 1 smoke test)
```python
# Source: redis-py docs
import redis
from app.config import get_settings

settings = get_settings()
r = redis.from_url(settings.redis_url)

# Write with TTL
r.setex("test:key", 3600, "test_value")

# Read
value = r.get("test:key")
assert value == b"test_value"
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| SQLAlchemy 1.x `Column()` | SQLAlchemy 2.0 `Mapped[T]` + `mapped_column()` | SQLAlchemy 2.0 (2023) | Better type safety, IDE completion |
| `docker-compose.yml` v3 `version:` field | Docker Compose v2 format (no version field required) | Docker Compose v2 (2022) | Omit `version:` key entirely |
| `runtime: nvidia` only | `deploy.resources.reservations.devices` | Docker Compose v3.8+ | Both work; `runtime: nvidia` simpler for single GPU |
| Alembic with `Base.metadata` in-migration | Alembic with `target_metadata` in env.py | Standard pattern | Always use target_metadata; autogenerate requires it |
| `postgres:16` + manual pgvector install | `pgvector/pgvector:pg16` | pgvector project (2023+) | Pre-built image; no custom Dockerfile needed |

**Deprecated/outdated:**
- `version: "3.8"` in docker-compose.yml: The top-level `version` key is now ignored by Docker Compose v2 and should be omitted.
- SQLAlchemy `Column()` without `Mapped[T]`: Still works but is "legacy" in SQLAlchemy 2.0.
- `CELERY_BROKER_URL` (uppercase): Celery 5.x uses lowercase `broker_url` in `app.conf.update()`. Uppercase env var still works for backward compat but lowercase is canonical.

---

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest (latest) |
| Config file | pyproject.toml `[tool.pytest.ini_options]` |
| Quick run command | `pytest tests/test_infra.py -x -v` |
| Full suite command | `pytest tests/ -v` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| INFRA-01 | `docker compose up` brings all 5 services healthy | smoke (manual verify) | `docker compose ps --format json \| jq '.[] \| select(.Health != "healthy")'` | manual |
| INFRA-02 | All 5 tables exist with correct columns and indexes | integration | `pytest tests/test_infra.py::test_schema -x` | Wave 0 |
| INFRA-03 | Redis write/read succeeds at `redis_url` | integration | `pytest tests/test_infra.py::test_redis -x` | Wave 0 |
| INFRA-04 | Task enqueued to `fast` queue completes; `slow` queue task respects 300s limit | integration | `pytest tests/test_infra.py::test_celery_queues -x` | Wave 0 |
| INFRA-05 | `alembic upgrade head` runs cleanly on fresh database | integration | `pytest tests/test_infra.py::test_alembic -x` | Wave 0 |
| INFRA-06 | `paper_citations` table exists; pgvector extension enabled; `vector` column present | integration | `pytest tests/test_infra.py::test_pgvector -x` | Wave 0 |

### Sampling Rate
- **Per task commit:** `pytest tests/test_infra.py -x -v`
- **Per wave merge:** `pytest tests/ -v`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/conftest.py` — shared fixtures: db engine from DATABASE_URL, Redis client, Celery app import
- [ ] `tests/test_infra.py` — covers INFRA-01 through INFRA-06
- [ ] `pytest` install: `pip install pytest pytest-timeout`

---

## Open Questions

1. **Python dependency management tool (Poetry vs pip + pyproject.toml)**
   - What we know: Both work; project left this as Claude's discretion
   - What's unclear: Whether the VM environment has Poetry installed
   - Recommendation: Use `pyproject.toml` with `[project.dependencies]` + pip. Simpler, no lock file format difference, Docker-friendly.

2. **Celery concurrency setting for the mixed fast/slow worker**
   - What we know: Single container runs both `fast` and `slow` queues; concurrency is tunable post-Phase 2
   - What's unclear: Optimal concurrency when GPU tasks are blocking; prefetch=1 helps but doesn't solve it
   - Recommendation: Start with `--concurrency=4` for `fast` and effectively `--concurrency=1` behavior on `slow` due to GPU exclusivity. Monitor with Flower.

3. **Alembic GIN index autogenerate exclusion**
   - What we know: Autogenerate always re-creates these; raw SQL is the workaround
   - What's unclear: Whether to also add an `include_name` exclusion in env.py
   - Recommendation: Write initial migration as a single hand-written file (not autogenerated). Use autogenerate only for future schema changes, and exclude known functional indexes.

---

## Sources

### Primary (HIGH confidence)
- PyPI registry (2026-04-13) — all package version numbers verified via `pip index versions`
- Docker official docs (docs.docker.com/compose/how-tos/gpu-support/) — GPU runtime configuration
- pgvector/pgvector Docker Hub — pg16 image tag confirmed
- grobid/grobid Docker Hub + GROBID readthedocs — port 8070, `/api/isalive`, 0.8.0 image tag

### Secondary (MEDIUM confidence)
- Alembic docs (alembic.sqlalchemy.org) — env.py pattern, autogenerate limitations
- SQLAlchemy 2.0 docs (docs.sqlalchemy.org/en/20/) — Mapped[T] declarative pattern, JSONB, GIN index
- Celery 5.4 docs (docs.celeryq.dev/en/v5.4.0/) — task_queues, task_routes, time_limit configuration
- pydantic-settings docs (docs.pydantic.dev) — BaseSettings, SettingsConfigDict, lru_cache pattern

### Tertiary (LOW confidence)
- GitHub issue sqlalchemy/alembic#1390 — GIN index autogenerate false-positive (verified as known issue)
- GitHub issue sqlalchemy/alembic#1327 — operator classes not supported in autogenerate

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all versions confirmed from PyPI registry on 2026-04-13
- Architecture: HIGH — all patterns from official docs; Docker Compose, SQLAlchemy, Celery, Alembic
- Pitfalls: HIGH (for GROBID start_period, Alembic GIN bug, pgvector ordering) / MEDIUM (for prefetch_multiplier impact on mixed queue)

**Research date:** 2026-04-13
**Valid until:** 2026-05-13 (30 days; stable ecosystem)
