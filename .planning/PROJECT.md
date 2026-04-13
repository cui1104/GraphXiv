# Research Knowledge Graph — End-to-End Platform

## What This Is

A full-stack academic paper platform built in two layers: (1) a backend processing pipeline that ingests arXiv and PubMed/PMC papers, routes them through appropriate parsers (LaTeX/XML → deterministic, PDF → ML models), and stores structured JSON in a queryable database; and (2) a forked and extended version of deepxiv_sdk that points at this backend and adds new capabilities. The project produces a self-contained, open-source alternative to the deepxiv / data.rag.ac.cn ecosystem.

## Core Value

Given an arXiv ID or PMC ID, return clean structured JSON (sections, tables, figures, metadata) in under a second — by doing all parsing work ahead of time via a continuous ingestion pipeline.

## Requirements

### Validated

(None yet — ship to validate)

### Active

- [ ] Targeted crawler for arXiv deep learning papers (cs.LG, cs.AI, cs.CV, cs.CL, stat.ML categories) producing a corpus of ~10,000 papers
- [ ] Targeted crawler for PubMed/PMC papers in deep learning / neural networks domain (~subset of the 10k corpus)
- [ ] Smart routing: arXiv LaTeX source → LaTeXML/s2orc parser (fast path); fallback to PDF → MinerU/GROBID (ML path)
- [ ] Smart routing: PMC JATS XML → deterministic parser; fallback to PDF → ML path
- [ ] Structured JSON output schema: title, abstract, authors, sections (heading + text), tables, figures, references, identifiers
- [ ] PostgreSQL storage layer with paper records, indexed by arXiv ID / PMCID
- [ ] REST API compatible with deepxiv_sdk endpoints: `GET /arxiv/` (search/head/brief/sections), `GET /pmc/` (head/full)
- [ ] Job queue (Celery + Redis or Ray) for parallel paper processing at small-cluster scale
- [ ] Benchmark evaluation: compare MinerU vs GROBID vs Docling on a sample of arXiv PDFs (section accuracy, table extraction quality)
- [ ] Citation graph: `paper_citations` edge table storing (source, target, context_text); REST endpoints for `/references`, `/cited_by`, `/related`
- [ ] Hybrid search: BM25 + pgvector semantic search on titles/abstracts (same PostgreSQL instance, no extra service)
- [ ] Fork deepxiv_sdk, point it at this backend, verify all existing SDK features work
- [ ] SDK fork: citation-aware agent — after reading a paper's sections, agent fetches sections of key cited papers (`in_corpus=True`) and incorporates that context before answering; depth configurable (default 1 hop)

### Out of Scope

- Full-text web scraping of gated publishers — only Open Access sources via official APIs/feeds
- Real-time on-demand PDF parsing (all parsing is pre-computed)
- [ ] Hybrid search: BM25 (PostgreSQL full-text) + semantic vector search (pgvector extension) on paper titles and abstracts — enables deepxiv-style discovery where agent finds papers by meaning, not just keywords
- Full RAG (chunked vector store) — chunking papers into fragments loses the structured section context that makes deepxiv's agentic reading work
- Kubernetes / production-scale deployment — single machine is sufficient for 10k papers

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
- **Scale:** ~10,000 papers total corpus, single machine + job queue; no Kubernetes
- **Domain scope:** Deep learning papers only (arXiv categories: cs.LG, cs.AI, cs.CV, cs.CL, stat.ML) — proves the pipeline on a well-defined, high-quality dataset
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
| pgvector for semantic search (not full RAG) | deepxiv uses BM25 + vector hybrid search on titles/abstracts; full chunked RAG loses structured section context; pgvector stays in PostgreSQL — no new service | — Pending |

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
