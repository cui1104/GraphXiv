# Phase 4: Normalizer + Storage - Research

**Researched:** 2026-04-15
**Domain:** Data normalization, PostgreSQL upsert, tiktoken, SHA-256 dedup, GROBID TEI fulltext
**Confidence:** HIGH (all findings corroborated by existing codebase + official docs)

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

- **D-01:** Append `normalize_paper.si(paper_id, parse_source)` to every parser chain in `router.py` — normalization runs automatically at the end of each parse chain, no separate trigger needed. The existing `normalize_paper` stub in `app/tasks/normalize.py` is the target; implement it fully here.
- **D-02:** Rule-based hierarchy from `sec_num` field — count dots in the section number string to determine depth (`"1.2.3"` = 2 dots = depth 3). `"title"` type blocks with no sec_num get `sec_num: null`. Flat `"text"` blocks between headings are grouped under the preceding `"title"` block. Result: a proper `sections[]` array with nested structure, not a flat blob. `text_level_broken: True` flag (set by Phase 3) signals this reconstruction path.
- **D-03:** Two modes in `app/parsers/grobid.py`: `extract_references(pdf_path)` (existing, calls `/api/processReferences`, citation-only, secondary enrichment) and `extract_fulltext(pdf_path)` (new, calls `/api/processFulltextDocument`, returns body text + sections + citations as TEI XML; parsed into sections and citations together). In `parse_pdf_grobid` task: detect primary vs secondary mode by checking `ps.parse_status == "cascade_to_pdf_grobid"`. If primary → call `extract_fulltext()`, populate sections + citations. If secondary → call `extract_references()`, merge citations only (existing behavior). This fixes the gap where D-03-routed papers had citations but no body text.
- **D-04:** Normalizer writes citation rows to `paper_citations` table during the normalize step. `target_arxiv_id` and `target_doi` stored as raw strings from GROBID output. `target_paper_id` resolved via `id_map` lookup (match on arxiv_id or doi) — set if found in corpus, left `NULL` otherwise. Upsert pattern: `ON CONFLICT (source_paper_id, target_arxiv_id)` update `context_text`.
- **D-05:** Before writing normalizer code, grep deepxiv_sdk for accessed field names. Required top-level keys always present (never omitted): `title`, `abstract`, `authors`, `sections`, `citations`, `tldr`, `src_url`, `token_count`, `parse_source`. `tldr`: first 2–3 sentences of abstract via sentence splitter (deterministic fallback, v1 only). `token_count`: tiktoken cl100k_base on concatenated full section text. `src_url`: arXiv papers → `https://arxiv.org/abs/{arxiv_id}`; PMC papers → `https://www.ncbi.nlm.nih.gov/pmc/articles/{pmc_id}/`.
- **D-06:** SHA-256 of `(normalized_title + "|" + first_author_last_name + "|" + year)` where normalization = lowercase + strip non-alphanumeric. Stored in `paper.content["dedup_fingerprint"]`. If any of the three fields is missing, fingerprint is skipped (not computed). Cross-source match: look up fingerprint in existing papers; if match found, link via `id_map` instead of creating duplicate.

### Claude's Discretion

- TEI XML parsing strategy for GROBID fulltext (lxml vs ElementTree vs regex)
- Exact sentence splitter for tldr (re-based split on `. ` boundary is fine)
- Error handling for malformed GROBID TEI responses
- Section `paragraphs` field shape within each section object

### Deferred Ideas (OUT OF SCOPE)

- S2 TLDR API or local model for tldr generation — v2 (SDK-V2-02), out of scope for Phase 4
- pgvector embeddings population — not in Phase 4 scope (embeddings column exists but stays null)
- Inline cite_spans / eq_spans within paragraph text — v2 (EXT-01), sections return flat text in v1
- Table HTML rendering — v2 (EXT-03), table caption + content string is sufficient for v1
</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| NORM-01 | Normalizer maps all parser outputs (S2ORC JSON, MinerU JSON, GROBID TEI XML) to unified PaperJSON schema with exact deepxiv_sdk field names | S2ORC field mapping documented; MinerU content_list structure known from Phase 3; GROBID TEI XML structure documented below |
| NORM-02 | `token_count` always populated using tiktoken (cl100k_base) on full extracted text; key never omitted | tiktoken 0.12.0 API verified; cl100k_base encoding pattern documented in Code Examples |
| NORM-03 | `tldr` always present as key (value may be null or first 2-3 sentences of abstract) | Regex sentence splitter pattern documented; always-present key enforcement pattern shown |
| NORM-04 | Dedup fingerprint (SHA-256 of normalized title + first author + year) computed; papers with matching fingerprint linked via `id_map` | SHA-256 pattern with hashlib documented; cross-source merge logic using existing `IdMap` ORM model verified |
| NORM-05 | Section objects: `{heading, sec_num, text, paragraphs, token_count}`; citation objects: `{ref_id, title, authors, year, venue, doi, arxiv_id, raw_text}` | Exact shapes verified against FEATURES.md schema; GROBID `_parse_tei_references` already populates title/authors/year/doi |
| NORM-06 | `parse_quality` field stored for every paper with degradation flags from all parse paths | Already set by Phase 3 parsers; normalizer must preserve and write to `Paper.parse_quality` column |
</phase_requirements>

---

## Summary

