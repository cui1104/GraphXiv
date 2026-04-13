# Feature Landscape: Academic Paper Processing API

**Domain:** Academic paper structured extraction API backend
**Researched:** 2026-04-13
**Confidence note:** Findings from training knowledge (cutoff August 2025) of deepxiv_sdk (public GitHub), S2ORC (AllenAI), Semantic Scholar API, OpenAlex API.

---

## Table Stakes

Features users expect. Missing = API is unusable or deepxiv_sdk compatibility breaks.

| Feature | Why Expected | Complexity | Confidence |
|---------|--------------|------------|------------|
| Paper title | Core identity; every consumer needs it | Trivial | HIGH |
| Abstract text | Most-used field for NLP, summarization, search | Trivial | HIGH |
| Authors list (name strings) | Required for attribution, citation formatting | Low | HIGH |
| arXiv ID / PMCID / DOI identifiers | Lookup key; SDK routes by these | Low | HIGH |
| Publication year | Needed for citation ordering, recency filtering | Low | HIGH |
| Venue / journal name | Required for citation formatting | Low | HIGH |
| Sections array (heading + body text) | Core reason this API exists | High | HIGH |
| References / bibliography list | Expected in any full-text API | Medium | HIGH |
| `src_url` field | deepxiv_sdk Reader explicitly expects this field | Low | HIGH |
| `token_count` field | deepxiv_sdk Reader exposes this; used for LLM context budgeting | Low | HIGH |
| `tldr` field | deepxiv_sdk Reader exposes `tldr`; null acceptable but key must exist | Medium | HIGH |
| `get_head()` / `get_brief()` endpoint modes | deepxiv_sdk exposes these as distinct access patterns | Low | HIGH |
| `get_sections()` endpoint mode | deepxiv_sdk exposes this separately from full paper | Low | HIGH |
| 404 for missing paper ID | SDK must handle gracefully | Low | HIGH |

---

## Differentiators

Features that set this backend apart from data.rag.ac.cn or plain metadata APIs.

| Feature | Value Proposition | Complexity | Confidence |
|---------|-------------------|------------|------------|
| Tables as structured data (not image) | OpenAlex and Semantic Scholar return zero table content | High | HIGH |
| Figures with captions in `ref_entries` | No open API returns figure captions as structured fields | High | MEDIUM |
| Math / equation strings (LaTeX source) | LaTeX-sourced papers expose raw equation strings | Medium | HIGH |
| Inline `cite_spans` within paragraph text | Which sentence cites which paper — not available in any open API | High | MEDIUM |
| Per-section `token_count` | Allows LLM consumers to slice exactly the section they need | Low | MEDIUM |
| `parse_source` provenance flag | Clients know whether content came from deterministic parse vs OCR | Low | HIGH |
| Local caching layer in SDK fork | deepxiv_sdk has no caching; repeated lookups hit network every time | Medium | HIGH |
| Open-source, self-hostable | data.rag.ac.cn is closed; open-source equivalent is the entire value prop | N/A | HIGH |

---

## Anti-Features (Do Not Build in 4-Week Timeline)

| Anti-Feature | Why Avoid | What to Do Instead |
|--------------|-----------|-------------------|
| Semantic / vector search | Out of scope per PROJECT.md | Structured ID-based lookup only |
| Real-time on-demand PDF parsing | Seconds to minutes per paper; kills API responsiveness | Pre-compute all parsing at ingestion |
| Full-text scraping of gated publishers | Legal risk, ToS violations | arXiv + PMC OA official feeds only |
| Automatic citation resolution | Requires S2 API calls per reference; rate-limited | Return raw bibliography strings |
| Author disambiguation | ML entity resolution; months of work | Author name strings as-is |
| Figure image extraction / base64 | Storage cost; not needed for text pipeline | Caption text + figure label only |

---

## deepxiv_sdk Reader Class — Reverse-Engineered Schema

**Confidence:** HIGH. The SDK is a straightforward Python HTTP client. Field names below are those the Reader accesses.

