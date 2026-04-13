# Architecture: Academic Paper Processing Pipeline

**Domain:** Academic paper ingestion, parsing, storage, and serving
**Researched:** 2026-04-13
**Confidence:** MEDIUM-HIGH (S2ORC paper, arXiv OAI-PMH, PMC FTP, GROBID, MinerU are stable well-documented systems)

---

## Component Diagram

```
INGESTION LAYER
  arXiv Crawler ──────────────────────────────┐
    • OAI-PMH daily (export.arxiv.org/oai2)   │
    • LaTeX .tar.gz per-paper fetch            │──→ Job Queue (Redis + Celery)
    • S3 bulk (s3://arxiv-dataset/) for seed  │
  PMC Crawler ────────────────────────────────┘
    • OAI-PMH daily (ncbi.nlm.nih.gov/pmc/oai)
    • FTP bulk seed (ftp.ncbi.nlm.nih.gov/pub/pmc/oa_bulk/)

ROUTING LAYER
  Job Queue → Smart Router
    IF latex_tar available → TEX2JSON (s2orc-doc2json)
    IF jats_xml available  → JATS2JSON (s2orc-doc2json)
    IF pdf only            → MinerU (primary) / GROBID (fallback)

NORMALIZATION LAYER
  Parser output → Normalizer
    • Map to PaperJSON schema (deepxiv_sdk field names)
    • Compute dedup fingerprint (SHA-256 of title+author+year)
    • Cross-link IDs via id_map

STORAGE LAYER
  PostgreSQL: papers, paper_sources, id_map, crawl_state tables
  Redis: Celery broker + API response cache (TTL 1h)

SERVE LAYER
  FastAPI: /arxiv/{id}/head, /brief, /sections, /search; /pmc/{id}/head, /full
  deepxiv_sdk fork → points at FastAPI backend
```

---

## Data Flow (arXiv feed → REST API response)

**Step 1 — Discovery:** OAI-PMH ListRecords with `metadataPrefix=arXiv`, `from=yesterday`. Returns XML records with IDs and metadata. Crawler enqueues `process_paper("arxiv", "2404.XXXXX")`.

**Step 2 — Asset Fetch:** Celery worker hits `https://export.arxiv.org/e-print/{id}`. `Content-Type` header reveals whether response is `.tar.gz` (LaTeX source, ~65% of papers) or raw PDF. Both saved to local disk.

**Step 3 — Routing:** Smart Router checks `available_assets`: `latex_tar` → TEX2JSON; `jats_xml` → JATS2JSON; `pdf` → MinerU → GROBID fallback.

**Step 4 — Parsing:** TEX2JSON unpacks .tar.gz, finds main .tex file (largest file with `\documentclass`), runs s2orc-doc2json. Returns `{title, abstract, authors, body_text[], bib_entries{}}`.

**Step 5 — Normalization:** Maps raw dict to PaperJSON: builds `sections` list `[{heading, text, section_type, order_idx}]`, computes `token_count` (tiktoken cl100k), generates `tldr` (first 2-3 abstract sentences for SDK compat), computes dedup fingerprint, checks for DOI-based cross-references.

**Step 6 — Storage:** Upsert to `papers` table (ON CONFLICT DO UPDATE). Insert to `id_map`. Insert to `paper_sources` with `parse_status="success"`.

**Step 7 — Serve:** `GET /arxiv/2404.XXXXX/sections` → check Redis cache (key `papers:arxiv:2404.XXXXX:sections`, TTL 3600s) → cache miss → `SELECT content_json FROM papers WHERE arxiv_id=...` → set cache → return. Target: <100ms cache hit, <500ms DB hit.

---

## Data Model (PostgreSQL schema)

**Table `papers`** (primary):
```sql
id               BIGSERIAL PK
canonical_id     TEXT UNIQUE          -- "arxiv:2404.XXXXX" or "pmc:PMC1234567"
arxiv_id         TEXT UNIQUE          -- "2404.XXXXX"
pmcid            TEXT UNIQUE          -- "PMC1234567"
doi              TEXT
title            TEXT NOT NULL
abstract         TEXT
authors          JSONB                -- [{name, affiliations[], orcid}]
year             INTEGER
published_date   DATE
venue            TEXT
tldr             TEXT                 -- synthetic: first 2-3 abstract sentences
token_count      INTEGER
sections         JSONB                -- [{heading, text, section_type, order_idx}]
tables           JSONB                -- [{caption, headers[], rows[[]]}]
figures          JSONB                -- [{caption, fig_id, src_url}]
references       JSONB                -- [{title, authors, year, doi, arxiv_id}]
src_url          TEXT                 -- canonical URL (arxiv abs page)
parser_used      TEXT                 -- "tex2json"|"jats2json"|"mineru"|"grobid"
parse_quality    SMALLINT             -- 1-5
dedup_fingerprint TEXT
ingested_at      TIMESTAMPTZ
updated_at       TIMESTAMPTZ
raw_asset_path   TEXT
```

Indexes: `arxiv_id`, `pmcid`, `doi`, `year`, `ingested_at`, GIN on `to_tsvector(title || abstract)` for full-text search.

**Table `paper_sources`:** tracks raw assets per paper — asset_path, asset_type, parse_status (`pending|success|failed|skipped`), parse_error, parsed_at. `UNIQUE(source, source_id)` enables idempotent upsert.