Phase 4 implements the single normalization layer that converts three different raw parser outputs into one unified PaperJSON schema. The normalizer runs as a Celery task (`normalize_paper`) appended to every parser chain in `router.py`. It reads `paper.content` (set by Phase 3 parsers), transforms it to the deepxiv_sdk field contract, computes token counts and tldr, derives a dedup fingerprint, and upserts back to PostgreSQL.

The three input formats are: (1) S2ORC JSON from TEX2JSON and JATS2JSON (`body_text[]` paragraphs with `section` and `sec_num` fields, `bib_entries{}` dict), (2) MinerU `content_list` JSON (flat array of typed blocks — `"title"` type for headings, `"text"` type for paragraphs), and (3) GROBID TEI XML from the new `extract_fulltext()` function (body uses `<div>`, `<head>`, `<p>` elements with `n` attribute for section numbers). MinerU also sets `text_level_broken: True` in `paper.content` — this flag signals the dot-counting hierarchy reconstruction path (D-02).

The storage step is a PostgreSQL upsert using SQLAlchemy's `pg_insert().on_conflict_do_update()` keyed on `canonical_id`. The `paper_citations` edge table is populated concurrently. Cross-source dedup uses SHA-256 fingerprint lookups against existing `IdMap` records before deciding to merge or create.

**Primary recommendation:** Implement `normalize_paper` as one function with three parse_source branches (latex/jats, pdf_mineru, pdf_grobid), each calling a dedicated `_normalize_{source}(content)` helper that returns a canonical PaperJSON dict, then pass that dict through shared `_add_token_count()`, `_add_tldr()`, `_add_dedup_fingerprint()` post-processors before the upsert.

---

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| tiktoken | 0.12.0 | Token counting with cl100k_base encoding | Mandated by D-05; same tokenizer as GPT-4; deterministic |
| hashlib | stdlib | SHA-256 dedup fingerprint | stdlib; no dependency; deterministic |
| lxml | 6.0.4 | Parse GROBID TEI XML for `extract_fulltext()` | Already installed (grobid.py uses it); proven with existing `_parse_tei_references` |
| SQLAlchemy | 2.0.49 | ORM + pg_insert upsert | Already locked in project |
| sqlalchemy.dialects.postgresql | 2.0.49 | `pg_insert` for ON CONFLICT DO UPDATE | Part of SQLAlchemy; required for proper JSONB upsert |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| re (stdlib) | stdlib | Sentence splitter for tldr fallback | Simple `. ` boundary split per Claude's discretion |
| unicodedata (stdlib) | stdlib | Normalize title for dedup fingerprint | Strip non-alphanumeric with proper Unicode handling |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| lxml for TEI XML | BeautifulSoup (lxml backend) | BS4 not installed; lxml already present; lxml is faster and already used in grobid.py |
| tiktoken | spacy / nltk tokenizer | Not tokens for LLM context — must be tiktoken cl100k_base per D-05 |

**Installation (add to pyproject.toml):**
```bash
pip install tiktoken==0.12.0
```

**Version verification:**
tiktoken 0.12.0 is the latest as of 2025-10 (verified via PyPI search). Add to `[project.dependencies]` in `pyproject.toml`.

---

## Architecture Patterns

### Recommended Project Structure

No new files needed. Work lives in:
```
app/
├── tasks/
│   ├── normalize.py        # implement normalize_paper fully (stub exists)
│   └── router.py           # append normalize_paper.si() to each chain
├── parsers/
│   └── grobid.py           # add extract_fulltext() alongside extract_references()
```

### Pattern 1: Dispatcher with per-source normalizer helpers

**What:** `normalize_paper` is the Celery task entry point. It reads `paper.content`, dispatches to a per-source helper based on `parse_source`, then runs shared post-processors.

**When to use:** Always — the three input formats are structurally incompatible; per-source helpers keep each branch readable and independently testable.

**Example:**
```python
# In app/tasks/normalize.py
def normalize_paper(self, paper_id: str, parse_source: str) -> dict:
    from app.db import SessionLocal
    from app.models import Paper
    session = SessionLocal()
    try:
        paper = session.query(Paper).filter(Paper.canonical_id == paper_id).first()
        raw = paper.content or {}

        if parse_source in ("latex", "jats"):
            paper_json = _normalize_s2orc(raw, paper)
        elif parse_source == "pdf_mineru":
            paper_json = _normalize_mineru(raw, paper)
        elif parse_source == "pdf_grobid":
            paper_json = _normalize_grobid_fulltext(raw, paper)
        else:
            return {"status": "unknown_source", "parse_source": parse_source}

        _add_token_count(paper_json)
        _add_tldr(paper_json)
        _add_dedup_fingerprint(paper_json)
        _upsert_paper(session, paper, paper_json)
        _upsert_citations(session, paper, paper_json.get("citations", []))
        session.commit()
        return {"status": "ok", "paper_id": paper_id}
    except Exception as exc:
        session.rollback()
        raise self.retry(exc=exc)
    finally:
        session.close()
```

### Pattern 2: S2ORC body_text paragraph grouping into sections

**What:** S2ORC `body_text` is an array of paragraph dicts, each with a `section` string and `sec_num` string. Group consecutive paragraphs with the same `(section, sec_num)` into one section object.

**When to use:** `parse_source in ("latex", "jats")` — both produce S2ORC format from s2orc-doc2json.

