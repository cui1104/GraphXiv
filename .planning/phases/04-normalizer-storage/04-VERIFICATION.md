---
phase: 04-normalizer-storage
verified: 2026-04-15T22:00:00Z
status: passed
score: 9/9 must-haves verified
re_verification: false
gaps: []
human_verification:
  - test: "Run normalize_paper end-to-end against a real parsed paper in Docker"
    expected: "paper.token_count > 0, paper.tldr non-null, paper.content.dedup_fingerprint is 64-char hex"
    why_human: "Requires live PostgreSQL + Celery worker; can't verify DB upsert path programmatically"
  - test: "Verify citation upsert with id_map resolution after two papers cite the same arXiv ID"
    expected: "target_paper_id is non-null in paper_citations after both papers are normalized"
    why_human: "Requires two real papers in DB with overlapping citation targets"
---

# Phase 4: Normalizer-Storage Verification Report

**Phase Goal:** Every parser output is mapped to the exact deepxiv_sdk JSON field names and upserted to PostgreSQL, with token counts, tldr, dedup fingerprints, and cross-source ID links all populated.
**Verified:** 2026-04-15T22:00:00Z
**Status:** PASSED
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|---------|
| 1 | S2ORC JSON is normalized into sections with heading/sec_num/text/paragraphs/token_count | VERIFIED | `_normalize_s2orc` groups consecutive body_text blocks by (section, sec_num); test_normalize_s2orc passes |
| 2 | MinerU content_list is reconstructed into sections via title/text hierarchy | VERIFIED | `_normalize_mineru` iterates content_list; no-title fallback implemented (Pitfall 2); test_normalize_mineru passes |
| 3 | GROBID fulltext TEI is normalized into sections using grobid_sections | VERIFIED | `_normalize_grobid_fulltext` reads grobid_sections; `_parse_tei_fulltext_sections` parses TEI XML body into section dicts |
| 4 | token_count is always > 0 for papers with section text; key always present | VERIFIED | `_add_token_count` uses tiktoken cl100k_base; sets per-section and total; test_token_count passes |
| 5 | tldr key is always present (string or None, never missing) | VERIFIED | `_compute_tldr` always returns dict with "tldr" key; _add_tldr always writes it; test_tldr_always_present + test_tldr_content pass |
| 6 | SHA-256 dedup fingerprint is computed and cross-source matches are linked via id_map | VERIFIED | `_compute_dedup_fingerprint` produces 64-char hex; `_check_dedup_and_link` queries JSONB and inserts IdMap row; test_dedup_fingerprint passes |
| 7 | Citations are upserted to paper_citations with id_map resolution for target_paper_id | VERIFIED | `_upsert_citations` resolves target_paper_id via IdMap; uses ON CONFLICT on uq_paper_citations_source_target_arxiv; doi-only uses DO NOTHING |
| 8 | parse_quality is preserved from parser output into normalized content | VERIFIED | All three normalizer branches accept parse_quality param and return it in output dict; test_parse_quality passes |
| 9 | normalize_paper.si() is appended to every parser chain in router.py | VERIFIED | All 3 chains (arxiv, pmc, pdf) have normalize_paper.si() as final step; count verified programmatically |

**Score:** 9/9 truths verified

---

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `app/tasks/normalize.py` | Complete normalize_paper Celery task | VERIFIED | 747 lines; contains all required helper functions; not a stub |
| `app/tasks/router.py` | Updated chains with normalize_paper appended | VERIFIED | 163 lines; 3 normalize_paper.si() calls confirmed |
| `tests/test_normalize.py` | 12 test stubs covering NORM-01 to NORM-06 | VERIFIED | Exactly 12 test functions; 10 pass, 2 skip (integration) |
| `alembic/versions/0003_paper_citations_unique.py` | UNIQUE constraint migration | VERIFIED | Creates uq_paper_citations_source_target_arxiv on (source_paper_id, target_arxiv_id) |
| `app/parsers/grobid.py` | extract_fulltext + _parse_tei_fulltext_sections | VERIFIED | Both functions present; processFulltextDocument endpoint used; existing functions preserved |

---

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `app/tasks/normalize.py` | `app/parsers/grobid.py` | `_parse_tei_fulltext_sections` import | NOT REQUIRED | normalize.py does not call _parse_tei_fulltext_sections directly — grobid_sections arrive pre-parsed in paper.content from parse_pdf_grobid. The link is through parse.py which calls extract_fulltext. This is correct architecture. |
| `app/tasks/normalize.py` | `app/models.py` | Paper, PaperSource, PaperCitation, IdMap | VERIFIED | Lazy imports inside normalize_paper and helper functions; all four models used |
| `app/tasks/router.py` | `app/tasks/normalize.py` | normalize_paper.si() in chain | VERIFIED | `from app.tasks.normalize import normalize_paper` present; 3 chains confirmed |
| `app/tasks/normalize.py` | tiktoken | cl100k_base encoding | VERIFIED | `tiktoken.get_encoding("cl100k_base")` in `_add_token_count` and `_compute_token_count` |
| `app/tasks/parse.py` | `app/parsers/grobid.py` | import extract_fulltext | VERIFIED | `from app.parsers.grobid import extract_fulltext` in primary mode branch at line 449 |