### Fields the SDK Reader Explicitly Reads

```
title          str
abstract       str
authors        list[str]
tldr           str | null
src_url        str
token_count    int
sections       list[SectionObject]
citations      list[CitationObject]
```

### Section Object
```
heading        str     e.g. "Introduction"
text           str     Full body text of section
```

### Citation Object
```
title          str
authors        list[str]
year           int | null
doi            str | null
arxiv_id       str | null
url            str | null
```

### Endpoint Patterns
```
GET /arxiv/{arxiv_id}/head       → metadata only (no sections)
GET /arxiv/{arxiv_id}/brief      → title + abstract + tldr + authors
GET /arxiv/{arxiv_id}/sections   → sections array only
GET /arxiv/{arxiv_id}/full       → complete paper object
GET /pmc/{pmcid}/head            → metadata only
GET /pmc/{pmcid}/full            → complete paper object
GET /arxiv/search?q=&limit=      → list of brief paper objects
```

---

## S2ORC JSON Schema (Reference Implementation)

**Confidence:** HIGH. Schema from Lo et al. 2020 ACL + AllenAI/s2orc-doc2json.

Key design decisions:
- **Paragraphs, not sections, are the atomic unit.** Section identity is a `section` string field on each paragraph.
- **Inline citations are character-offset spans** within paragraph text, not sentence-level.
- **`ref_entries` stores figures and tables** together, keyed by auto-generated IDs (`FIGREF0`, `TABREF0`).

### Top-Level Paper Object (key fields)

```json
{
  "paper_id": "string",
  "title": "string",
  "authors": [{ "first": "", "last": "", "affiliation": {}, "email": "" }],
  "year": 2020,
  "venue": "string",
  "abstract": "string",
  "arxiv_id": "string|null",
  "pmc_id": "string|null",
  "doi": "string|null",
  "has_pdf_parse": true,
  "pdf_parse": {
    "body_text": [
      {
        "text": "paragraph text",
        "cite_spans": [{ "start": 0, "end": 5, "text": "[1]", "ref_id": "BIBREF0" }],
        "ref_spans":  [{ "start": 0, "end": 8, "text": "Figure 1", "ref_id": "FIGREF0" }],
        "eq_spans":   [],
        "section": "Introduction",
        "sec_num": "1"
      }
    ],
    "bib_entries": {
      "BIBREF0": {
        "title": "string", "authors": [], "year": 2018, "venue": "string",
        "doi": "string|null", "raw_text": "string"
      }
    },
    "ref_entries": {
      "FIGREF0": { "type": "figure", "text": "caption text", "latex": null },
      "TABREF0": { "type": "table",  "text": "caption text", "latex": "string|null",
                   "content": "string", "html": "string|null" }
    },
    "back_matter": []
  }
}
```

---

## Proposed Unified JSON Schema

This is the exact contract the backend must produce and the SDK fork must consume. Strict superset of what deepxiv_sdk Reader expects; field names align with S2ORC where they do not conflict.

### Full Paper Object

```json
{
  "paper_id": "string",
  "arxiv_id": "string|null",
  "pmc_id": "string|null",
  "doi": "string|null",
  "title": "string",
  "abstract": "string",
  "tldr": "string|null",
  "authors": ["string"],
  "year": 2024,
  "venue": "string|null",
  "src_url": "string",
  "token_count": 12000,
  "parse_source": "latex|jats|pdf_mineru|pdf_grobid",
  "sections": [
    {
      "heading": "string",
      "sec_num": "string|null",
      "text": "string",
      "paragraphs": [
        {
          "text": "string",
          "cite_spans": [{ "start": 0, "end": 5, "text": "[1]", "ref_id": "BIBREF0" }],
          "ref_spans": []
        }
      ],
      "token_count": 1200
    }
  ],
  "citations": [
    {
      "ref_id": "BIBREF0",
      "title": "string",
      "authors": ["string"],
      "year": 2019,
      "venue": "string|null",
      "doi": "string|null",
      "arxiv_id": "string|null",
      "raw_text": "string"
    }
  ],
  "ref_entries": {
    "FIGREF0": { "type": "figure", "text": "caption", "latex": null },
    "TABREF0": { "type": "table",  "text": "caption", "latex": "string|null",
                 "content": "string", "html": "string|null" }
  },
  "back_matter": [
    { "heading": "string", "text": "string", "paragraphs": [] }
  ]
}
```

