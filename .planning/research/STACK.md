# Technology Stack

**Project:** Research Knowledge Graph — Academic Paper Processing Pipeline
**Researched:** 2026-04-13
**Confidence note:** Version numbers based on training data through August 2025 — verify against PyPI/GitHub before pinning.

---

## Recommended Stack

### Core Framework / API Layer

| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| FastAPI | 0.111.x | REST API server | Async-native, automatic OpenAPI docs, Pydantic v2 validation matches deepxiv_sdk JSON schema contract |
| Uvicorn | 0.29.x | ASGI server | Production-grade, `--workers` for multi-process without Gunicorn ceremony |
| Pydantic v2 | 2.7.x | Schema validation | Rust core is 5-50x faster than v1 — critical when serialising thousands of paper records |
| Python | 3.11 | Runtime | 10-60% speed gains over 3.10; 3.12 has ML dep lag (torch, paddleocr). Pin 3.11. |

**FastAPI over Flask:** Flask is synchronous by default. This pipeline is I/O-heavy (DB writes, filesystem reads, HTTP fetches). FastAPI's native async context means Celery worker callbacks and API handlers share a mental model without greenlet workarounds.

---

### Parser Layer — Full Comparison and Routing Strategy

#### Parser Comparison Matrix

| Parser | Approach | Input | Output | Tables | Math | Speed (CPU) | GPU Required | Stars |
|--------|----------|-------|--------|--------|------|------------|-------------|-------|
| **s2orc-doc2json** | Rule-based / GROBID-mediated | PDF, .tex, JATS XML | S2ORC JSON | No | No | Fast | No | ~2k |
| **GROBID** | CRF + BiLSTM-CRF | PDF | TEI XML | Partial | No | Medium | Optional | ~3.5k |
| **MinerU (magic-pdf)** | YOLOv8 + PaddleOCR + UniMERNet | PDF | Markdown + JSON | Yes | Yes (LaTeX) | Slow (10x slower without GPU) | Strongly recommended | ~59k |
| **Docling** | IBM layout + TATR table transformer | PDF, DOCX, HTML | JSON, Markdown | Yes (TATR) | Partial | Medium-Slow | Optional | ~57k |
| **Nougat** | End-to-end encoder-decoder | PDF (as images) | Modified Markdown | Yes | Yes (excellent) | Very slow | Required | ~9.9k |

#### Parser Routing Strategy (Recommended)

```
arXiv paper received
  ├── LaTeX source available (.tar.gz) → s2orc-doc2json TEX2JSON      [fast, deterministic, ~95% of papers]
  │     └── Parse failure? → fall through to PDF path
  └── PDF only
        ├── General paper → MinerU (magic-pdf)                         [best all-round quality]
        └── Math-critical AND GPU available → Nougat                   [formula fidelity only — not default]

PMC paper received
  ├── JATS XML available (OAI-PMH) → s2orc-doc2json JATS2JSON         [fast, deterministic, ~90% of OA papers]
  │     └── Parse failure? → fall through to PDF path
  └── PDF only → MinerU (fallback)

Reference extraction (any PDF)
  └── GROBID /api/processReferences                                    [companion service, not primary parser]
```

#### Parser Recommendations

**Primary PDF parser: MinerU (magic-pdf)**
- Version: 1.x (verify on PyPI: `magic-pdf`)
- Install: `pip install magic-pdf[full]`
- Why over Docling: YOLOv8 layout detector outperforms Docling's IBM model on arXiv-style multi-column layouts. JSON output aligns better with project target schema.
- Why over GROBID: GROBID is not a full-content extractor. TEI XML requires significant post-processing; no table/figure extraction.
- Why over Nougat: GPU required with no viable CPU fallback; outputs .mmd not JSON; formula fidelity not in scope.
- GPU caveat: MinerU on CPU is ~10x slower. A GPU (T4 or 3090) is strongly recommended for thousands/day.

