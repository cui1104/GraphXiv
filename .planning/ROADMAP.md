# Roadmap: Research Knowledge Graph — End-to-End Platform

## Overview

Seven phases on a strict critical path: stand up the infrastructure, crawl the corpus, route papers through tiered parsers, normalize everything to the deepxiv_sdk JSON contract, serve via a FastAPI REST layer, verify the SDK fork end-to-end, and benchmark the three PDF parsers head-to-head. Phases 1–6 are sequential dependencies; Phase 7 runs in parallel starting from Phase 3. Total timeline: ~4 weeks (April 2026, DATS5990).

## Phases

- [x] **Phase 1: Foundation** - Docker Compose services, PostgreSQL schema, Redis, and Celery skeleton wired up and verified (completed 2026-04-14)
- [ ] **Phase 2: Ingestion** - arXiv and PMC crawlers running with resumable state and ~10,000 papers queued for parsing
- [ ] **Phase 3: Parser Layer** - TEX2JSON, JATS2JSON, and MinerU/GROBID paths all producing structured output from real papers
- [ ] **Phase 4: Normalizer + Storage** - All parser outputs mapped to unified deepxiv_sdk JSON schema and upserted to PostgreSQL
- [ ] **Phase 5: REST API** - All 7 FastAPI endpoints serving correct JSON with Redis caching
- [ ] **Phase 6: SDK Fork + Verification** - Forked deepxiv_sdk passes full test suite against this backend and ships one new capability
- [ ] **Phase 7: Benchmark** - MinerU vs GROBID vs Docling vs this system's router evaluated on 150 DL papers with written findings report

---

## Phase Details

### Phase 1: Foundation
**Goal**: All infrastructure services run locally via Docker Compose and the database schema is locked in before any data flows through it.
**Depends on**: Nothing (first phase)
**Requirements**: INFRA-01, INFRA-02, INFRA-03, INFRA-04, INFRA-05
**Success Criteria** (what must be TRUE):
  1. `docker compose up` brings up PostgreSQL, Redis, Celery workers, Flower, and GROBID with no manual steps
  2. `papers`, `paper_sources`, `id_map`, and `crawl_state` tables exist with correct indexes; `alembic upgrade head` applies cleanly on a fresh database
  3. A test Celery task enqueued to the `fast` queue completes successfully and a test task on the `slow` queue respects its 5-minute time limit
  4. Redis is reachable as both the Celery broker and a key-value store; a test cache write and read succeeds
**Plans**: 3 plans

Plans:
- [x] 01-01: Docker Compose services — write `docker-compose.yml` for PostgreSQL 16, Redis 7, Celery worker (fast + slow queues), Flower, and GROBID 0.8; verify all services start and pass health checks
- [x] 01-02: Database schema — write Alembic migration for `papers` (hybrid schema: structured columns + JSONB content blob), `paper_sources`, `id_map`, and `crawl_state`; add all indexes (arxiv_id, pmcid, doi, GIN on tsvector for title+abstract)
- [x] 01-03: Celery skeleton — configure Celery app with Redis broker, `fast` and `slow`/`gpu` task queues, `task_routes`, `max_retries=3`, and per-queue `time_limit`; write stub tasks for each pipeline stage; verify task routing with Flower

---

### Phase 2: Ingestion
**Goal**: Both arXiv and PMC crawlers run to completion with resumable state, asset files are saved to disk, and the papers queue is populated with ~10,000 records.
**Depends on**: Phase 1
**Requirements**: INGEST-01, INGEST-02, INGEST-03, INGEST-04, INGEST-05, INGEST-06
**Success Criteria** (what must be TRUE):
  1. arXiv OAI-PMH crawler harvests metadata for all 5 target categories (cs.LG, cs.AI, cs.CV, cs.CL, stat.ML) without triggering a rate-limit ban; User-Agent header is present on every request; 3 req/sec token-bucket is enforced
  2. Each arXiv paper record has its asset downloaded (`.tar.gz` or `.pdf`), with `Content-Type`-based routing recorded in `paper_sources`
  3. PMC OAI-PMH crawler completes a full harvest with resumptionToken persisted to `crawl_state` after every page; final record count matches the `completeListSize` from the first response
  4. Stopping and restarting either crawler resumes from where it left off without re-ingesting already-processed IDs
  5. arXiv IDs are normalized (version suffix stripped); re-ingesting a v2 paper updates the existing record
  6. Total corpus reaches ~10,000 papers with `parse_status = pending` in `paper_sources`