**Example:**
```python
def _normalize_s2orc(raw: dict, paper) -> dict:
    # S2ORC wraps body under pdf_parse for PDF-sourced; or at top level for LaTeX/JATS
    pdf_parse = raw.get("pdf_parse") or raw
    body_text = pdf_parse.get("body_text", [])
    bib_entries = pdf_parse.get("bib_entries", {})

    sections = []
    current_key = None
    current_paragraphs = []

    for para in body_text:
        key = (para.get("section", ""), para.get("sec_num"))
        if key != current_key:
            if current_paragraphs:
                sections.append(_build_section(current_key, current_paragraphs))
            current_key = key
            current_paragraphs = [para]
        else:
            current_paragraphs.append(para)
    if current_paragraphs:
        sections.append(_build_section(current_key, current_paragraphs))

    citations = _bib_entries_to_citations(bib_entries)
    # merge grobid_citations if present (from GROBID enrichment step)
    if raw.get("grobid_citations"):
        citations = _merge_citations(citations, raw["grobid_citations"])

    return {
        "title": raw.get("title") or paper.title or "",
        "abstract": raw.get("abstract") or paper.abstract or "",
        "authors": _flatten_authors(raw.get("authors", [])),
        "sections": sections,
        "citations": citations,
        "ref_entries": pdf_parse.get("ref_entries", {}),
        "back_matter": pdf_parse.get("back_matter", []),
        "parse_source": paper.parse_source,
        "parse_quality": paper.parse_quality or "ok",
    }
```

### Pattern 3: MinerU content_list dot-counting hierarchy reconstruction (D-02)

**What:** MinerU stores all content as a flat list of typed blocks. Headings are `type: "title"` blocks; body text is `type: "text"`. Reconstruct hierarchy by counting dots in `sec_num`.

**When to use:** `parse_source == "pdf_mineru"` AND `content.get("text_level_broken") is True` (always True for OSS MinerU, set by Phase 3).

**Example:**
```python
def _normalize_mineru(raw: dict, paper) -> dict:
    content_list = raw.get("content_list", [])
    sections = []
    current_heading = None
    current_sec_num = None
    current_texts = []

    for block in content_list:
        btype = block.get("type", "")
        if btype == "title":
            # Flush previous section
            if current_heading is not None:
                sections.append(_make_section(current_heading, current_sec_num, current_texts))
            current_heading = block.get("text", "")
            current_sec_num = block.get("sec_num")  # e.g. "1.2.3" or None
            current_texts = []
        elif btype == "text":
            current_texts.append(block.get("text", ""))

    if current_heading is not None:
        sections.append(_make_section(current_heading, current_sec_num, current_texts))

    # Citations come from grobid_citations added by parse_pdf_grobid step
    grobid_cits = raw.get("grobid_citations", [])
    citations = _grobid_raw_to_citations(grobid_cits)

    return {
        "title": paper.title or "",
        "abstract": paper.abstract or "",
        "authors": _authors_from_paper(paper),
        "sections": sections,
        "citations": citations,
        "ref_entries": {},
        "back_matter": [],
        "parse_source": paper.parse_source,
        "parse_quality": paper.parse_quality or "ok",
    }
```

### Pattern 4: GROBID extract_fulltext TEI XML body parsing

**What:** `processFulltextDocument` returns full TEI XML. Body structure: `<text><body><div n="1"><head>Introduction</head><p>...</p></div></body></text>`. Section number is in the `n` attribute of `<div>`.

**When to use:** D-03 grobid primary path — `parse_status == "cascade_to_pdf_grobid"`. Only the `extract_fulltext()` function (new in Phase 4) produces this; `extract_references()` produces citations-only TEI.

**Example (TEI structure and parse pattern):**
```python
# TEI XML structure from processFulltextDocument:
# <TEI xmlns="http://www.tei-c.org/ns/1.0">
#   <teiHeader>...</teiHeader>
#   <text>
#     <body>
#       <div n="1">
#         <head>Introduction</head>
#         <p>First paragraph text.</p>
#         <p>Second paragraph text.</p>
#       </div>
#       <div n="2">
#         <head>Related Work</head>
#         <p>...</p>
#       </div>
#     </body>
#   </text>
# </TEI>

TEI_NS = "http://www.tei-c.org/ns/1.0"

def _parse_tei_fulltext_sections(tei_xml: bytes) -> list[dict]:
    from lxml import etree
    root = etree.fromstring(tei_xml)
    sections = []
    body = root.find(f".//{{{TEI_NS}}}body")
    if body is None:
        return sections
    for div in body.findall(f"{{{TEI_NS}}}div"):
        sec_num = div.get("n")
        head_el = div.find(f"{{{TEI_NS}}}head")
        heading = head_el.text.strip() if head_el is not None and head_el.text else ""
        paras = []
        for p_el in div.findall(f"{{{TEI_NS}}}p"):
            text = "".join(p_el.itertext()).strip()
            if text:
                paras.append({"text": text, "cite_spans": [], "ref_spans": []})
        full_text = " ".join(p["text"] for p in paras)
        sections.append({
            "heading": heading,
            "sec_num": sec_num,
            "text": full_text,
            "paragraphs": paras,
            "token_count": 0,  # populated by _add_token_count()
        })
    return sections
```

