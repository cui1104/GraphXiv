# Requirements: Research Knowledge Graph — End-to-End Platform

**Defined:** 2026-04-13
**Core Value:** Given an arXiv ID or PMC ID, return clean structured JSON (sections, tables, figures, metadata) in under a second — by doing all parsing work ahead of time via a continuous ingestion pipeline.

## v1 Requirements

### Infrastructure

- [x] **INFRA-01**: Docker Compose file brings up all services (PostgreSQL 16, Redis 7, Celery workers, Flower, GROBID) with a single `docker compose up`
- [x] **INFRA-02**: PostgreSQL schema includes `papers`, `paper_sources`, `id_map`, and `crawl_state` tables with correct indexes and UUID canonical IDs
- [x] **INFRA-03**: Redis is configured as both Celery broker and API response cache (TTL 3600s for paper views, 300s for search)
- [x] **INFRA-04**: Celery task skeleton exists with `fast` queue (LaTeX/XML tasks, 60s time limit) and `gpu`/`slow` queue (PDF ML tasks, 5min time limit), max_retries=3
- [x] **INFRA-05**: Alembic migration tracks initial schema; schema can be rebuilt cleanly from migrations
- [x] **INFRA-06**: PostgreSQL schema includes `paper_citations` edge table `(source_paper_id, target_paper_id NULLABLE, target_arxiv_id, target_doi, context_text)` with indexes on both paper ID columns; pgvector extension enabled with `embeddings` column on `papers` table

### Ingestion

- [ ] **INGEST-01**: arXiv OAI-PMH crawler harvests metadata for cs.LG, cs.AI, cs.CV, cs.CL, and stat.ML categories using `export.arxiv.org/oai2`, respects 3 req/sec rate limit with token-bucket enforcement and User-Agent header
- [ ] **INGEST-02**: arXiv asset downloader fetches `.tar.gz` (LaTeX source) or `.pdf` from `export.arxiv.org/e-print/{id}` based on `Content-Type` response header, saves to local disk
- [ ] **INGEST-03**: PMC OAI-PMH crawler harvests JATS XML from `ncbi.nlm.nih.gov/pmc/oai` for the deep learning subset, with resumptionToken persisted to `crawl_state` after every page
- [ ] **INGEST-04**: Crawl state is resumable — harvesting arXiv or PMC can be stopped and restarted without re-harvesting already-processed IDs
- [ ] **INGEST-05**: arXiv IDs are normalized on ingest (version suffix stripped, canonical form stored); duplicate versions update existing record rather than creating a new one
- [ ] **INGEST-06**: Corpus reaches ~10,000 papers total across arXiv and PMC sources

### Parsing

- [ ] **PARSE-01**: TEX2JSON fast path — arXiv `.tar.gz` archives are unpacked and fed to s2orc-doc2json to produce S2ORC-format JSON; main `.tex` file is detected by `\documentclass` heuristic; post-parse check flags `parse_quality=degraded` if >2% of tokens are raw backslash commands
- [ ] **PARSE-02**: JATS2JSON fast path — PMC JATS XML (inline from OAI response or from `.nxml` in FTP archive) is parsed by s2orc-doc2json JATS2JSON; JATS schema version is detected from `<!DOCTYPE>` and normalized before parsing
- [ ] **PARSE-03**: MinerU PDF path — for arXiv or PMC papers with no source available, PDF is pre-checked for text layer with pymupdf (scanned PDFs flagged separately), then routed to MinerU (`magic-pdf`) for structured JSON extraction
- [ ] **PARSE-04**: GROBID reference extraction — GROBID 0.8 runs as a Docker companion service and is called via `/api/processReferences` on any parsed paper to extract and enrich the citations list; GROBID is not used as a primary parser
- [ ] **PARSE-05**: Parser routing logic selects TEX2JSON → JATS2JSON → MinerU → GROBID in priority order; `parse_source` is recorded as `latex`, `jats`, `pdf_mineru`, or `pdf_grobid`; multi-column PDF parse degradation is detected by avg sentence length >80 tokens

### Normalization