**Plans**: 4 plans

Plans:
- [x] 02-01-PLAN.md — Schema migration (crawl_state UNIQUE), shared crawler utilities (ID normalization, crawl state persistence, dedup), new dependencies, test scaffold (completed 2026-04-15)
- [ ] 02-02-PLAN.md — arXiv OAI-PMH harvester (httpx + aiolimiter, 5 DL sets) and e-print asset downloader (Content-Type routing), replace Celery stubs
- [ ] 02-03-PLAN.md — PMC OAI-PMH harvester (sickle, pmc-open set, DL keyword filter, token checkpointing)
- [ ] 02-04-PLAN.md — CLI harvest runner, 100-paper smoke test, resumability verification, human sign-off

---

### Phase 3: Parser Layer
**Goal**: All three parsing paths (TEX2JSON, JATS2JSON, MinerU + GROBID) produce structured JSON output from real papers, with quality flags and `parse_source` recorded.
**Depends on**: Phase 2
**Requirements**: PARSE-01, PARSE-02, PARSE-03, PARSE-04, PARSE-05
**Success Criteria** (what must be TRUE):
  1. A `.tar.gz` arXiv paper is parsed by TEX2JSON and produces a JSON object with non-empty `title`, `abstract`, and at least one `body_text` paragraph; papers with >2% backslash tokens are flagged `parse_quality=degraded`
  2. A PMC JATS XML file is parsed by JATS2JSON and produces the same schema; JATS DOCTYPE is detected and old NLM 2.x DTD files are normalized before parsing
  3. A PDF-only arXiv paper passes pymupdf text-layer pre-check, routes to MinerU, and produces structured JSON; scanned PDFs (text layer < 100 characters) are flagged separately before routing
  4. GROBID companion service is called via `/api/processReferences` and enriches the citations list of a successfully parsed paper
  5. `parse_source` is recorded as `latex`, `jats`, `pdf_mineru`, or `pdf_grobid`; multi-column PDF degradation (avg sentence length >80 tokens) sets `parse_quality=degraded`
**Plans**: 4 plans

Plans:
- [ ] 03-01: TEX2JSON parser task — install s2orc-doc2json from GitHub HEAD; implement Celery task that unpacks `.tar.gz`, detects main `.tex` file by `\documentclass` heuristic, runs TEX2JSON, and returns raw S2ORC JSON dict; add post-parse backslash-token check; set `parse_source=latex`
- [ ] 03-02: JATS2JSON parser task — implement Celery task that reads PMC JATS XML (inline or from file), detects DOCTYPE/schema version, applies NLM 2.x normalization if needed, runs JATS2JSON, and returns raw S2ORC JSON dict; set `parse_source=jats`
- [ ] 03-03: MinerU PDF parser task — install `magic-pdf[full]` (verify PyPI version); implement Celery task on `slow` queue that pre-checks PDF text layer with pymupdf, routes scanned PDFs to a `parse_status=scanned_skip` status, and runs MinerU on born-digital PDFs; post-parse sentence-length degradation check; set `parse_source=pdf_mineru`
- [ ] 03-04: GROBID reference extraction and smart router — implement GROBID client task that calls `/api/processReferences` and merges citation data; implement smart router that selects the correct parser Celery chain (TEX2JSON → GROBID → store, JATS2JSON → GROBID → store, MinerU → GROBID → store) based on available asset type in `paper_sources`

---

### Phase 4: Normalizer + Storage
**Goal**: Every parser output is mapped to the exact deepxiv_sdk JSON field names and upserted to PostgreSQL, with token counts, tldr, dedup fingerprints, and cross-source ID links all populated.
**Depends on**: Phase 3
**Requirements**: NORM-01, NORM-02, NORM-03, NORM-04, NORM-05, NORM-06
**Success Criteria** (what must be TRUE):
  1. A paper processed via TEX2JSON, JATS2JSON, or MinerU produces a database row where `SELECT content->'title', content->'sections', content->'citations', content->'token_count', content->'tldr', content->'src_url', content->'parse_source' FROM papers WHERE arxiv_id=...` returns non-null values for all fields
  2. `token_count` is an integer greater than 0 for every successfully parsed paper; key is never absent from response JSON
  3. `tldr` key is present in every response (value is string or null, never absent)
  4. A paper ingested first as arXiv and then found in PMC is linked via `id_map` rather than stored as a duplicate; dedup fingerprint matches prevent double-counting
  5. Section objects have `{heading, sec_num, text, paragraphs, token_count}` shape; citation objects have `{ref_id, title, authors, year, venue, doi, arxiv_id, raw_text}` shape — verified by running deepxiv_sdk `Reader` field accesses against at least 5 stored papers before Phase 5 begins
