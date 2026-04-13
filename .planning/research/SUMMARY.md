# Research Summary — Research Knowledge Graph

**Synthesized:** 2026-04-13
**Sources:** STACK.md, FEATURES.md, ARCHITECTURE.md, PITFALLS.md
**Consumer:** gsd-roadmapper (phase planning)

---

## Executive Summary

This is an academic paper processing pipeline: ingest arXiv/PMC papers, route them through appropriate parsers (LaTeX/JATS deterministic first, PDF-ML fallback), normalize output to a fixed JSON schema, store in PostgreSQL, and serve via a FastAPI REST layer that exactly matches the deepxiv_sdk field contract. The central value proposition is pre-computed parsing — all heavy work happens at ingestion, so API responses land under 100ms cached / 500ms cold.

The recommended approach is a tiered routing strategy: ~65% of arXiv papers have LaTeX source (.tar.gz) and can be parsed deterministically in seconds with s2orc-doc2json. PMC papers arrive as JATS XML via OAI-PMH and are equally fast. Only the PDF-only remainder needs MinerU (ML, CPU-slow, GPU-preferred). This three-lane router controls cost, speed, and quality simultaneously.

The critical risk is contract fidelity to deepxiv_sdk. The SDK accesses response JSON by exact key name; a mismatch returns silent empty values, not errors. The JSON schema must be locked in before any backend code is written, and the SDK test suite must run against every meaningful backend change. The second critical risk is arXiv rate limiting — exceeding the 3-req/s limit can produce a silent multi-day IP ban that stops ingestion entirely.

---

## 1. Stack Decisions

| Component | Choice | One-Line Rationale |
|-----------|--------|--------------------|
| Language / runtime | Python 3.11 | Active LTS; full ML ecosystem (torch, paddleocr); 3.12 has ML dep lag |
| API framework | FastAPI 0.111 + Uvicorn 0.29 | Async-native I/O model matches pipeline; built-in Pydantic v2 schema validation |
| Schema validation | Pydantic v2 (2.7) | 5-50x faster than v1; critical for serialising thousands of paper records |
| Primary database | PostgreSQL 16 + JSONB | Hybrid: structured columns for queriable fields, JSONB for full content blob |
| ORM | SQLAlchemy 2.x async + asyncpg 0.29 | True async DB access; fastest Python PostgreSQL driver |
| Job queue | Celery 5.4 + Redis 7 | Python-native, supports priority routing (fast / gpu queues), retry semantics |
| Fast-path parser | s2orc-doc2json (GitHub HEAD) | Purpose-built for arXiv .tar.gz (TEX2JSON) and PMC JATS (JATS2JSON); S2ORC-validated |
| PDF ML parser | MinerU / magic-pdf 1.x | Best JSON output alignment with target schema; tables + figures; beats Docling on multi-column arXiv layout |
| Reference extraction | GROBID 0.8 (Docker) | Companion service for /api/processReferences only — not primary parser |
| HTTP / crawling | httpx 0.27 + tenacity 8 + arxiv 2.x + sickle 0.7 | Async HTTP, exponential backoff, arXiv OAI-PMH + PMC OAI-PMH clients |
| Migrations | Alembic 1.13 | Tracked, reversible schema changes |
| Monitoring | Flower 2.x | Celery task health and failure tracking |

**Deferred / rejected:** Elasticsearch (overkill for ID-lookup patterns), MongoDB (JSONB covers it), Ray (actor model overkill for stateless I/O pipeline), Nougat (GPU required, .mmd not JSON, formula fidelity not in scope).

---

## 2. JSON Schema Contract (deepxiv_sdk Field Names)

The backend must produce exactly these field names. The SDK accesses them by key — wrong names return silent None / [].

### Full Paper Object