### Pattern 5: PostgreSQL upsert via pg_insert

**What:** `sqlalchemy.dialects.postgresql.insert` (aliased `pg_insert`) provides `on_conflict_do_update()`. Key on `canonical_id` (primary key) — use `set_=` to update content, token_count, tldr, parse_source, parse_quality, updated_at.

**When to use:** Writing the normalized paper back to the `papers` table. Same pattern for `paper_citations` with its own conflict target.

**Example:**
```python
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy import func

def _upsert_paper(session, paper, paper_json: dict):
    stmt = pg_insert(Paper.__table__).values(
        canonical_id=paper.canonical_id,
        arxiv_id=paper.arxiv_id,
        pmc_id=paper.pmc_id,
        doi=paper.doi,
        title=paper_json["title"],
        abstract=paper_json["abstract"],
        year=paper.year,
        venue=paper.venue,
        parse_source=paper_json["parse_source"],
        parse_quality=paper_json["parse_quality"],
        token_count=paper_json["token_count"],
        tldr=paper_json["tldr"],
        content=paper_json,
        updated_at=func.now(),
    ).on_conflict_do_update(
        index_elements=["canonical_id"],
        set_={
            "content": paper_json,
            "token_count": paper_json["token_count"],
            "tldr": paper_json["tldr"],
            "parse_source": paper_json["parse_source"],
            "parse_quality": paper_json["parse_quality"],
            "updated_at": func.now(),
        }
    )
    session.execute(stmt)
```

### Pattern 6: tiktoken token count (NORM-02)

**What:** tiktoken cl100k_base, concatenate all section text before encoding. Always write result (never omit key).

**Example:**
```python
def _add_token_count(paper_json: dict) -> None:
    import tiktoken
    enc = tiktoken.get_encoding("cl100k_base")
    all_text = " ".join(s.get("text", "") for s in paper_json.get("sections", []))
    paper_json["token_count"] = len(enc.encode(all_text)) if all_text else 0
    # Also set per-section token_count
    for sec in paper_json.get("sections", []):
        sec["token_count"] = len(enc.encode(sec.get("text", ""))) if sec.get("text") else 0
```

### Pattern 7: tldr fallback (NORM-03)

**What:** Split abstract on `. ` boundaries, take first 2-3 sentences. Key always present even if abstract is empty (value becomes null or empty string).

**Example:**
```python
def _add_tldr(paper_json: dict) -> None:
    abstract = paper_json.get("abstract") or ""
    if not abstract:
        paper_json["tldr"] = None
        return
    sentences = [s.strip() for s in abstract.split(". ") if s.strip()]
    tldr_sentences = sentences[:3]
    paper_json["tldr"] = ". ".join(tldr_sentences) + "." if tldr_sentences else None
```

### Pattern 8: SHA-256 dedup fingerprint (D-06)

**What:** Normalize title (lowercase, strip non-alphanumeric), concatenate with first author last name and year, hash with hashlib SHA-256. Skip if any field missing.

**Example:**
```python
import hashlib
import re

def _add_dedup_fingerprint(paper_json: dict) -> None:
    title = paper_json.get("title") or ""
    authors = paper_json.get("authors") or []
    year = paper_json.get("year")
    if not title or not authors or not year:
        paper_json["dedup_fingerprint"] = None
        return
    norm_title = re.sub(r"[^a-z0-9]", "", title.lower())
    first_author = authors[0] if authors else ""
    # Extract last name (last space-separated token)
    last_name = re.sub(r"[^a-z0-9]", "", first_author.split()[-1].lower()) if first_author else ""
    raw = f"{norm_title}|{last_name}|{year}"
    paper_json["dedup_fingerprint"] = hashlib.sha256(raw.encode()).hexdigest()
```

### Pattern 9: Cross-source dedup via id_map (D-06 + NORM-04)

**What:** After computing fingerprint, search existing papers for a matching fingerprint in their `content` JSONB. If found, insert/update `id_map` to link IDs rather than creating a duplicate paper row.

**Example:**
```python
def _check_dedup_and_link(session, paper, paper_json: dict) -> bool:
    """Returns True if this paper was merged into an existing record (skip upsert)."""
    fp = paper_json.get("dedup_fingerprint")
    if not fp:
        return False
    from sqlalchemy import text
    existing = session.execute(
        text("SELECT canonical_id, arxiv_id, pmc_id FROM papers WHERE content->>'dedup_fingerprint' = :fp LIMIT 1"),
        {"fp": fp}
    ).fetchone()
    if existing and str(existing.canonical_id) != str(paper.canonical_id):
        # Link this paper's IDs to the existing canonical
        from app.models import IdMap
        id_map_row = IdMap(
            canonical_id=existing.canonical_id,
            arxiv_id=paper.arxiv_id,
            pmc_id=paper.pmc_id,
            doi=paper.doi,
        )
        session.merge(id_map_row)
        return True  # merged — do not upsert as separate row
    return False
```

### Pattern 10: Citation upsert to paper_citations (D-04)

**What:** For each citation in `paper_json["citations"]`, insert to `paper_citations`. Resolve `target_paper_id` via `id_map` lookup on `target_arxiv_id` or `target_doi`. Upsert on `(source_paper_id, target_arxiv_id)`.