**Deterministic fast-path parser: s2orc-doc2json**
- Version: GitHub HEAD (no versioned PyPI release)
- Install: `git clone https://github.com/allenai/s2orc-doc2json && pip install -e s2orc-doc2json`
- Why: Purpose-built for `.tex` (LaTeXML-based) and JATS XML paths. S2ORC JSON schema is well-documented and close to target schema. Validated on tens of millions of papers.
- Caveat: PDF path uses GROBID internally. For PDFs, skip s2orc and call MinerU directly.

**Reference extraction companion: GROBID**
- Version: 0.8.x (Docker service)
- Install: `docker pull lfoppiano/grobid:0.8.0` + `pip install grobid-client-python`
- Scope: Reference extraction ONLY via `/api/processReferences`. Complementary to MinerU, not competing.

**Nougat: defer unless math fidelity is explicit requirement**
- Version: 0.1.x — low confidence, development pace slowed post-2023
- Not recommended as primary: GPU required, slow, outputs .mmd not JSON, LaTeX source path is better for most arXiv math anyway.

---

### LaTeX Processing

| Technology | Purpose | Why |
|------------|---------|-----|
| s2orc-doc2json TEX2JSON | arXiv .tex → S2ORC JSON | Handles multi-file .tex archives, resolves `\input{}`/`\include{}`, battle-tested on S2ORC corpus |
| LaTeXML (fallback only) | .tex → XML → JSON | More complete macro coverage for exotic packages; Perl runtime is heavy — only if s2orc fails >5% |

---

### JATS XML Processing

| Technology | Purpose | Why |
|------------|---------|-----|
| s2orc-doc2json JATS2JSON | PMC JATS XML → S2ORC JSON | Purpose-built for JATS 1.x DTD, extracts sections/tables/references deterministically |
| lxml 5.x (fallback) | Custom XPath parser | JATS is well-documented; 200-line lxml/XPath extractor viable for parse failures |

---

### Database / Storage

**Recommendation: PostgreSQL 16 with JSONB**

| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| PostgreSQL | 16.x | Primary data store | JSONB columns + GIN indexes for fast lookups; SQL for metadata filtering |
| SQLAlchemy (async) | 2.x | ORM / query layer | Async engine + asyncpg gives true async DB access compatible with FastAPI |
| asyncpg | 0.29.x | PostgreSQL async driver | Fastest Python PostgreSQL driver |
| Alembic | 1.13.x | Schema migrations | Standard companion for tracked, reversible schema changes |

**PostgreSQL over Elasticsearch:** Query patterns here are lookup-by-ID plus simple metadata filtering — not full-text relevance ranking. Elasticsearch adds JVM complexity with no benefit. PostgreSQL JSONB + GIN handles `jsonb_path_query` patterns efficiently at this scale.

**Recommended schema:**
```sql
CREATE TABLE papers (
    id          BIGSERIAL PRIMARY KEY,
    arxiv_id    TEXT UNIQUE,
    pmcid       TEXT UNIQUE,
    title       TEXT,
    ingested_at TIMESTAMPTZ DEFAULT NOW(),
    parse_status TEXT DEFAULT 'pending',  -- pending/success/failed
    source_type TEXT,                      -- latex/jats/pdf
    content     JSONB                      -- full parsed JSON blob
);
CREATE INDEX papers_arxiv_id_idx ON papers (arxiv_id);
CREATE INDEX papers_pmcid_idx    ON papers (pmcid);
CREATE INDEX papers_content_gin  ON papers USING GIN (content);
```

---

### Job Queue

**Recommendation: Celery 5.4 + Redis 7**

| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| Celery | 5.4.x | Task queue / worker | Python-native, battle-tested retry/failure semantics, `task_routes` for GPU vs fast queue separation |
| Redis | 7.x | Celery broker + result backend | In-memory broker; doubles as API caching layer |
| Flower | 2.x | Celery monitoring UI | Task inspection, worker health, failure tracking |

**Celery over Ray:** Ray is designed for ML training, simulation, actor-model parallelism. This pipeline's tasks are embarrassingly parallel, stateless, and I/O-bound. Celery's `@app.task` handles this in 20 lines with built-in retry, countdown backoff, and dead-letter queue. Ray cluster ops burden is not justified.