```json
{
  "paper_id":     "string",
  "arxiv_id":     "string|null",
  "pmc_id":       "string|null",
  "doi":          "string|null",
  "title":        "string",
  "abstract":     "string",
  "tldr":         "string|null",
  "authors":      ["string"],
  "year":         2024,
  "venue":        "string|null",
  "src_url":      "string",
  "token_count":  12000,
  "parse_source": "latex|jats|pdf_mineru|pdf_grobid",
  "sections": [
    {
      "heading":     "string",
      "sec_num":     "string|null",
      "text":        "string",
      "paragraphs":  [],
      "token_count": 1200
    }
  ],
  "citations": [
    {
      "ref_id":   "BIBREF0",
      "title":    "string",
      "authors":  ["string"],
      "year":     2019,
      "venue":    "string|null",
      "doi":      "string|null",
      "arxiv_id": "string|null",
      "raw_text": "string"
    }
  ],
  "ref_entries": {
    "FIGREF0": { "type": "figure", "text": "caption", "latex": null },
    "TABREF0": { "type": "table",  "text": "caption", "latex": "string|null",
                 "content": "string", "html": "string|null" }
  },
  "back_matter": []
}
```

### Endpoint-Specific Shapes

```
GET /arxiv/{id}/head     -> paper_id, arxiv_id, pmc_id, doi, title, abstract, tldr,
                            authors, year, venue, src_url, token_count, parse_source
GET /arxiv/{id}/brief    -> same as head
GET /arxiv/{id}/sections -> paper_id, title, sections[], token_count
GET /arxiv/{id}/full     -> complete paper object
GET /pmc/{id}/head       -> same as arxiv head (pmc_id populated)
GET /pmc/{id}/full       -> complete paper object
GET /arxiv/search?q=&limit= -> { total, results: [head-shaped objects] }
```

**Open question — resolve before Phase 4:** Verify `citations` vs `references` field name by running `grep "citations\|references" deepxiv_sdk/reader.py` against cloned SDK.

---

## 3. Architecture Build Order

Dependencies are strict — this is the critical path.

```
Phase 1: Foundation
  DB schema (papers, paper_sources, id_map, crawl_state) + Redis + Celery skeleton
  Everything else depends on this. Schema is hardest to change later.

Phase 2: Ingestion / Crawlers
  arXiv OAI-PMH crawler + LaTeX .tar.gz asset download
  PMC OAI-PMH crawler + JATS XML extraction
  Must exist before parsers have input.

Phase 3: Parser Layer (can develop in parallel once Phase 2 is running)
  3a. s2orc-doc2json TEX2JSON (arXiv LaTeX fast path)
  3b. s2orc-doc2json JATS2JSON (PMC JATS fast path)
  3c. MinerU PDF path + GROBID reference extraction companion

Phase 4: Normalizer + Storage Upsert
  Map all parser outputs to unified PaperJSON schema
  Compute token_count (tiktoken), generate tldr fallback, compute dedup fingerprint
  Upsert to papers table via canonical_id
  This is the correctness gate — wrong field names here break the SDK.

Phase 5: FastAPI REST Layer
  Serve all endpoint shapes from populated DB
  Redis caching layer (TTL 3600s paper views, 300s search)

Phase 6: deepxiv_sdk Fork + Contract Verification
  Update base_url, run SDK test suite against backend
  Add local caching extension (lowest-risk new capability)

Phase 7 (parallel): Benchmark Evaluation
  MinerU vs GROBID vs Docling on sample arXiv PDFs
  Must include 2-column IEEE/ACM papers in test set
  Can start as soon as Phase 3c parsers are running
```

Critical path: 1 -> 2 -> 3 -> 4 -> 5 -> 6. Phase 7 is parallel.

---

## 4. Top 5 Critical Pitfalls

**P1 — arXiv IP Ban (CRITICAL — 4-week timeline killer)**
Silent ban after exceeding 3 req/sec. Manifests as 403 or connection reset with no "banned" message. Prevention: Set User-Agent header on every request (documented arXiv requirement), token-bucket rate limiter, use OAI-PMH feed for bulk (not search API), exponential backoff with jitter. Monitor for 503 -> 403 -> connection-reset escalation in logs.

**P2 — deepxiv_sdk Silent Empty Responses on Field Name Mismatch (CRITICAL)**
SDK returns None/[] not exceptions when field names differ. HTTP 200 masks the breakage completely. Prevention: Read deepxiv_sdk/reader.py and extract every accessed key BEFORE writing any backend code. Integration tests must assert non-empty content values, not just HTTP status codes.