**Note:** `PaperCitation` table has no explicit UNIQUE constraint on `(source_paper_id, target_arxiv_id)` in the existing model — Phase 4 plan 04-03 must add this constraint via Alembic migration before the upsert pattern works reliably.

**Example:**
```python
def _upsert_citations(session, paper, citations: list[dict]) -> None:
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    from app.models import PaperCitation, IdMap
    for cit in citations:
        target_arxiv_id = cit.get("arxiv_id")
        target_doi = cit.get("doi")
        # Attempt to resolve target_paper_id from id_map
        target_paper_id = None
        if target_arxiv_id:
            row = session.query(IdMap).filter(IdMap.arxiv_id == target_arxiv_id).first()
            if row:
                target_paper_id = row.canonical_id
        if not target_paper_id and target_doi:
            row = session.query(IdMap).filter(IdMap.doi == target_doi).first()
            if row:
                target_paper_id = row.canonical_id

        stmt = pg_insert(PaperCitation.__table__).values(
            source_paper_id=paper.canonical_id,
            target_paper_id=target_paper_id,
            target_arxiv_id=target_arxiv_id,
            target_doi=target_doi,
            context_text=cit.get("raw_text"),
        ).on_conflict_do_update(
            constraint="uq_paper_citations_source_target_arxiv",
            set_={"context_text": cit.get("raw_text"), "target_paper_id": target_paper_id},
        )
        session.execute(stmt)
```

### Pattern 11: GROBID extract_fulltext (new function in D-03)

**What:** New function in `app/parsers/grobid.py` calling `/api/processFulltextDocument`. Returns both sections and citations. Non-blocking — returns `([], [])` on any failure.

**Example:**
```python
def extract_fulltext(pdf_path: str, timeout: int = 60) -> tuple[list[dict], list[dict]]:
    """POST PDF to GROBID /api/processFulltextDocument. Returns (sections, citations).
    Returns ([], []) on any failure — non-blocking."""
    try:
        with open(pdf_path, "rb") as f:
            pdf_bytes = f.read()
        with httpx.Client(timeout=timeout) as client:
            resp = client.post(
                f"{GROBID_URL}/api/processFulltextDocument",
                files={"input": ("paper.pdf", pdf_bytes, "application/pdf")},
                data={"includeRawCitations": "1", "consolidateCitations": "0"},
            )
        if resp.status_code != 200:
            return [], []
        sections = _parse_tei_fulltext_sections(resp.content)
        citations = _parse_tei_references(resp.content)  # reuse existing function
        return sections, citations
    except Exception as exc:
        logger.warning("GROBID fulltext failed for %s: %s", pdf_path, exc)
        return [], []
```

### Pattern 12: Router chain wiring (D-01)

**What:** Append `normalize_paper.si(paper_id, parse_source)` to the end of every chain in `_build_parse_chain()` in `router.py`.

**Example:**
```python
from app.tasks.normalize import normalize_paper

# In _build_parse_chain():
if source_type in ("arxiv_tar", "arxiv"):
    return chain(
        parse_latex.si(paper_id),
        parse_pdf_grobid.si(paper_id),
        normalize_paper.si(paper_id, "latex"),
    )
elif source_type in ("pmc_jats", "pmc"):
    return chain(
        parse_jats.si(paper_id),
        parse_pdf_grobid.si(paper_id),
        normalize_paper.si(paper_id, "jats"),
    )
elif source_type in ("arxiv_pdf", "pmc_pdf", "pdf"):
    return chain(
        parse_pdf_mineru.si(paper_id),
        parse_pdf_grobid.si(paper_id),
        normalize_paper.si(paper_id, "pdf_mineru"),
    )
```

**Critical note:** `parse_source` is passed at chain-build time. For papers that cascade within `parse_latex` to `parse_pdf_grobid` as primary parser (D-03), the router chain for `arxiv_tar` sources will pass `"latex"` to `normalize_paper`, but the actual `paper.parse_source` in the DB will be `"pdf_grobid"`. The normalizer must read `paper.parse_source` from the DB record (not trust the `parse_source` argument) to select the correct helper branch.

### Anti-Patterns to Avoid

- **Never trust the `parse_source` argument blindly:** It reflects the original routing decision. After D-03 cascades, `paper.parse_source` in the DB may be `"pdf_grobid"` even if the chain was built for `"arxiv_tar"`. Always re-read `paper.parse_source` from the DB.
- **Never omit `token_count` or `tldr` keys from the JSONB content:** Phase 5 SQL queries expect `content->'token_count'` to be non-null. Missing key returns SQL null even if the column is non-null.
- **Never pass large dicts through Celery:** Chains use `.si()` immutable signatures — `normalize_paper.si(paper_id, parse_source)` only, no large result passing. Paper content is read from DB inside the task.
- **Never use `session.add(paper); session.commit()` for content updates:** Use `pg_insert().on_conflict_do_update()` to ensure idempotency across retries.
- **Never build GROBID fulltext path without handling TEI namespace:** `{http://www.tei-c.org/ns/1.0}` prefix required on all element lookups via lxml.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Token counting | Custom word/char count | tiktoken cl100k_base | cl100k_base is the exact tokenizer Phase 5/6 consumers expect for LLM context budgeting |
| JSONB upsert | Manual SELECT + INSERT/UPDATE in Python | `pg_insert().on_conflict_do_update()` | Race conditions under Celery parallelism; PostgreSQL atomicity handles concurrent normalize tasks |
| Cross-source ID resolution | Custom fingerprint algorithm | SHA-256 of normalized title+author+year (D-06) | Agreed spec; deviation breaks NORM-04 |
| TEI XML parsing | Regex string matching | lxml etree with namespace-aware XPath | GROBID TEI is valid XML; lxml already installed; regex on XML is fragile |
| Section hierarchy | Full tree data structure | Flat list with `sec_num` string preserved | The deepxiv_sdk schema stores sections as a flat list — hierarchy is conveyed via `sec_num` strings, not nesting |