**Celery task architecture:**
```python
task_routes = {
    'pipeline.tasks.parse_pdf_mineru': {'queue': 'gpu'},
    'pipeline.tasks.parse_latex':      {'queue': 'fast'},
    'pipeline.tasks.parse_jats':       {'queue': 'fast'},
    'pipeline.tasks.extract_refs':     {'queue': 'fast'},
}

chain(
    download_source.s(paper_id),
    route_and_parse.s(),
    extract_references.s(),
    store_result.s(),
    mark_complete.s()
)
```

---

### Ingestion / Crawling

| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| httpx | 0.27.x | Async HTTP client | Native async, connection pooling, compatible with tenacity retry |
| arxiv (PyPI) | 2.x | arXiv API client | Wraps OAI-PMH and REST API; handles pagination, rate limits, source download |
| sickle | 0.7.x | OAI-PMH harvester for PMC | Standard Python OAI-PMH client for PMC bulk metadata and JATS XML |
| tenacity | 8.x | Retry / backoff | Exponential backoff for 429s, transient errors, download timeouts |

---

### Supporting Libraries

| Library | Version | Purpose |
|---------|---------|---------|
| pydantic-settings | 2.x | Config via env vars |
| loguru | 0.7.x | Structured logging |
| python-dotenv | 1.x | `.env` file loading |
| pytest | 8.x | Testing framework |
| pytest-asyncio | 0.23.x | Async test support |

---

## Alternatives Considered

| Category | Recommended | Alternative | Why Not |
|----------|-------------|-------------|---------|
| API framework | FastAPI | Flask | Synchronous default; no built-in Pydantic schema validation |
| Storage | PostgreSQL | Elasticsearch | Overengineered for key-lookup patterns; semantic search is out of scope |
| Storage | PostgreSQL | MongoDB | JSONB provides equivalent document storage with SQL joins; one fewer system |
| Job queue | Celery + Redis | Ray | Actor model overkill for stateless I/O pipeline |
| Job queue | Celery + Redis | RQ | Lacks routing/priority/retry features for GPU/CPU queue separation |
| Primary PDF parser | MinerU | Docling | MinerU JSON output aligns better with project target schema |
| Primary PDF parser | MinerU | Nougat | GPU required, no CPU fallback, .mmd output format |

---

## Installation

```bash
# Core API
pip install "fastapi==0.111.*" "uvicorn[standard]==0.29.*" "pydantic==2.7.*" "pydantic-settings==2.*"

# Database
pip install "sqlalchemy[asyncio]==2.*" "asyncpg==0.29.*" "alembic==1.13.*"

# Job queue
pip install "celery[redis]==5.4.*" "flower==2.*"

# HTTP / Ingestion
pip install "httpx==0.27.*" "arxiv==2.*" "sickle==0.7.*" "tenacity==8.*"

# Parsers — deterministic fast path
git clone https://github.com/allenai/s2orc-doc2json
pip install -e s2orc-doc2json

# Parser — ML PDF path
pip install "magic-pdf[full]"    # MinerU — downloads model weights

# GROBID companion (Docker)
docker pull lfoppiano/grobid:0.8.0
pip install "grobid-client-python"

# Supporting
pip install "loguru==0.7.*" "python-dotenv==1.*" "pytest==8.*" "pytest-asyncio==0.23.*"
```

---

## Version Confidence

| Component | Confidence | Verify At |
|-----------|------------|-----------|
| FastAPI 0.111.x | MEDIUM | https://pypi.org/project/fastapi/ |
| MinerU / magic-pdf 1.x | LOW | https://pypi.org/project/magic-pdf/ — version series changed rapidly |
| Celery 5.4.x | MEDIUM | https://pypi.org/project/celery/ |
| PostgreSQL 16.x | HIGH | Stable LTS |
| GROBID 0.8.x | MEDIUM | https://github.com/kermitt2/grobid/releases |
| s2orc-doc2json | LOW | No PyPI release — track GitHub HEAD |
| Nougat 0.1.x | LOW | Development pace slowed post-2023 |
| Redis 7.x | HIGH | Stable LTS |
| Python 3.11 | HIGH | Active LTS; full ML ecosystem support |