- [ ] **NORM-01**: Normalizer maps all parser outputs (S2ORC JSON from TEX2JSON/JATS2JSON, MinerU JSON, GROBID TEI XML) to the unified PaperJSON schema with exact deepxiv_sdk field names: `title`, `abstract`, `authors`, `sections`, `citations`, `tldr`, `src_url`, `token_count`, `parse_source`
- [ ] **NORM-02**: `token_count` is always populated using tiktoken (cl100k_base) on the full extracted text; key is never omitted from responses
- [ ] **NORM-03**: `tldr` is always present as a key in responses (value may be null or first 2-3 sentences of abstract as deterministic fallback)
- [ ] **NORM-04**: Dedup fingerprint (SHA-256 of normalized title + first author + year) is computed and stored; papers with matching fingerprint across arXiv and PMC sources are linked via `id_map` rather than duplicated
- [ ] **NORM-05**: Section objects conform exactly to the SDK shape: `{heading, sec_num, text, paragraphs, token_count}`; citation objects conform to `{ref_id, title, authors, year, venue, doi, arxiv_id, raw_text}`
- [ ] **NORM-06**: `parse_quality` field is stored for every paper with degradation flags from all parse paths (macro expansion failures, multi-column detection, scanned PDF detection)

### REST API

- [ ] **API-01**: `GET /arxiv/{id}/head` returns metadata-only response (paper_id, arxiv_id, pmc_id, doi, title, abstract, tldr, authors, year, venue, src_url, token_count, parse_source)
- [ ] **API-02**: `GET /arxiv/{id}/brief` returns same shape as head (ensures SDK brief/head distinction works)
- [ ] **API-03**: `GET /arxiv/{id}/sections` returns sections-only response (paper_id, title, sections[], token_count)
- [ ] **API-04**: `GET /arxiv/{id}/full` returns the complete paper object including sections, citations, ref_entries, and back_matter
- [ ] **API-05**: `GET /arxiv/search?q=&limit=` returns `{total, results: [...head-shaped objects]}` with keyword search over stored title and abstract text
- [ ] **API-06**: `GET /pmc/{id}/head` returns metadata-only response (same shape as arxiv head, pmc_id populated)
- [ ] **API-07**: `GET /pmc/{id}/full` returns complete paper object for PMC papers
- [ ] **API-08**: All endpoints return HTTP 404 with a structured error body when the requested ID is not in the database
- [ ] **API-09**: Redis caching layer is active on all endpoints; cache keys follow `papers:{canonical_id}:{view}` pattern with appropriate TTLs
- [ ] **API-10**: `GET /arxiv/search` supports hybrid search — BM25 (PostgreSQL `tsvector`) + semantic vector similarity (pgvector) on paper titles and abstracts; `search_mode` parameter accepts `bm25`, `vector`, or `hybrid`
- [ ] **API-11**: `GET /arxiv/{id}/references` returns papers this paper cites, each with `in_corpus` flag, `context_text` (sentence where cited), and full head-shape metadata if in corpus
- [ ] **API-12**: `GET /arxiv/{id}/cited_by` returns papers in the corpus that cite this paper
- [ ] **API-13**: `GET /arxiv/{id}/related` returns co-cited papers (papers frequently cited alongside this one within the corpus)

### SDK Fork

- [ ] **SDK-01**: deepxiv_sdk is forked and the default `base_url` is updated to point at this backend; fork is installable via `pip install -e`
- [ ] **SDK-02**: All existing deepxiv_sdk features work against this backend — `Reader.head()`, `Reader.brief()`, `Reader.sections()`, `Reader.full()`, `Reader.search()` return non-empty content for at least 10 test papers
- [ ] **SDK-03**: SDK fork adds `Reader.references(arxiv_id)` and `Reader.cited_by(arxiv_id)` methods that call the citation graph endpoints
- [ ] **SDK-04**: SDK fork ships an improved `Agent` that performs citation-aware reading — after reading a paper's sections, the agent automatically identifies key cited works, fetches their sections if `in_corpus=True`, and incorporates that context before generating an answer; depth is configurable (default: 1 hop)

### Benchmark

- [ ] **BENCH-01**: Benchmark evaluates MinerU vs GROBID vs Docling on a sample of 100-200 arXiv DL papers, including at least 30 two-column IEEE/ACM-format papers
- [ ] **BENCH-02**: Benchmark measures section extraction accuracy (number of correctly identified sections, section heading match rate) and table extraction quality (presence and structural completeness of table content)
- [ ] **BENCH-03**: Benchmark findings are written up as a structured report documenting parser comparison results, sample selection methodology, and recommendation for which parser to use as MinerU fallback

