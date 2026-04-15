# Phase 4: Normalizer + Storage - Context

**Gathered:** 2026-04-15
**Status:** Ready for planning

<domain>
## Phase Boundary

Map all parser outputs (S2ORC JSON from TEX2JSON/JATS2JSON, MinerU content_list JSON, GROBID TEI XML) to the unified PaperJSON schema with exact deepxiv_sdk field names, compute token counts and tldr, populate dedup fingerprints, cross-link cross-source IDs via id_map, and upsert to PostgreSQL. Also fix the GROBID primary-path gap discovered in Phase 3 (wrong endpoint used). Phase 5 (REST API) reads directly from what this phase writes.

</domain>

<decisions>
## Implementation Decisions

### Normalization trigger
- **D-01:** Append `normalize_paper.si(paper_id, parse_source)` to every parser chain in `router.py` — normalization runs automatically at the end of each parse chain, no separate trigger needed.
- The existing `normalize_paper` stub in `app/tasks/normalize.py` is the target; implement it fully here.

### MinerU sections reconstruction
- **D-02:** Rule-based hierarchy from `sec_num` field — count dots in the section number string to determine depth (`"1.2.3"` = 2 dots = depth 3). `"title"` type blocks with no sec_num get `sec_num: null`. Flat `"text"` blocks between headings are grouped under the preceding `"title"` block. Result: a proper `sections[]` array with nested structure, not a flat blob.
- `text_level_broken: True` flag (set by Phase 3) signals this reconstruction path.

### GROBID endpoint fix (primary path)
- **D-03:** Two modes in `app/parsers/grobid.py`:
  - `extract_references(pdf_path)` — existing function, calls `/api/processReferences`, citation-only, used as secondary enrichment step.
  - `extract_fulltext(pdf_path)` — new function, calls `/api/processFulltextDocument`, returns body text + sections + citations as TEI XML; parsed into sections and citations together.
- In `parse_pdf_grobid` task: detect primary vs secondary mode by checking `ps.parse_status == "cascade_to_pdf_grobid"`. If primary → call `extract_fulltext()`, populate sections + citations. If secondary → call `extract_references()`, merge citations only (existing behavior).
- This fixes the gap where D-03-routed papers had citations but no body text.

### Citation graph population
- **D-04:** Normalizer writes citation rows to `paper_citations` table during the normalize step.
  - `target_arxiv_id` and `target_doi` stored as raw strings from GROBID output.
  - `target_paper_id` resolved via `id_map` lookup (match on arxiv_id or doi) — set if found in corpus, left `NULL` otherwise.
  - Upsert pattern: `ON CONFLICT (source_paper_id, target_arxiv_id)` update `context_text`.

### Schema field mapping
- **D-05:** Before writing normalizer code, grep deepxiv_sdk for accessed field names (plan 04-01 specifies this). All field names in `paper.content` JSONB blob must exactly match SDK expectations.
- Required top-level keys always present (never omitted): `title`, `abstract`, `authors`, `sections`, `citations`, `tldr`, `src_url`, `token_count`, `parse_source`.
- `tldr`: first 2–3 sentences of abstract via sentence splitter (deterministic fallback, v1 only).
- `token_count`: tiktoken cl100k_base on concatenated full section text.
- `src_url`: arXiv papers → `https://arxiv.org/abs/{arxiv_id}`; PMC papers → `https://www.ncbi.nlm.nih.gov/pmc/articles/{pmc_id}/`.

### Dedup fingerprint
- **D-06:** SHA-256 of `(normalized_title + "|" + first_author_last_name + "|" + year)` where normalization = lowercase + strip non-alphanumeric. Stored in `paper.content["dedup_fingerprint"]`. If any of the three fields is missing, fingerprint is skipped (not computed). Cross-source match: look up fingerprint in existing papers; if match found, link via `id_map` instead of creating duplicate.

### Claude's Discretion
- TEI XML parsing strategy for GROBID fulltext (lxml vs ElementTree vs regex)
- Exact sentence splitter for tldr (re-based split on `. ` boundary is fine)
- Error handling for malformed GROBID TEI responses
- Section `paragraphs` field shape within each section object

</decisions>

<specifics>
## Specific Ideas

- The `text_level_broken: True` flag in MinerU output (set in Phase 3) is the signal to use the rule-based dot-counting reconstruction for sections.
- Phase 5 will run `SELECT content->'title', content->'sections', ...` directly — the JSONB blob shape is the API contract.
- deepxiv_sdk `Reader` field accesses must work before Phase 5 begins — success criterion 5 in ROADMAP.md requires testing against 5 stored papers.

</specifics>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Schema contract
- `.planning/REQUIREMENTS.md` §Normalization — NORM-01 through NORM-06, exact field names and shapes required
- `.planning/ROADMAP.md` §Phase 4 — 3-plan breakdown and success criteria (especially criterion 5: SDK field access test)

### Parser output formats (what normalizer consumes)
- `app/tasks/parse.py` — `parse_latex`, `parse_jats`, `parse_pdf_mineru`, `parse_pdf_grobid` tasks; understand what each sets in `paper.content` before normalizing
- `app/tasks/parse_helpers.py` — helper functions for context
- `app/parsers/grobid.py` — existing `extract_references()` to understand before adding `extract_fulltext()`

### Storage targets
- `app/models.py` — `Paper`, `PaperSource`, `IdMap`, `PaperCitation` ORM models; understand columns before upsert
- `app/db.py` — SessionLocal factory pattern used by all tasks

### Chain wiring target
- `app/tasks/router.py` — `_build_parse_chain()` function; D-01 requires appending `normalize_paper.si()` here

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `app/tasks/normalize.py`: stub `normalize_paper(paper_id, parse_source)` task — implement this fully, don't create a new file
- `app/parsers/grobid.py`: existing `extract_references()` — add `extract_fulltext()` alongside it
- `app/tasks/parse_helpers.py`: `_strip_jats_doctype()`, `_sentence_length_degraded()` — may be useful in normalizer

### Established Patterns
- All tasks: lazy imports inside function body (fast-worker safety, established in Phase 3)
- All tasks: `raise self.retry(exc=exc)` in except block (not bare `self.retry()`)
- All tasks: `session = SessionLocal()` with try/finally `session.close()`
- Router chains use `.si()` immutable signatures — `normalize_paper.si(paper_id, parse_source)` must follow the same pattern

### Integration Points
- `router.py:_build_parse_chain()` — append normalize task here (D-01)
- `Paper.content` JSONB column — this is where the full PaperJSON blob lives
- `Paper.token_count`, `Paper.tldr`, `Paper.parse_source`, `Paper.parse_quality` — also stored as top-level columns (not just in JSONB) for fast SQL queries
- `PaperCitation` table — written by normalizer, read by Phase 5 citation graph endpoints

</code_context>

<deferred>
## Deferred Ideas

- S2 TLDR API or local model for tldr generation — v2 (SDK-V2-02), out of scope for Phase 4
- pgvector embeddings population — not in Phase 4 scope (embeddings column exists but stays null)
- Inline cite_spans / eq_spans within paragraph text — v2 (EXT-01), sections return flat text in v1
- Table HTML rendering — v2 (EXT-03), table caption + content string is sufficient for v1

</deferred>

---

*Phase: 04-normalizer-storage*
*Context gathered: 2026-04-15*