**Key insight:** The JSONB content blob is the API contract. Phase 5 reads it with `->` operators. Every missing key is a breaking change for the SDK in Phase 6.

---

## Common Pitfalls

### Pitfall 1: parse_source mismatch after D-03 cascade

**What goes wrong:** Chain is built for `source_type="arxiv_tar"` so `normalize_paper.si(paper_id, "latex")` is appended. But `parse_latex` internally cascaded to `parse_pdf_grobid` (D-03), setting `paper.parse_source="pdf_grobid"`. Normalizer gets `parse_source="latex"` argument but `paper.parse_source="pdf_grobid"` in DB.

**Why it happens:** Router decides parse_source at chain build time; cascade changes it inside the parser task.

**How to avoid:** Normalizer ignores the `parse_source` argument — always reads `paper.parse_source` from the DB record to select the normalization branch. The argument is kept for logging only.

**Warning signs:** Papers in the `pdf_grobid` path have empty `sections` list but non-empty `grobid_citations`.

### Pitfall 2: MinerU content_list has no heading blocks

**What goes wrong:** Some papers have no `"title"` type blocks in the content_list — only `"text"` blocks. Result: zero sections constructed even though text exists.

**Why it happens:** MinerU may not detect headings in papers with unusual formatting.

**How to avoid:** Fall back — if zero `"title"` blocks found, treat the entire content_list as a single section with heading="" and sec_num=null. Never write `sections: []` when text content exists.

**Warning signs:** `sections: []` in final content but `content_list` has many `"text"` blocks.

### Pitfall 3: GROBID TEI XML namespace handling

**What goes wrong:** `root.find("body")` returns None even though `<body>` exists in the TEI. All elements have the `{http://www.tei-c.org/ns/1.0}` namespace prefix.

**Why it happens:** lxml requires namespace-qualified element names.

**How to avoid:** Use the `TEI_NS` constant already defined in `grobid.py`: `root.find(f".//{{{TEI_NS}}}body")`. Already demonstrated correct in the existing `_parse_tei_references` function.

**Warning signs:** `sections: []` from `extract_fulltext()` even though GROBID returned 200.

### Pitfall 4: tiktoken first-run network download

**What goes wrong:** First call to `tiktoken.get_encoding("cl100k_base")` downloads encoding files from the internet. Inside Docker with no internet = timeout.

**Why it happens:** tiktoken fetches vocabulary files on first use.

**How to avoid:** Either pre-cache inside the Docker image (run `python -c "import tiktoken; tiktoken.get_encoding('cl100k_base')"` in Dockerfile), or set `TIKTOKEN_CACHE_DIR` env var to a writable directory pre-populated during Docker build.

**Warning signs:** `normalize_paper` times out on first run but succeeds on subsequent runs.

### Pitfall 5: token_count key absent from JSONB content

**What goes wrong:** Phase 5 query `SELECT content->'token_count' FROM papers` returns null for rows where the key was never set in the JSONB blob — even though `Paper.token_count` column is set correctly.

**Why it happens:** `Paper.token_count` is a separate integer column AND the JSONB `content` blob also needs the key. These are stored independently.

**How to avoid:** Always write `token_count` into the `paper_json` dict before calling `_upsert_paper`. The upsert writes the dict as `content=paper_json`. Check with: `SELECT content->'token_count' FROM papers LIMIT 5`.

**Warning signs:** Phase 5 success criterion 1 fails — `content->'token_count'` returns null.

### Pitfall 6: S2ORC bib_entries format vs citation schema

**What goes wrong:** S2ORC `bib_entries` is a dict keyed by `"BIBREF0"`, `"BIBREF1"`, etc. Each value has `authors` as a list of dicts `{"first": "A", "last": "B"}`, not as strings. SDK citation schema expects `authors: ["string"]`.

**Why it happens:** S2ORC uses structured author objects; deepxiv_sdk schema uses flat name strings.

**How to avoid:** `_bib_entries_to_citations()` must flatten: `f"{a.get('first','')} {a.get('last','')}".strip()` for each author dict. Also set `ref_id` to the BIBREF key string.

**Warning signs:** `citations[0]["authors"]` contains dicts instead of strings; SDK throws attribute error.

### Pitfall 7: paper_citations UNIQUE constraint missing

**What goes wrong:** `ON CONFLICT (source_paper_id, target_arxiv_id)` upsert for `paper_citations` fails if the constraint doesn't exist in PostgreSQL.

**Why it happens:** `app/models.py` `PaperCitation` has no `UniqueConstraint` on `(source_paper_id, target_arxiv_id)`. pg_insert needs a real DB constraint to conflict against.