**P3 — Multi-Column PDF Layout Garbles Section Text (HIGH)**
Two-column papers cause all ML parsers to interleave column A and B sentences. Silent — output looks structurally valid. Prevention: Prefer LaTeX source over PDF (solves ~65% of arXiv papers). Post-parse sanity check: avg words/sentence >80 or >2% mid-word hyphens -> set parse_quality = degraded.

**P4 — Schema Design Wrong Before Bulk Load (HIGH)**
jsonb-only storage causes full table scans at section-query time. arXiv ID version suffixes (v2, v3) create duplicate records. Missing id_map cross-reference table means same paper ingested twice as separate arXiv + PMC rows. Prevention: Hybrid schema (structured columns + JSONB content), separate sections indexing, UUID canonical_id, normalize arXiv IDs on ingest (strip version suffix). Must be locked in before ingestion begins.

**P5 — PMC OAI-PMH resumptionToken Expiry (HIGH)**
Token expires in ~24 hours if harvest pauses between pages. Next request returns badResumptionToken; harvest silently loses the tail of the result set. Prevention: Separate harvest phase (page all IDs fast, <1s between pages) from processing phase. Log completeListSize from first response and verify final record count against it.

**Additional moderate pitfalls to track:**
- LaTeX unexpanded macros: >2% backslash tokens in section body -> set macro_expansion_failed, flag parse quality
- tldr / token_count must always be present as keys (never omit from response, even if value is null)
- Celery retry storms: max_retries=3, time_limit per task type (ML parse: 5min, LaTeX/XML: 60s)
- Scanned PDFs silently routed to text extractor: pre-check text layer with pymupdf before routing

---

## 5. V1 Scope vs Deferred

### In Scope for V1

- Continuous arXiv OAI-PMH ingestion + LaTeX .tar.gz fetch + TEX2JSON parsing
- Continuous PMC OAI-PMH ingestion + JATS2JSON parsing
- MinerU PDF fallback path for papers with no source available
- GROBID companion for reference extraction
- PostgreSQL hybrid schema (structured columns + JSONB content blob)
- All 7 API endpoints: /arxiv/{id}/(head|brief|sections|full), /pmc/{id}/(head|full), /arxiv/search
- SDK field contract: title, abstract, authors, tldr (null OK), src_url, token_count, sections, citations
- Redis API response caching
- deepxiv_sdk fork with base_url redirect + local caching extension
- Parser benchmark evaluation (MinerU vs GROBID vs Docling on 2-column test set)
- parse_source provenance field and parse_quality degradation flags

### Deferred to Post-MVP / V2

- Inline cite_spans, ref_spans, eq_spans within paragraph text (return empty arrays in v1)
- Per-paragraph body structure (sections return flat text string in v1)
- Table HTML rendering (html field in ref_entries.TABREF0)
- tldr population via external API (return null or first-2-sentences fallback in v1)
- Author affiliation / ORCID disambiguation
- Figure image extraction (caption text + label only in v1)
- Automatic citation cross-resolution to external paper IDs
- Semantic / vector search
- Kubernetes or multi-machine deployment

---

## 6. Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack choices | MEDIUM-HIGH | FastAPI/Postgres/Celery/Redis are stable LTS. MinerU version series changed rapidly — verify on PyPI before pinning. s2orc-doc2json has no PyPI release; track GitHub HEAD. |
| JSON schema contract | MEDIUM-HIGH | Core SDK fields derived from documented SDK source patterns. Must verify citations vs references naming by cloning SDK before Phase 4. |
| Architecture patterns | HIGH | arXiv OAI-PMH, PMC FTP/OAI, GROBID, S2ORC all have stable public documentation. Build order derived from hard dependencies. |
| Pitfall identification | HIGH | Rate limiting, resumptionToken, multi-column PDF, schema-first design are well-documented failure modes in this exact domain. |
| Parser quality / fidelity | LOW-MEDIUM | MinerU vs Docling quality gap on arXiv-specific layouts needs empirical validation in Phase 7 benchmark. |

**Gaps to address during development:**
1. Clone deepxiv_sdk and verify all field names before Phase 4 normalizer is built
2. Verify MinerU PyPI version and install path before Phase 3c
3. Empirically measure LaTeX source availability rate on target paper set (assumed ~65%)