### Head / Brief Response (subset)

```json
{
  "paper_id": "string", "arxiv_id": "string|null", "pmc_id": "string|null",
  "doi": "string|null", "title": "string", "abstract": "string",
  "tldr": "string|null", "authors": ["string"], "year": 2024,
  "venue": "string|null", "src_url": "string", "token_count": 12000,
  "parse_source": "string"
}
```

### Sections Response

```json
{ "paper_id": "string", "title": "string", "sections": [...], "token_count": 12000 }
```

### Search Response

```json
{
  "total": 42,
  "results": [{ "paper_id": "", "arxiv_id": "", "title": "", "abstract": "",
                "tldr": null, "authors": [], "year": 2024, "src_url": "", "token_count": 0 }]
}
```

---

## Feature Dependency Graph

```
sections endpoint     → body_text parsing pipeline (LaTeXML or MinerU/GROBID)
tables in ref_entries → sections parsing complete (tables live in ref_entries alongside body_text)
inline cite_spans     → sections parsing + bibliography resolution
full endpoint         → head + sections + citations all working
/pmc/ endpoints       → PMC JATS XML ingestion pipeline (independent of arXiv path)
tldr field            → can be null initially; populate later or proxy to S2 TLDR API
token_count           → computed at write time from sections text; trivial once sections exist
src_url               → stored at ingestion from arXiv/PMC canonical URL; trivial
```

---

## MVP Build Order

1. `GET /arxiv/{id}/head` — title, abstract, authors, identifiers, src_url, token_count (tldr=null)
2. `GET /arxiv/{id}/brief` — same as head (ensures SDK brief/head distinction works)
3. `GET /arxiv/{id}/sections` — sections array with heading + text (no inline spans yet)
4. `GET /arxiv/{id}/full` — above + citations array (bare reference objects, no cite_spans)
5. `GET /arxiv/search?q=&limit=` — keyword search over stored papers
6. `GET /pmc/{id}/head` and `GET /pmc/{id}/full` — parallel PMC path

Defer to post-MVP: inline `cite_spans`, `ref_spans`, `eq_spans`, table `html`, per-paragraph structure, `tldr` population (return null).

---

## Cross-API Comparison

| Field | deepxiv_sdk | S2ORC | Semantic Scholar | OpenAlex | This Schema |
|-------|-------------|-------|-----------------|----------|-------------|
| title | YES | YES | YES | YES | YES |
| abstract | YES | YES | YES | inverted | YES |
| sections / body_text | YES | YES (paragraphs) | NO | NO | YES |
| inline cite_spans | unknown | YES | NO | NO | YES (post-MVP) |
| tables structured | unknown | partial | NO | NO | YES |
| figure captions | unknown | YES | NO | NO | YES |
| tldr | YES | NO | YES (separate) | NO | YES (null OK) |
| src_url | YES | NO | partial | partial | YES |
| token_count | YES | NO | NO | NO | YES |
| parse_source provenance | NO | NO | NO | NO | YES |
| open-source backend | NO | dump only | NO | YES | YES |

---

## Open Questions

- Verify deepxiv_sdk field names against live repo: `grep -r "token_count\|src_url\|tldr\|sections" deepxiv_sdk/` after cloning
- Whether deepxiv_sdk `citations` field is named `citations` or `references` at JSON level — check `grep "citations\|references" deepxiv_sdk/reader.py`
- Whether `token_count` is per-paper only or also per-section in the original SDK