---

## v2 Requirements

### Extended Content Extraction

- **EXT-01**: Inline `cite_spans`, `ref_spans`, `eq_spans` within paragraph text (character-offset span annotations)
- **EXT-02**: Per-paragraph body structure in sections (sections return flat text string in v1)
- **EXT-03**: Table HTML rendering (`html` field in `ref_entries.TABREF0`)
- **EXT-04**: Figure image extraction and base64 encoding (caption text + label only in v1)

### SDK Extensions

- **SDK-V2-01**: Bulk export endpoint and corresponding SDK method
- **SDK-V2-02**: tldr population via external API (S2 TLDR API or local model) rather than abstract-sentence fallback
- **SDK-V2-03**: New query modes (year range filter, venue filter, author search)

### Author and Citation Resolution

- **META-01**: Author affiliation and ORCID disambiguation
- **META-02**: Automatic citation cross-resolution to external paper IDs (DOI lookup, S2 ID matching)

---

## Out of Scope

| Feature | Reason |
|---------|--------|
| Semantic / vector search | Purely structured extraction; no RAG in scope per PROJECT.md |
| Real-time on-demand PDF parsing | All parsing is pre-computed; on-demand parsing would kill API response times |
| Full-text scraping of gated publishers | Legal / ToS risk; only Open Access via official APIs |
| Kubernetes / production deployment | Single machine + job queue is sufficient for 10k paper corpus |
| Nougat parser | GPU required with no CPU fallback; .mmd output format; formula fidelity not in scope |
| Author disambiguation (v1) | ML entity resolution; months of work; name strings as-is for v1 |
| Figure image extraction (v1) | Storage cost; caption text + label is sufficient for v1 |
| Inline cite_spans (v1) | Post-MVP; sections return flat text in v1 |
| Table HTML rendering (v1) | Deferred; table caption and content string is sufficient for v1 |

---

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| INFRA-01 | Phase 1 | Pending |
| INFRA-02 | Phase 1 | Complete |
| INFRA-03 | Phase 1 | Complete |
| INFRA-04 | Phase 1 | Complete |
| INFRA-05 | Phase 1 | Complete |
| INFRA-06 | Phase 1 | Complete |
| INGEST-01 | Phase 2 | Pending |
| INGEST-02 | Phase 2 | Pending |
| INGEST-03 | Phase 2 | Pending |
| INGEST-04 | Phase 2 | Pending |
| INGEST-05 | Phase 2 | Pending |
| INGEST-06 | Phase 2 | Pending |
| PARSE-01 | Phase 3 | Pending |
| PARSE-02 | Phase 3 | Pending |
| PARSE-03 | Phase 3 | Pending |
| PARSE-04 | Phase 3 | Pending |
| PARSE-05 | Phase 3 | Pending |
| NORM-01 | Phase 4 | Pending |
| NORM-02 | Phase 4 | Pending |
| NORM-03 | Phase 4 | Pending |
| NORM-04 | Phase 4 | Pending |
| NORM-05 | Phase 4 | Pending |
| NORM-06 | Phase 4 | Pending |
| API-01 | Phase 5 | Pending |
| API-02 | Phase 5 | Pending |
| API-03 | Phase 5 | Pending |
| API-04 | Phase 5 | Pending |
| API-05 | Phase 5 | Pending |
| API-06 | Phase 5 | Pending |
| API-07 | Phase 5 | Pending |
| API-08 | Phase 5 | Pending |
| API-09 | Phase 5 | Pending |
| API-10 | Phase 5 | Pending |
| API-11 | Phase 5 | Pending |
| API-12 | Phase 5 | Pending |
| API-13 | Phase 5 | Pending |
| SDK-01 | Phase 6 | Pending |
| SDK-02 | Phase 6 | Pending |
| SDK-03 | Phase 6 | Pending |
| SDK-04 | Phase 6 | Pending |
| BENCH-01 | Phase 7 | Pending |
| BENCH-02 | Phase 7 | Pending |
| BENCH-03 | Phase 7 | Pending |

**Coverage:**
- v1 requirements: 42 total
- Mapped to phases: 36
- Unmapped: 0 ✓

---
*Requirements defined: 2026-04-13*
*Last updated: 2026-04-13 after initial definition*
