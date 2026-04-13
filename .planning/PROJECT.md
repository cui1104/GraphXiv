# Research Knowledge Graph Backend

## What This Is

A scalable academic paper processing pipeline that ingests arXiv and PubMed/PMC papers via their official feeds, routes them through appropriate parsers (LaTeX/XML → deterministic, PDF → ML models), and stores structured JSON output in a queryable database. The project exposes a REST API that is API-compatible with deepxiv_sdk's `Reader` class (`/arxiv/`, `/pmc/` endpoints), so the existing SDK works against this backend by simply changing `base_url`.

## Core Value

Given an arXiv ID or PMC ID, return clean structured JSON (sections, tables, figures, metadata) in under a second — by doing all parsing work ahead of time via a continuous ingestion pipeline.

## Requirements

### Validated

(None yet — ship to validate)

### Active

- [ ] Continuous ingestion crawler for arXiv daily submissions feed (new papers auto-downloaded)
- [ ] Continuous ingestion crawler for PubMed/PMC OAI-PMH feed
- [ ] Smart routing: arXiv LaTeX source → LaTeXML/s2orc parser (fast path); fallback to PDF → MinerU/GROBID (ML path)
- [ ] Smart routing: PMC JATS XML → deterministic parser; fallback to PDF → ML path
- [ ] Structured JSON output schema: title, abstract, authors, sections (heading + text), tables, figures, references, identifiers
- [ ] PostgreSQL storage layer with paper records, indexed by arXiv ID / PMCID
- [ ] REST API compatible with deepxiv_sdk endpoints: `GET /arxiv/` (search/head/brief/sections), `GET /pmc/` (head/full)
- [ ] Job queue (Celery + Redis or Ray) for parallel paper processing at small-cluster scale
- [ ] Benchmark evaluation: compare MinerU vs GROBID vs Docling on a sample of arXiv PDFs (section accuracy, table extraction quality)

### Out of Scope

- Full-text web scraping of gated publishers — only Open Access sources via official APIs/feeds
- Real-time on-demand PDF parsing (all parsing is pre-computed)
- Kubernetes / production-scale deployment — small cluster (single machine + job queue) is sufficient
- Semantic search / vector embeddings — purely structured extraction, not RAG
- deepxiv_sdk fork/extensions — deferred to final phase if time permits

## Context

- **Independent study:** DATS5990, one-month timeline (April 2026)
- **Prior art:** deepxiv_sdk (open-source client SDK) wraps data.rag.ac.cn, a closed-source backend doing exactly this. The goal is an open-source equivalent.
- **API compatibility target:** deepxiv_sdk `Reader` class uses `base_url` param — matching `/arxiv/` and `/pmc/` endpoint contracts means zero SDK changes needed to point at this backend.
- **Key open-source components to leverage:**
  - s2orc-doc2json (AllenAI) — PDF2JSON, TEX2JSON, JATS2JSON
  - MinerU (opendatalab, 59k ★) — high-fidelity PDF → markdown/JSON
  - GROBID — CRF-based scholarly PDF extraction (citations, references)
  - Docling (IBM, 57k ★) — PDF → structured formats with table support
  - Nougat (Meta, 9.9k ★) — transformer OCR for academic PDFs
- **arXiv advantage:** arXiv provides LaTeX source for most papers — parsing LaTeX is deterministic and much cheaper than OCR. PDF fallback only when source unavailable.
- **PMC advantage:** PubMed Central provides JATS XML for open-access articles — same deterministic advantage.

## Constraints

- **Timeline:** ~4 weeks (April 2026 DATS5990 submission)
- **Scale:** Small cluster — thousands of papers, job queue, single machine or small VM; no Kubernetes
- **Data sources:** Only Open Access — arXiv bulk API, PMC OAI-PMH, no gated publisher scraping
- **API contract:** Output JSON schema must be compatible with deepxiv_sdk's expected response format so the SDK works without modification

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Prioritize LaTeX/XML over PDF parsing | Deterministic, free, higher fidelity — PDFs are the fallback not the primary path | — Pending |
| deepxiv_sdk API compatibility | Enables reuse of existing SDK tooling and potential future SDK extension phase | — Pending |
| PostgreSQL as storage layer | Sufficient for small-cluster scale, good JSON support, easy to query | — Pending |
| Celery + Redis for job queue | Lightweight, Python-native, sufficient for thousands of papers/day | — Pending |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/gsd:transition`):
1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions
5. "What This Is" still accurate? → Update if drifted

**After each milestone** (via `/gsd:complete-milestone`):
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-04-13 after initialization*