**How to avoid:** Plan 04-03 must add an Alembic migration adding this unique constraint before implementing the citation upsert. Alternatively use `ON CONFLICT DO NOTHING` without a constraint if citation dedup is not critical.

**Warning signs:** `sqlalchemy.exc.InvalidRequestError: no unique constraint matching given keys for table 'paper_citations'`.

### Pitfall 8: GROBID fulltext timeout

**What goes wrong:** `processFulltextDocument` is slower than `processReferences` — full ML layout analysis on a 20-page PDF can take 60-120 seconds. Default timeout of 30s triggers too early.

**Why it happens:** Full-text processing runs the full GROBID pipeline; reference extraction is a lighter pass.

**How to avoid:** `extract_fulltext()` uses `timeout=60` (or configurable). Normalizer task has `time_limit=60, soft_time_limit=50` — this may need extension if GROBID fulltext is slow. Consider raising `parse_pdf_grobid` time limit for primary-mode papers.

**Warning signs:** GROBID primary path papers have empty sections due to timeout, with `"grobid_failed"` in task return.

---

## Code Examples

### Building a section object (shared shape for all paths)

```python
def _make_section(heading: str, sec_num, texts: list[str]) -> dict:
    """Build a section dict conforming to NORM-05 shape."""
    full_text = " ".join(texts)
    paragraphs = [{"text": t, "cite_spans": [], "ref_spans": []} for t in texts if t]
    return {
        "heading": heading or "",
        "sec_num": sec_num,       # str like "1.2" or None
        "text": full_text,
        "paragraphs": paragraphs,
        "token_count": 0,         # populated later by _add_token_count()
    }
```

### Citation object shape (NORM-05 compliant)

```python
def _bib_entries_to_citations(bib_entries: dict) -> list[dict]:
    """Convert S2ORC bib_entries dict to citations list."""
    citations = []
    for ref_id, bib in bib_entries.items():
        authors_raw = bib.get("authors", [])
        if authors_raw and isinstance(authors_raw[0], dict):
            authors = [f"{a.get('first','')} {a.get('last','')}".strip() for a in authors_raw]
        else:
            authors = authors_raw  # already strings (JATS path)
        citations.append({
            "ref_id": ref_id,
            "title": bib.get("title"),
            "authors": authors,
            "year": bib.get("year"),
            "venue": bib.get("venue"),
            "doi": bib.get("doi"),
            "arxiv_id": bib.get("arxiv_id"),
            "raw_text": bib.get("raw_text"),
        })
    return citations
```

### GROBID raw citation to citation schema

```python
def _grobid_raw_to_citations(grobid_cits: list[dict]) -> list[dict]:
    """Convert grobid.extract_references() output to citation schema."""
    citations = []
    for i, cit in enumerate(grobid_cits):
        citations.append({
            "ref_id": f"BIBREF{i}",
            "title": cit.get("title"),
            "authors": cit.get("authors", []),
            "year": cit.get("year"),
            "venue": None,
            "doi": cit.get("doi"),
            "arxiv_id": None,
            "raw_text": cit.get("raw_text"),
        })
    return citations
```

### src_url construction (D-05)

