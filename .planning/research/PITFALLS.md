# Domain Pitfalls

**Domain:** Academic paper processing pipeline (arXiv + PMC ingestion, multi-parser routing, deepxiv_sdk compatibility)
**Researched:** 2026-04-13

---

## Critical Pitfalls

### Pitfall 1: Multi-Column PDF Layout Breaks All Three ML Parsers

**What goes wrong:** Two-column IEEE/ACM/Nature-style PDFs cause MinerU, GROBID, and Docling to mis-sequence text. Reading-order detection treats columns as a wide block, interleaving sentences from column A and column B mid-word. No error is thrown — the output looks structurally valid.

**Why it happens:** PDF content streams store glyphs in draw order, not reading order. Two-column papers interleave left/right glyph sequences in the raw PDF.

**Consequences:** Section text for affected papers is permanently garbled in the database. Silent — HTTP 200, no exception.

**Prevention:**
- Always prefer LaTeX source over PDF for arXiv papers. ML parsers are fallback-only.
- Post-parse sanity check: if `avg_words_per_sentence > 80` or >2% of tokens start with mid-word hyphens, flag `parse_quality = degraded`.
- Benchmark phase must include two-column IEEE/ACM papers in the test set.
- Store `parse_quality` and `parse_method` fields in the schema from day one.

**Warning signs:** Average sentence length >80 tokens. Paragraph breaks at unusual positions with mid-word hyphen continuations.

**Phase:** Benchmark evaluation + schema design.

**Confidence:** HIGH

---

### Pitfall 2: arXiv LaTeX Source — Unexpanded Custom Macros Pollute Section Text

**What goes wrong:** arXiv papers define custom macros in separate files (`macros.tex`, `defs.tex`). LaTeXML and s2orc-doc2json guess the main `.tex` file by heuristic. When they start from the wrong root, `\input` chains fail silently, leaving raw LaTeX commands like `\bm{x}`, `\citet{foo}` unexpanded in section text.

**Why it happens:** arXiv `.tar.gz` source archives have no canonical "main file" metadata.

**Consequences:** Section text contains raw LaTeX command strings. Text search fails. NLP downstream tasks degrade.