**Table `id_map`:** `arxiv_id`, `doi`, `pmcid`, `pubmed_id`, `s2_id` all pointing to a `canonical_id`. Index on `doi` for cross-source merging.

**Table `crawl_state`:** `source PK`, `last_harvest_date`, `last_run_at`, `papers_added`, `papers_failed`. Enables resumable OAI-PMH harvests.

**Redis keys:** `papers:{canonical_id}:{view}` (TTL 3600s), `search:{query_hash}` (TTL 300s).

---

## arXiv Bulk Access Mechanisms

**Confidence: HIGH**

1. **OAI-PMH daily feed** — `https://export.arxiv.org/oai2?verb=ListRecords&metadataPrefix=arXiv&from=YYYY-MM-DD&until=YYYY-MM-DD`. Metadata only. Follow resumptionTokens. 3-second delay between requests.

2. **LaTeX source per-paper** — `https://export.arxiv.org/e-print/{id}`. Check `Content-Type` response header:
   - `application/x-eprint-tar` = LaTeX available → save .tar.gz → route to TEX2JSON
   - `application/pdf` = PDF-only paper → route to MinerU
   - ~65% of arXiv papers have LaTeX source.

3. **S3 bulk snapshot** (seed only) — `s3://arxiv-dataset/` (AWS Open Data, requester-pays). `src/` = LaTeX, `pdf/` = PDFs. Use once for historical bootstrap; OAI-PMH for daily thereafter.

---

## PMC Bulk Access Mechanisms

**Confidence: HIGH**

1. **OAI-PMH with `metadataPrefix=pmc`** — `https://www.ncbi.nlm.nih.gov/pmc/oai/oai.cgi?verb=ListRecords&metadataPrefix=pmc&from=YYYY-MM-DD&set=pmc-open`. Returns **full JATS XML inline** in the OAI response — no separate asset download needed. 3 req/sec with free NCBI API key; 1 req/sec without.

2. **FTP bulk** — `ftp.ncbi.nlm.nih.gov/pub/pmc/oa_bulk/`. Subdirs: `oa_comm/`, `oa_noncomm/`, `oa_other/`. Index: `oa_file_list.csv` (PMCID → .tar.gz filename + license). Each .tar.gz = `.nxml` JATS file + figure images. Updated weekly. Use for initial seed.

3. **eFetch per-paper** — `https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=pmc&id={PMCID}&rettype=xml`. For small-scale or on-demand lookups only.

---

## Smart Routing: Asset Detection

```python
resp = requests.get(f"https://export.arxiv.org/e-print/{arxiv_id}", stream=True)
if resp.headers["Content-Type"] == "application/x-eprint-tar":
    # LaTeX source available — save .tar.gz → route to TEX2JSON
elif resp.headers["Content-Type"] == "application/pdf":
    # PDF only — save .pdf → route to MinerU
```

For PMC: presence of `.nxml` in the .tar.gz (or inline in OAI response with `metadataPrefix=pmc`) signals JATS path. If the OAI record has full XML inline, no separate asset download needed.

---

## ID Unification

1. Canonical ID = `"arxiv:{id}"` or `"pmc:{pmcid}"` — prefixed, stored in `papers.canonical_id`
2. `id_map` table: all alternate IDs (DOI, PubMed ID, S2 ID) point back to canonical
3. API resolution: any input ID → `id_map` lookup → canonical → `papers` row
4. Dedup merge: if incoming PMC paper's DOI matches existing arXiv paper → update `id_map`, no duplicate
5. arXiv ID formats: pre-2007 `cond-mat/0612585`; post-2007 `1703.10593` — store verbatim, normalize for comparison

---

## Suggested Build Order

```
Phase 1: DB schema + Redis + Celery skeleton
  (everything else depends on this)

Phase 2: Crawlers + asset download
  (must exist before anything can be parsed)

Phase 3: Parsers (TEX2JSON, JATS2JSON, MinerU/GROBID)
  (can be developed in parallel once Phase 2 exists)

Phase 4: Normalizer + storage upsert
  (enforces SDK JSON contract — critical correctness gate)

Phase 5: FastAPI REST layer
  (depends on populated DB from Phase 4)

Phase 6: deepxiv_sdk fork + contract verification
  (depends on Phase 5 passing SDK test suite)

Phase 7: Benchmark (MinerU vs GROBID vs Docling)
  (parallel track — can start as soon as Phase 3 parsers work)
```

**Critical path:** 1 → 2 → 3 → 4 → 5 → 6. Phase 7 is parallel.

The SDK fork (Phase 6) cannot be verified until the API (Phase 5) serves the exact JSON field names deepxiv_sdk's `Reader` class expects: `title`, `abstract`, `sections`, `tldr`, `citations`, `src_url`, `token_count`.

---

## Architecture-Specific Pitfalls

- **On-demand parsing is a trap**: never trigger MinerU/GROBID at request time — 5-30s latency kills the API
- **OAI-PMH resumption token loss**: always persist token to `crawl_state` after each page
- **arXiv .tar.gz multi-file detection**: heuristic for main file (largest with `\documentclass`, or look for `\begin{document}`) must be implemented carefully
- **JATS XML variant drift**: PMC JATS XML is not perfectly uniform; normalizer must handle missing optional fields gracefully
- **PostgreSQL JSONB vs text columns**: store parsed arrays as JSONB not TEXT JSON — enables `->` operator queries and GIN indexing
