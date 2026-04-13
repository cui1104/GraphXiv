# Research Knowledge Graph — End-to-End Platform

## What This Is

A full-stack academic paper platform built in two layers: (1) a backend processing pipeline that ingests arXiv and PubMed/PMC papers, routes them through appropriate parsers (LaTeX/XML → deterministic, PDF → ML models), and stores structured JSON in a queryable database; and (2) a forked and extended version of deepxiv_sdk that points at this backend and adds new capabilities. The project produces a self-contained, open-source alternative to the deepxiv / data.rag.ac.cn ecosystem.

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
- [ ] Fork deepxiv_sdk, point it at this backend, and verify all existing SDK features work (search, brief, head, sections, agent)
- [ ] Extend the forked SDK with at least one new capability not in the original (e.g., table access, bulk export, local caching, or new query modes)

### Out of Scope

- Full-text web scraping of gated publishers — only Open Access sources via official APIs/feeds
- Real-time on-demand PDF parsing (all parsing is pre-computed)
- Kubernetes / production-scale deployment — small cluster (single machine + job queue) is sufficient
- Semantic search / vector embeddings — purely structured extraction, not RAG

## Context

- **Independent study:** DATS5990, one-month timeline (April 2026)
- **Prior art:** deepxiv_sdk (open-source client SDK) wraps data.rag.ac.cn, a closed-source backend doing exactly this. The goal is an open-source equivalent.
- **SDK fork strategy:** Fork deepxiv_sdk, update `base_url` default to point at this backend, verify all existing features work, then add new functionality. The goal is a working end-to-end product, not just a backend.
- **API contract:** The backend REST API must exactly match the JSON response schemas that deepxiv_sdk's `Reader` class expects — fields like `title`, `abstract`, `sections`, `tldr`, `citations`, `src_url`, `token_count` must be present and named identically.
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
- **API contract:** Backend JSON response schemas must exactly match deepxiv_sdk field names/types — verified by running the SDK's own test suite against this backend
- **End-to-end:** Project must produce both a working backend AND a working SDK fork — not just one layer

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Prioritize LaTeX/XML over PDF parsing | Deterministic, free, higher fidelity — PDFs are the fallback not the primary path | — Pending |
| Fork deepxiv_sdk as the client layer | End-to-end product requires both backend + SDK; forking ensures exact JSON schema compatibility and enables new features | — Pending |
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