**Prevention:**
- Pass the full extracted directory to s2orc-doc2json so it can resolve `\input` chains.
- Post-parse check: if more than 2% of tokens start with `\`, set `macro_expansion_failed = true` and `parse_quality = degraded`.

**Warning signs:** Backslash characters in section body text. `\bm`, `\mathbb`, `\citet`, `\newcommand` appearing in extracted text strings.

**Phase:** LaTeX parser implementation.

**Confidence:** HIGH

---

### Pitfall 3: arXiv API Rate Limiting — Silent IP Bans

**What goes wrong:** The arXiv API requires 1 request per 3 seconds minimum. Exceeding it gives HTTP 503, then a silent IP ban manifesting as 403 or connection reset — with no clear "you are banned" message. In a 4-week timeline, a 3-day IP ban is catastrophic.

**Prevention:**
- Set `User-Agent: YourProjectName/1.0 (contact@youremail.edu)` on every request — documented arXiv requirement.
- Enforce a 3-second minimum between arXiv API requests using a token bucket.
- For continuous ingestion, use arXiv **OAI-PMH** feed (`export.arxiv.org/oai2`) — designed for daily harvesting, not the search API.
- For bulk initial seeding, use arXiv S3 bulk data (requester-pays) or bulk access program.
- Implement exponential backoff with jitter on 503/429/403.
- Reserve the search API exclusively for user-facing queries.

**Warning signs:** HTTP 503 in logs, then 403, then connection reset from export.arxiv.org.

**Phase:** Crawler implementation — highest-consequence operational pitfall given 4-week timeline.

**Confidence:** HIGH

---

### Pitfall 4: deepxiv_sdk Field Name Mismatches — Silent Empty Responses

**What goes wrong:** deepxiv_sdk's `Reader` class accesses response JSON by exact field names. If your backend returns `section_title` where the SDK expects `heading`, or `body` where it expects `text`, the SDK returns `None` or `[]` rather than raising an exception. HTTP 200, no errors — but all content fields are empty.

**Prevention:**
- **Before writing any backend code**: read `deepxiv_sdk/reader.py` and extract every field name accessed via dict key. Build a reference schema document from SDK source.
- Write integration tests that call every SDK method and assert non-None, non-empty values — not just HTTP status code.
- Run the SDK's own test suite against your backend on every commit.
- Critical fields: `title`, `abstract`, `sections` (list of `{heading, text}`), `tldr`, `citations`, `src_url`, `token_count`.

**Warning signs:** `Reader.sections()` returns `[]`. `Reader.head()` title is None. All SDK content methods return empty values while API returns HTTP 200.

**Phase:** Schema design (resolve before writing backend code). SDK fork phase.

**Confidence:** MEDIUM (field names require SDK source inspection; failure mode pattern is HIGH confidence)

---

### Pitfall 5: PostgreSQL jsonb-Only Schema Prevents Efficient Section Queries

**What goes wrong:** Storing the full paper JSON as a single `jsonb` column makes section-level queries require full table scans. At thousands of papers, `GET /arxiv/{id}/sections` becomes slow. Schema migrations after bulk load are expensive.

**Prevention:**
- Hybrid schema from day one: structured columns for queriable fields (`arxiv_id`, `pmcid`, `title`, `abstract`, `parse_quality`, `parse_method`) plus `content jsonb` for full payload.
- Separate `sections` table: `(paper_id, section_index, heading, body_text, section_type)`.
- GIN index on `content jsonb` if needed. B-tree indexes on `arxiv_id`, `pmcid`.

**Warning signs:** `EXPLAIN` showing `Seq Scan` on large jsonb column. API response times >500ms at >5k papers.

**Phase:** Storage schema design — must be decided before ingestion begins.

**Confidence:** HIGH

---

### Pitfall 6: PMC OAI-PMH `resumptionToken` Expiry Breaks Bulk Harvests Mid-Way

**What goes wrong:** PMC OAI-PMH pagination uses a `resumptionToken` with server-side expiry (~24 hours, unguaranteed). If your harvester pauses between pages to process records, the token expires. The next request returns `badResumptionToken` and the harvest must restart. The database appears complete but is missing the tail of the result set — silently.

**Prevention:**
- Separate harvesting (OAI-PMH pagination) from processing (parsing). Harvest all IDs/metadata first (fast); store in `pending_papers` queue; process in second pass.
- Keep OAI-PMH page requests continuous with <1 second between pages.
- Log `completeListSize` from first OAI response; verify final count against it.
- For daily updates, use `from`/`until` date parameters — keeps page counts small.

**Warning signs:** `badResumptionToken` in OAI-PMH response XML. Final record count significantly less than `completeListSize`.

**Phase:** PMC crawler implementation.

**Confidence:** HIGH

---

## Moderate Pitfalls

### Pitfall 7: Scanned vs Born-Digital PDFs Treated the Same

**What goes wrong:** Scanned PDFs (image-only, no text layer) are silently routed to text-extraction parsers. GROBID returns near-empty results with no error. No quality flag distinguishes OCR text from directly-extracted text.

**Prevention:**
- Pre-check: use `pymupdf` to attempt raw text extraction from first two pages. If character count <100, classify as `scanned`, route to OCR path, set `parse_method = ocr_fallback`.

**Warning signs:** Empty body_text on legitimate publications. `section_count = 0` on multi-section papers.

**Phase:** PDF parser routing logic.

**Confidence:** HIGH

---

### Pitfall 8: JATS XML Schema Version Variations — Silent Missing Content

**What goes wrong:** PMC distributes JATS XML in multiple schema versions (JATS 1.0, 1.1, 1.2, NLM DTD 2.x legacy). Element names for figure captions, table footnotes differ across versions. s2orc-doc2json targets a specific version; older papers parse without error but miss content.

**Prevention:**
- Read the `<!DOCTYPE>` declaration in each JATS XML file before parsing. Map DTD version to parser variant.
- For NLM DTD 2.x files, apply official NLM XSLT migration stylesheets to normalize to JATS 1.1 before parsing.
- Store `jats_schema_version` in paper record for debugging.

**Phase:** PMC XML parser implementation.

**Confidence:** MEDIUM

---

### Pitfall 9: arXiv ID Versioning — Version Suffix Produces Duplicate Records

**What goes wrong:** arXiv IDs come with and without version suffixes (`2301.12345` vs `2301.12345v2`). Different ingestion sources return the same paper with different version annotations, producing duplicate database records.

**Prevention:**
- Normalize all arXiv IDs on ingest: strip version suffix, store canonical ID as primary key, store version as `arxiv_version` column.
- Explicit policy: overwrite on newer version (re-parse, replace).

**Phase:** Schema design + crawler.

**Confidence:** HIGH

---

### Pitfall 10: arXiv + PMC ID Cross-Reference — Same Paper, No Link

**What goes wrong:** Many arXiv papers are also published in journals with PMC full-text XML. Without a cross-reference table, the API cannot answer "given arXiv ID X, is there a PMC version?" — losing significant value.

**Prevention:**
- Create a `paper_identifiers` table: `(paper_id UUID, id_type, id_value)` with id_type in `{arxiv_id, pmcid, doi, pubmed_id}`.
- Use internal UUID as primary key; map all external IDs through `paper_identifiers`.

**Phase:** Storage schema design — must be in initial schema.

**Confidence:** HIGH

---

### Pitfall 11: Math Environments — Silent Drops or Raw LaTeX in Section Text

**What goes wrong:** Inline math (`$...$`) and display math are either stripped entirely or left as raw LaTeX strings. No policy decision means inconsistent behavior across papers.

**Prevention:**
- Decide math representation policy before building any parser: keep raw LaTeX (recommended — reversible). Never silently drop math blocks — always use a `[MATH]` placeholder at minimum.
- Store `contains_math` boolean on each section record.

**Phase:** LaTeX parser implementation.

**Confidence:** HIGH

---

### Pitfall 12: Celery Retry Storms on ML Parser Failures

**What goes wrong:** MinerU and Docling occasionally crash, time out, or OOM on specific papers. Without `max_retries` and task timeouts, the same paper retries indefinitely, consuming queue capacity.

**Prevention:**
- `max_retries = 3` on all parsing tasks. After 3 failures, set `parse_status = failed`.
- `time_limit` on Celery tasks: PDF ML parsing ≤5 minutes; LaTeX/XML parsing ≤60 seconds.
- Two priority queues: `fast` (LaTeX/XML) and `slow` (PDF ML parsing).

**Phase:** Job queue implementation.

**Confidence:** HIGH

---

### Pitfall 13: `tldr` and `token_count` — SDK May Fail on Absent Keys

**What goes wrong:** deepxiv_sdk expects `tldr` and `token_count` in responses. If your backend omits these keys entirely (vs. returning `null`), SDK attribute access may raise `KeyError` rather than returning `None`.

**Prevention:**
- `token_count`: Always populate using `tiktoken` on the full extracted text. Never null.
- `tldr`: Return first two sentences of abstract as deterministic fallback, or return `null` — but always include the key in the JSON response (never omit).

**Phase:** SDK compatibility verification.

**Confidence:** MEDIUM

---

## Phase-Specific Warnings Summary

| Phase Topic | Pitfall | Priority |
|-------------|---------|----------|
| arXiv crawler design | Rate limit ban (P3) — silent IP ban, 4-week timeline killer | CRITICAL |
| arXiv crawler design | Wrong access method for bulk — use OAI-PMH not search API | HIGH |
| PMC crawler design | resumptionToken expiry (P6) — separate harvest from processing | HIGH |
| Storage schema | jsonb-only schema (P5) — sections table + structured columns from day one | HIGH |
| Storage schema | Missing ID cross-reference (P10) — paper_identifiers table, UUID primary key | HIGH |
| Storage schema | arXiv version duplication (P9) — normalize on ingest | HIGH |
| SDK compatibility | Field name mismatches (P4) — read SDK source before writing backend | CRITICAL |
| SDK compatibility | Missing keys vs null (P13) — always include keys in response JSON | MEDIUM |
| LaTeX parser | Unexpanded macros (P2) — detect root file, backslash post-check | HIGH |
| LaTeX parser | Math environment policy (P11) — decide before building, never silent-drop | HIGH |
| PDF parser | Multi-column layouts (P1) — benchmark must include 2-column papers | HIGH |
| PDF parser | Scanned vs born-digital (P7) — pre-check text layer before routing | MEDIUM |
| PMC XML parser | JATS schema versions (P8) — read DOCTYPE, normalize old schemas | MEDIUM |
| Job queue | Retry storms (P12) — max_retries=3, time_limit, fast/slow queues | MEDIUM |