```python
def _build_src_url(paper) -> str:
    if paper.arxiv_id:
        return f"https://arxiv.org/abs/{paper.arxiv_id}"
    if paper.pmc_id:
        return f"https://www.ncbi.nlm.nih.gov/pmc/articles/{paper.pmc_id}/"
    return ""
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| GROBID reference-only extraction | GROBID fulltext via `processFulltextDocument` | Phase 4 (D-03 gap fix) | D-03-cascaded papers gain body sections, not just citations |
| S2ORC paragraph-level granularity | Section-grouped with flat text per v1 spec | Phase 4 | Matches deepxiv_sdk Reader expectations for v1 |
| No token count | tiktoken cl100k_base on full text | Phase 4 | LLM consumers can budget context by token count |
| No dedup | SHA-256 fingerprint cross-source linking | Phase 4 | Same paper as arXiv + PMC stored once, not twice |

**Deprecated/outdated:**
- `normalize_paper` stub (Phase 3): returns `{"status": "stub"}` — fully replaced in Phase 4.
- Direct `session.add()` + `commit()` for paper updates: replaced by `pg_insert().on_conflict_do_update()` for idempotent Celery retries.

---

## Open Questions

1. **PaperCitation UNIQUE constraint**
   - What we know: `app/models.py` has no `UniqueConstraint` on `(source_paper_id, target_arxiv_id)` in `PaperCitation`. `pg_insert().on_conflict_do_update()` requires a real PostgreSQL constraint.
   - What's unclear: Whether to add via Alembic migration or use `ON CONFLICT DO NOTHING` with a duplicate-check approach.
   - Recommendation: Plan 04-03 adds Alembic migration for `UNIQUE(source_paper_id, target_arxiv_id)` before the upsert code. This is the cleanest solution.

2. **tiktoken Docker caching**
   - What we know: First call downloads vocab files; Docker containers may not have internet.
   - What's unclear: Whether TIKTOKEN_CACHE_DIR is pre-set in the existing Docker setup.
   - Recommendation: Add `RUN python -c "import tiktoken; tiktoken.get_encoding('cl100k_base')"` to Dockerfile to pre-cache. Or add `tiktoken` to the Docker build layer and accept the internet dependency during image build.

3. **S2ORC `pdf_parse` wrapper key**
   - What we know: S2ORC format sometimes wraps body_text under `pdf_parse` dict, sometimes at top level depending on whether TEX2JSON or JATS2JSON was used.
   - What's unclear: Which path outputs which structure — confirmed by reading s2orc-doc2json source.
   - Recommendation: Use `raw.get("pdf_parse") or raw` to handle both cases safely. Validate against actual Phase 3 output before finalizing.

4. **parse_pdf_grobid time_limit for primary mode**
   - What we know: `parse_pdf_grobid` has `time_limit=300`. The new `extract_fulltext()` call may take 60-120s.
   - What's unclear: Whether the existing 300s limit is sufficient or if GROBID fulltext needs dedicated limits.
   - Recommendation: Keep 300s limit (same as MinerU). Document that GROBID fulltext is best-effort within this window.

---

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest (installed) |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]` |
| Quick run command | `pytest tests/test_normalize.py -x -q` |
| Full suite command | `pytest tests/ -x -q -m "not gpu"` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| NORM-01 | S2ORC body_text grouped into sections with correct field names | unit | `pytest tests/test_normalize.py::test_normalize_s2orc -x` | ❌ Wave 0 |
| NORM-01 | MinerU content_list reconstructed into sections via dot-count | unit | `pytest tests/test_normalize.py::test_normalize_mineru -x` | ❌ Wave 0 |
| NORM-01 | GROBID TEI fulltext sections parsed from div/head/p elements | unit | `pytest tests/test_normalize.py::test_parse_tei_sections -x` | ❌ Wave 0 |
| NORM-02 | token_count > 0 for paper with section text | unit | `pytest tests/test_normalize.py::test_token_count -x` | ❌ Wave 0 |
| NORM-02 | token_count key present in content JSONB after upsert | integration | `pytest tests/test_normalize.py::test_token_count_in_db -x -m integration` | ❌ Wave 0 |
| NORM-03 | tldr key always present (string or null) | unit | `pytest tests/test_normalize.py::test_tldr_always_present -x` | ❌ Wave 0 |
| NORM-03 | tldr is first 2-3 abstract sentences | unit | `pytest tests/test_normalize.py::test_tldr_content -x` | ❌ Wave 0 |
| NORM-04 | SHA-256 fingerprint computed correctly | unit | `pytest tests/test_normalize.py::test_dedup_fingerprint -x` | ❌ Wave 0 |
| NORM-04 | id_map linked for matching fingerprint | integration | `pytest tests/test_normalize.py::test_cross_source_dedup -x -m integration` | ❌ Wave 0 |
| NORM-05 | Section object has all required fields | unit | `pytest tests/test_normalize.py::test_section_shape -x` | ❌ Wave 0 |
| NORM-05 | Citation object has all required fields | unit | `pytest tests/test_normalize.py::test_citation_shape -x` | ❌ Wave 0 |
| NORM-06 | parse_quality propagated from parser to normalized content | unit | `pytest tests/test_normalize.py::test_parse_quality -x` | ❌ Wave 0 |

### Sampling Rate

- **Per task commit:** `pytest tests/test_normalize.py -x -q`
- **Per wave merge:** `pytest tests/ -x -q -m "not gpu"`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps

- [ ] `tests/test_normalize.py` — all 12 test functions above; covers NORM-01 through NORM-06
- [ ] Fixture data: minimal S2ORC JSON dict, minimal MinerU content_list JSON, minimal GROBID TEI XML bytes — inline in test file, no external files needed

---

## Sources

### Primary (HIGH confidence)
- Existing codebase (`app/parsers/grobid.py`, `app/models.py`, `app/tasks/parse.py`, `app/tasks/router.py`) — verified pattern for lxml TEI parsing, ORM models, Celery chain patterns
- `.planning/research/FEATURES.md` — deepxiv_sdk field names and S2ORC schema, researched 2026-04-13 with HIGH confidence
- `.planning/phases/04-normalizer-storage/04-CONTEXT.md` — all locked decisions D-01 through D-06
- PyPI tiktoken 0.12.0 — current version verified via WebSearch 2026-04-15

### Secondary (MEDIUM confidence)
- WebSearch: GROBID TEI XML body structure — `<div n="">`, `<head>`, `<p>` element names confirmed by multiple sources including official docs excerpts and community examples
- WebSearch: tiktoken cl100k_base usage — standard OpenAI pattern, consistent across multiple cookbook references
- WebSearch: SQLAlchemy `pg_insert().on_conflict_do_update()` — SQLAlchemy 2.0 official docs confirmed the pattern; JSONB `||` merge operator available but not needed here (full content replacement preferred)

### Tertiary (LOW confidence)
- GROBID `processFulltextDocument` exact timeout behavior on large papers — needs empirical testing in actual environment

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — tiktoken version verified via PyPI; lxml already installed; SQLAlchemy pattern confirmed in official docs
- Architecture: HIGH — all patterns derived from existing Phase 3 code; S2ORC schema documented in FEATURES.md
- Pitfalls: HIGH for parse_source mismatch, MinerU no-headings, TEI namespace (derived from Phase 3 experience); MEDIUM for GROBID timeout (estimating based on known behavior)

**Research date:** 2026-04-15
**Valid until:** 2026-05-15 (stable stack; tiktoken and SQLAlchemy APIs are stable)