**Plans**: 3 plans

Plans:
- [ ] 04-01: PaperJSON normalizer — before writing any code, clone deepxiv_sdk and run `grep -r "title\|abstract\|sections\|citations\|token_count\|src_url\|tldr\|parse_source\|heading\|text\|ref_id" deepxiv_sdk/` to extract every accessed field name; write normalizer that maps S2ORC JSON (from TEX2JSON/JATS2JSON) and MinerU JSON to the verified PaperJSON schema; handle JATS optional-field variance gracefully
- [ ] 04-02: Token count, tldr, and quality fields — implement tiktoken (cl100k_base) token count computation on full section text; implement tldr fallback (first 2 sentences of abstract via sentence splitter); populate `parse_quality` and `parse_source` fields; ensure `tldr` and `token_count` keys are always present (never omitted) in the serialized JSON
- [ ] 04-03: PostgreSQL upsert and ID cross-linking — implement `ON CONFLICT DO UPDATE` upsert to `papers` table keyed on `canonical_id`; insert into `paper_sources` with `parse_status=success/failed`; compute SHA-256 dedup fingerprint; look up incoming DOI in `id_map` to detect cross-source matches (same paper as both arXiv and PMC record); link via `id_map` and update existing canonical record

---

### Phase 5: REST API
**Goal**: All 7 FastAPI endpoints return correctly shaped JSON that the deepxiv_sdk `Reader` class can consume without empty-value responses, with Redis caching active.
**Depends on**: Phase 4
**Requirements**: API-01, API-02, API-03, API-04, API-05, API-06, API-07, API-08, API-09
**Success Criteria** (what must be TRUE):
  1. `GET /arxiv/{id}/head`, `/brief`, `/sections`, and `/full` all return HTTP 200 with non-empty content for a paper in the database; responses match the exact field shapes documented in FEATURES.md
  2. `GET /arxiv/search?q=attention&limit=5` returns `{total, results: [...]}` with at least one result for any keyword present in the stored corpus
  3. `GET /pmc/{id}/head` and `GET /pmc/{id}/full` return correctly shaped responses for PMC papers
  4. Any unknown arXiv ID or PMC ID returns HTTP 404 with a structured `{error, message}` body
  5. A second identical request for the same paper ID is served from Redis cache; `KEYS papers:*` in Redis shows active cache entries
**Plans**: 3 plans

Plans:
- [ ] 05-01: FastAPI app structure and Pydantic response schemas — scaffold FastAPI app with Uvicorn; define Pydantic v2 response models for all 7 endpoint shapes (HeadResponse, BriefResponse, SectionsResponse, FullResponse, SearchResponse, PmcHeadResponse, PmcFullResponse); field names must exactly match deepxiv_sdk contract verified in Phase 4
- [ ] 05-02: Endpoint implementations — implement all 7 route handlers using SQLAlchemy 2.x async queries; implement `id_map` resolution so any input ID (arxiv_id, pmcid, doi) resolves to a canonical paper row; implement keyword search using PostgreSQL full-text search index on title+abstract; return 404 with structured body for missing IDs
- [ ] 05-03: Redis caching layer — implement cache-aside pattern for all endpoints; cache key format `papers:{canonical_id}:{view}`, TTL 3600s for paper views, 300s for search results; cache invalidation on paper upsert; verify cache hit/miss behavior manually and via Flower task logs

---