---

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|------------|-------------|--------|---------|
| NORM-01 | 04-01, 04-02 | All parser outputs map to unified PaperJSON schema (title, abstract, authors, sections, citations, tldr, src_url, token_count, parse_source) | SATISFIED | `_normalize_s2orc`, `_normalize_mineru`, `_normalize_grobid_fulltext` all return dicts with deepxiv_sdk field names; tests pass |
| NORM-02 | 04-01, 04-02 | token_count always populated via tiktoken cl100k_base; key never omitted | SATISFIED | `_add_token_count` always sets paper_json["token_count"]; per-section token_count also set; tiktoken pre-cached in Docker |
| NORM-03 | 04-01, 04-02 | tldr always present as key (null or first 2-3 abstract sentences) | SATISFIED | `_compute_tldr` returns {"tldr": ...} always; splits on ". " with full-abstract fallback when no sentence boundary |
| NORM-04 | 04-01, 04-02 | SHA-256 dedup fingerprint; cross-source papers linked via id_map | SATISFIED | `_compute_dedup_fingerprint` produces sha256("{norm_title}\|{last_name}\|{year}"); `_check_dedup_and_link` inserts IdMap row on match |
| NORM-05 | 04-01, 04-02 | Section shape: {heading, sec_num, text, paragraphs, token_count}; Citation shape: {ref_id, title, authors, year, venue, doi, arxiv_id, raw_text} | SATISFIED | `_make_section` builds correct section shape; `_bib_entries_to_citations` and `_grobid_raw_to_citations` produce correct citation shape; test_section_shape + test_citation_shape pass |
| NORM-06 | 04-01, 04-02 | parse_quality stored for every paper with degradation flags | SATISFIED | All three normalizer branches accept parse_quality arg and include it in output; `_upsert_paper` writes it to DB; test_parse_quality passes |

All 6 NORM requirements satisfied. No orphaned requirements found (REQUIREMENTS.md traceability table marks all 6 as Complete in Phase 4).

---

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `app/tasks/normalize.py` | 338, 348 | `return []` in `_flatten_authors` | INFO | Legitimate guard clause for empty/non-list input; not a stub — function path produces real data for valid inputs |

No blocker or warning-level anti-patterns found. The `return []` hits are legitimate guard clauses in `_flatten_authors` for invalid input types, not stubs.

---

### Human Verification Required

#### 1. End-to-end normalize_paper DB upsert

**Test:** In Docker environment, ingest one arXiv paper, run the full parse chain, verify `paper.token_count > 0`, `paper.tldr` is a non-null string, `paper.content["dedup_fingerprint"]` is a 64-char hex string.
**Expected:** All three fields populated in the papers table row.
**Why human:** Requires live PostgreSQL + Celery worker + real parser output in paper.content JSONB.

#### 2. Citation upsert with id_map resolution

**Test:** Normalize two papers that both cite the same arXiv ID (e.g., "1706.03762"). Check `paper_citations.target_paper_id` is non-null when the cited paper is itself in the corpus.
**Expected:** `target_paper_id` resolved via IdMap lookup, not NULL.
**Why human:** Requires two real papers with overlapping citations already in the corpus.

---

### Verification Detail: Key Implementation Facts

**Pitfall 1 (stale parse_source argument):** Confirmed mitigated. Line 58 of normalize.py: `actual_parse_source = paper.parse_source` reads from DB; the router argument is only a hint.

**Pitfall 2 (MinerU no-title fallback):** Confirmed implemented. `_normalize_mineru` checks `has_titles = any(...)` and creates a single section with `heading=""` when no title blocks found.

**Pitfall 6 (author dict flattening):** Confirmed implemented. `_flatten_authors` handles both dict-style and string-style authors.

**D-03 primary mode:** Confirmed. `parse_pdf_grobid` in parse.py branches on `ps.parse_status == "cascade_to_pdf_grobid"` and calls `extract_fulltext` for sections + citations; secondary mode calls `extract_references` only.

**tiktoken Docker pre-cache:** Confirmed. Dockerfile line 22: `RUN python -c "import tiktoken; tiktoken.get_encoding('cl100k_base')"` prevents first-run network download.

**UNIQUE constraint migration:** Confirmed. `0003_paper_citations_unique.py` adds `uq_paper_citations_source_target_arxiv` on `(source_paper_id, target_arxiv_id)` enabling ON CONFLICT DO UPDATE in `_upsert_citations`.

---

## Summary

Phase 4 goal is fully achieved. All 9 observable truths are verified against the codebase. All 6 NORM requirements are satisfied with substantive implementations — no stubs, no orphaned artifacts, no broken wiring. The normalize_paper Celery task correctly:

1. Reads actual parse_source from DB (not the stale router argument)
2. Dispatches to three normalization branches (S2ORC, MinerU, GROBID)
3. Enriches with tiktoken token counts, tldr from abstract sentences, and SHA-256 dedup fingerprint
4. Checks for cross-source duplicates via JSONB query and links via IdMap
5. Upserts Paper row with ON CONFLICT DO UPDATE
6. Upserts citations to paper_citations using the UNIQUE constraint added by migration 0003

The router correctly appends `normalize_paper.si()` as the final step in all three parser chains (arxiv/latex, pmc/jats, pdf/mineru). The test suite has all 12 required functions with 10 unit tests passing and 2 integration stubs skipped as designed.

Two human verification items remain for end-to-end DB testing in the live Docker environment.

---

_Verified: 2026-04-15T22:00:00Z_
_Verifier: Claude (gsd-verifier)_