### Phase 6: SDK Fork + Verification
**Goal**: The forked deepxiv_sdk passes its full test suite against this backend and ships at least one new capability.
**Depends on**: Phase 5
**Requirements**: SDK-01, SDK-02, SDK-03
**Success Criteria** (what must be TRUE):
  1. Forked SDK installs via `pip install -e .` and `Reader(base_url="http://localhost:8000")` connects to the backend without errors
  2. `Reader.head()`, `Reader.brief()`, `Reader.sections()`, `Reader.full()`, and `Reader.search()` all return non-empty content (not `None` or `[]`) for at least 10 arXiv papers from the stored corpus
  3. The original SDK test suite (if any) passes with zero failures against this backend
  4. The new capability (local disk caching or table-access endpoint + SDK method) works: repeated SDK calls with caching enabled do not make network requests; OR a new `Reader.tables()` method returns table content for a paper that has tables
**Plans**: 3 plans

Plans:
- [ ] 06-01: Fork and base_url update — fork deepxiv_sdk on GitHub; update `base_url` default in `Reader.__init__` to point at `http://localhost:8000`; verify all existing SDK methods are importable and callable; document any field name mismatches found during SDK test run and fix in backend normalizer if needed
- [ ] 06-02: SDK contract verification — run the SDK's existing test suite (or write integration tests if none exist) that call every Reader method and assert non-None, non-empty content values for at least 10 test papers; fix any silent-empty-response issues found by tracing the failing field name back through the normalizer
- [ ] 06-03: New capability — implement local response caching in the SDK fork (cache responses to `~/.deepxiv_cache/` on first call, serve from disk on repeat calls with configurable TTL) OR implement a `Reader.tables()` method backed by a new `GET /arxiv/{id}/tables` backend endpoint that extracts `ref_entries` entries of type `table`; write tests for the new capability

---

### Phase 7: Benchmark
**Goal**: An empirical comparison of MinerU, GROBID, and Docling on the DL paper corpus is complete and findings are documented.
**Depends on**: Phase 3 (can run in parallel with Phases 4–6)
**Requirements**: BENCH-01, BENCH-02, BENCH-03
**Success Criteria** (what must be TRUE):
  1. Benchmark sample of exactly 150 DL papers is selected, including at least 30 two-column IEEE/ACM-format papers; all three standalone parsers (MinerU, GROBID, Docling) plus the pipeline router run on the same sample without crashing
  2. Section extraction accuracy is measured: for each of the four conditions (MinerU, GROBID, Docling, Router), the number of correctly identified section headings and percentage of sections with coherent (non-garbled) body text is recorded
  3. Table extraction quality is measured: for each condition, the presence and structural completeness (caption, headers, row content) of tables is recorded
  4. Findings report documents sample composition, methodology, per-condition scores in a comparison table, two-column performance gap, and a recommendation on which parser to use as MinerU fallback
**Plans**: 3 plans

Plans:
- [ ] 07-01: Benchmark sample selection and Docling setup — select exactly 150 DL papers from the stored corpus (stratified: ~75 single-column arXiv LaTeX-sourced, ~50 two-column IEEE/ACM/Nature-style PDF-only, ~25 mixed); install Docling; verify MinerU, GROBID, Docling, and the pipeline router all run on the benchmark sample without crashes or missing dependencies
- [ ] 07-02: Automated evaluation — for each of four conditions (MinerU standalone, GROBID standalone, Docling standalone, Router) and each sample paper, extract sections and tables; compute section heading match rate against ground truth (LaTeX-sourced papers as reference); compute sentence-length distribution to detect multi-column interleaving; record table presence rate and structural completeness score; output all four conditions to a single CSV with condition column
- [ ] 07-03: Findings report — analyze CSV; compute per-condition aggregate scores; produce comparison table (MinerU | GROBID | Docling | Router) across all metrics; characterize multi-column failure modes; write benchmark report documenting methodology, sample composition, results table, and recommendation for which parser to use as MinerU fallback

---

## Progress

**Execution Order:**
Phases execute in numeric order: 1 → 2 → 3 → 4 → 5 → 6. Phase 7 is parallel (start after Phase 3).

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Foundation | 3/3 | Complete   | 2026-04-14 |
| 2. Ingestion | 1/4 | In progress | - |
| 3. Parser Layer | 0/4 | Not started | - |
| 4. Normalizer + Storage | 0/3 | Not started | - |
| 5. REST API | 0/3 | Not started | - |
| 6. SDK Fork + Verification | 0/3 | Not started | - |
| 7. Benchmark | 0/3 | Not started | - |
