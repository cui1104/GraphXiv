"""normalize_paper Celery task — maps parser outputs to unified PaperJSON schema.

Implements NORM-01 through NORM-06:
  NORM-01: Parser output → unified sections (S2ORC, MinerU, GROBID)
  NORM-02: token_count via tiktoken cl100k_base
  NORM-03: tldr always present (first 2-3 abstract sentences or None)
  NORM-04: SHA-256 dedup fingerprint; cross-source matching via id_map
  NORM-05: Consistent section and citation shapes
  NORM-06: parse_quality preserved from parser output
"""

import hashlib
import logging
import re
from celery import shared_task

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Celery task
# ---------------------------------------------------------------------------


@shared_task(
    bind=True,
    name="app.tasks.normalize.normalize_paper",
    max_retries=3,
    time_limit=60,
    soft_time_limit=50,
    default_retry_delay=10,
)
def normalize_paper(self, paper_id: str, parse_source: str) -> dict:
    """Normalize parser output and upsert to PostgreSQL.

    Reads paper.parse_source from DB (NOT the parse_source argument per Pitfall 1).
    Dispatches to correct normalization branch, enriches, deduplicates, upserts.

    Args:
        paper_id: String UUID of paper.canonical_id.
        parse_source: Hint from router chain — may be stale after D-03 cascade.
                      actual_parse_source is read from DB.
    """
    from app.db import SessionLocal
    from app.models import Paper, PaperSource

    session = SessionLocal()
    try:
        paper = session.query(Paper).filter(
            Paper.canonical_id == paper_id
        ).first()

        if paper is None:
            logger.warning("normalize_paper: paper %s not found", paper_id)
            return {"status": "not_found", "paper_id": paper_id}

        # Pitfall 1: always read from DB — router hint may be stale after D-03 cascade
        actual_parse_source = paper.parse_source
        raw = paper.content or {}

        if actual_parse_source in ("latex", "jats"):
            paper_json = _normalize_s2orc(raw, paper.parse_quality)
        elif actual_parse_source == "pdf_mineru":
            paper_json = _normalize_mineru(raw, paper.parse_quality)
        elif actual_parse_source == "pdf_grobid":
            paper_json = _normalize_grobid_fulltext(raw, paper.parse_quality)
        else:
            logger.warning(
                "normalize_paper: unknown parse_source %s for %s",
                actual_parse_source, paper_id,
            )
            return {"status": "unknown_source", "parse_source": actual_parse_source}

        # Pull structured metadata from paper object
        paper_json.setdefault("title", paper.title)
        paper_json.setdefault("abstract", paper.abstract)
        paper_json.setdefault("year", paper.year)

        # Enrichment
        _add_token_count(paper_json)
        _add_tldr(paper_json)
        _add_dedup_fingerprint(paper_json)

        # src_url from identifiers
        paper_json["src_url"] = _build_src_url(paper)

        # Dedup check — if matched, link via id_map and return early
        merged = _check_dedup_and_link(session, paper, paper_json)
        if merged:
            session.commit()
            return {"status": "merged", "paper_id": paper_id}

        # Upsert paper row
        _upsert_paper(session, paper, paper_json)

        # Update parse_status on active paper_source
        active_source = session.query(PaperSource).filter(
            PaperSource.canonical_id == paper_id,
            PaperSource.parse_status.in_(["success", "cascade_to_pdf_grobid", "pending"]),
        ).first()
        if active_source:
            active_source.parse_status = "success"

        # Upsert citations
        _upsert_citations(session, paper, paper_json.get("citations", []))

        session.commit()
        return {"status": "ok", "paper_id": paper_id, "parse_source": actual_parse_source}

    except Exception as exc:
        session.rollback()
        raise self.retry(exc=exc)
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Normalization helpers (pure functions, no DB access)
# ---------------------------------------------------------------------------


def _normalize_s2orc(raw: dict, parse_quality: str | None = None) -> dict:
    """Normalize S2ORC JSON (from TEX2JSON / JATS2JSON) into unified PaperJSON.

    Handles both top-level S2ORC and pdf_parse wrapper.
    Groups consecutive body_text paragraphs with same (section, sec_num) into sections.

    Args:
        raw: Parser output dict from paper.content.
        parse_quality: From paper.parse_quality, propagated to output.

    Returns:
        PaperJSON dict with keys: title, abstract, authors, sections, citations,
        ref_entries, back_matter, parse_source, parse_quality.
    """
    # Handle S2ORC pdf_parse wrapper
    pdf_parse = raw.get("pdf_parse") or raw

    title = pdf_parse.get("title") or raw.get("title")
    abstract = pdf_parse.get("abstract") or raw.get("abstract")
    authors_raw = pdf_parse.get("authors") or raw.get("authors", [])
    body_text = pdf_parse.get("body_text", [])
    bib_entries = pdf_parse.get("bib_entries", {})
    ref_entries = pdf_parse.get("ref_entries", {})
    back_matter = pdf_parse.get("back_matter", [])

    # Group consecutive paragraphs by (section, sec_num)
    sections = []
    current_key = None
    current_heading = None
    current_sec_num = None
    current_texts = []

    for para in body_text:
        heading = para.get("section") or ""
        sec_num = para.get("sec_num")
        key = (heading, sec_num)
        text = para.get("text") or ""

        if key != current_key:
            if current_key is not None and (current_texts or current_heading):
                sections.append(
                    _make_section(current_heading or "", current_sec_num, current_texts)
                )
            current_key = key
            current_heading = heading
            current_sec_num = sec_num
            current_texts = [text] if text else []
        else:
            if text:
                current_texts.append(text)

    # Flush last section
    if current_key is not None and (current_texts or current_heading):
        sections.append(_make_section(current_heading or "", current_sec_num, current_texts))

    # Citations from bib_entries
    s2orc_citations = _bib_entries_to_citations(bib_entries)

    # Merge GROBID citations if present
    grobid_raw = raw.get("grobid_citations", [])
    if grobid_raw:
        grobid_cits = _grobid_raw_to_citations(grobid_raw)
        citations = _merge_citations(s2orc_citations, grobid_cits)
    else:
        citations = s2orc_citations

    return {
        "title": title,
        "abstract": abstract,
        "authors": _flatten_authors(authors_raw),
        "sections": sections,
        "citations": citations,
        "ref_entries": ref_entries,
        "back_matter": back_matter,
        "parse_source": "s2orc",
        "parse_quality": parse_quality,
    }


def _normalize_mineru(raw: dict, parse_quality: str | None = None) -> dict:
    """Normalize MinerU content_list into unified PaperJSON.

    MinerU returns flat content_list with type==title and type==text.
    Per Pitfall 2: if no title blocks found, create single section with heading="".

    Args:
        raw: Parser output dict from paper.content.
        parse_quality: From paper.parse_quality.

    Returns:
        PaperJSON dict.
    """
    content_list = raw.get("content_list", [])

    sections = []
    current_heading = None
    current_sec_num = None
    current_texts = []

    has_titles = any(item.get("type") == "title" for item in content_list)

    if not has_titles:
        # Pitfall 2: no heading hierarchy — single section
        all_texts = [
            item.get("text", "")
            for item in content_list
            if item.get("type") == "text" and item.get("text")
        ]
        sections = [_make_section("", None, all_texts)]
    else:
        for item in content_list:
            item_type = item.get("type")
            text = item.get("text") or ""

            if item_type == "title":
                # Flush previous section
                if current_heading is not None or current_texts:
                    sections.append(
                        _make_section(current_heading or "", current_sec_num, current_texts)
                    )
                current_heading = text
                current_sec_num = item.get("sec_num")
                current_texts = []
            elif item_type == "text" and text:
                current_texts.append(text)

        # Flush last section
        if current_heading is not None or current_texts:
            sections.append(
                _make_section(current_heading or "", current_sec_num, current_texts)
            )

    # Citations from GROBID enrichment
    grobid_raw = raw.get("grobid_citations", [])
    citations = _grobid_raw_to_citations(grobid_raw) if grobid_raw else []

    return {
        "title": raw.get("title"),
        "abstract": raw.get("abstract"),
        "authors": _flatten_authors(raw.get("authors", [])),
        "sections": sections,
        "citations": citations,
        "ref_entries": {},
        "back_matter": [],
        "parse_source": "mineru",
        "parse_quality": parse_quality,
    }


def _normalize_grobid_fulltext(raw: dict, parse_quality: str | None = None) -> dict:
    """Normalize GROBID fulltext output (pdf_grobid primary mode).

    Sections are already in correct shape from parse_pdf_grobid (Plan 04-01).

    Args:
        raw: Parser output dict from paper.content (has grobid_sections + grobid_citations).
        parse_quality: From paper.parse_quality.

    Returns:
        PaperJSON dict.
    """
    sections = raw.get("grobid_sections", [])
    grobid_raw = raw.get("grobid_citations", [])
    citations = _grobid_raw_to_citations(grobid_raw) if grobid_raw else []

    return {
        "title": raw.get("title"),
        "abstract": raw.get("abstract"),
        "authors": _flatten_authors(raw.get("authors", [])),
        "sections": sections,
        "citations": citations,
        "ref_entries": {},
        "back_matter": [],
        "parse_source": "pdf_grobid",
        "parse_quality": parse_quality,
    }


def _make_section(heading: str, sec_num, texts: list[str]) -> dict:
    """Build a unified section dict.

    Args:
        heading: Section heading string (empty string if absent).
        sec_num: Section number string or None.
        texts: List of paragraph text strings.

    Returns:
        Dict with keys: heading, sec_num, text, paragraphs, token_count.
    """
    full_text = " ".join(t for t in texts if t)
    paragraphs = [
        {"text": t, "cite_spans": [], "ref_spans": []}
        for t in texts
        if t
    ]
    return {
        "heading": heading or "",
        "sec_num": sec_num,
        "text": full_text,
        "paragraphs": paragraphs,
        "token_count": 0,
    }


def _flatten_authors(authors_raw: list) -> list[str]:
    """Flatten author list to list of name strings.

    Handles both dict-style authors ({"first": ..., "last": ...}) and plain strings.

    Args:
        authors_raw: List from parser output.

    Returns:
        List of name strings.
    """
    if not authors_raw or not isinstance(authors_raw, list):
        return []
    first = authors_raw[0]
    if isinstance(first, dict):
        return [
            f"{a.get('first', '')} {a.get('last', '')}".strip()
            for a in authors_raw
            if isinstance(a, dict)
        ]
    elif isinstance(first, str):
        return list(authors_raw)
    return []


def _bib_entries_to_citations(bib_entries: dict) -> list[dict]:
    """Convert S2ORC bib_entries dict to list of citation dicts.

    Args:
        bib_entries: Dict mapping ref_id to bib metadata (from S2ORC).

    Returns:
        List of citation dicts with keys: ref_id, title, authors, year, venue,
        doi, arxiv_id, raw_text.
    """
    citations = []
    for ref_id, bib in bib_entries.items():
        authors_raw = bib.get("authors", [])
        # Pitfall 6: authors may be dicts — always flatten to strings
        authors = _flatten_authors(authors_raw) if authors_raw else []
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


def _grobid_raw_to_citations(grobid_cits: list[dict]) -> list[dict]:
    """Convert GROBID raw citation dicts to unified citation shape.

    Args:
        grobid_cits: List from extract_references / extract_fulltext output.

    Returns:
        List of citation dicts with ref_id as BIBREFn.
    """
    return [
        {
            "ref_id": f"BIBREF{i}",
            "title": cit.get("title"),
            "authors": cit.get("authors", []),
            "year": cit.get("year"),
            "venue": None,
            "doi": cit.get("doi"),
            "arxiv_id": None,
            "raw_text": cit.get("raw_text"),
        }
        for i, cit in enumerate(grobid_cits)
    ]


def _merge_citations(primary: list[dict], secondary: list[dict]) -> list[dict]:
    """Merge two citation lists; secondary fills gaps in primary.

    For each secondary citation: if title matches primary (case-insensitive),
    merge missing fields (doi, raw_text). Otherwise append as new citation.

    Args:
        primary: S2ORC bib_entries citations (authoritative for ref_id keys).
        secondary: GROBID citations (may have DOI/raw_text the S2ORC lacked).

    Returns:
        Merged citation list.
    """
    merged = list(primary)
    primary_titles = {
        (c.get("title") or "").lower(): i
        for i, c in enumerate(merged)
        if c.get("title")
    }

    for sec_cit in secondary:
        sec_title = (sec_cit.get("title") or "").lower()
        if sec_title and sec_title in primary_titles:
            idx = primary_titles[sec_title]
            # Fill missing fields
            if not merged[idx].get("doi") and sec_cit.get("doi"):
                merged[idx]["doi"] = sec_cit["doi"]
            if not merged[idx].get("raw_text") and sec_cit.get("raw_text"):
                merged[idx]["raw_text"] = sec_cit["raw_text"]
        else:
            # Append with new ref_id to avoid collision
            new_cit = dict(sec_cit)
            new_cit["ref_id"] = f"GROBID_{len(merged)}"
            merged.append(new_cit)

    return merged


# ---------------------------------------------------------------------------
# Enrichment functions (mutate paper_json in place)
# ---------------------------------------------------------------------------


def _add_token_count(paper_json: dict) -> None:
    """Add token_count to paper_json and per-section using tiktoken cl100k_base.

    Mutates paper_json in place.
    """
    import tiktoken
    enc = tiktoken.get_encoding("cl100k_base")

    sections = paper_json.get("sections", [])
    total_tokens = 0

    for sec in sections:
        text = sec.get("text") or ""
        count = len(enc.encode(text)) if text.strip() else 0
        sec["token_count"] = count
        total_tokens += count

    paper_json["token_count"] = total_tokens


def _add_tldr(paper_json: dict) -> None:
    """Add tldr to paper_json from first 2-3 abstract sentences.

    tldr key is ALWAYS set (to str or None). Mutates paper_json in place.
    """
    abstract = paper_json.get("abstract") or ""
    paper_json["tldr"] = _compute_tldr(abstract)["tldr"]


def _add_dedup_fingerprint(paper_json: dict) -> None:
    """Add dedup_fingerprint to paper_json.

    SHA-256 of normalized_title|first_author_last_name|year.
    Sets None if any field is missing. Mutates paper_json in place.
    """
    title = paper_json.get("title") or ""
    authors = paper_json.get("authors") or []
    year = paper_json.get("year")

    if not title or not authors or not year:
        paper_json["dedup_fingerprint"] = None
        return

    first_author = authors[0] if authors else ""
    paper_json["dedup_fingerprint"] = _compute_dedup_fingerprint(
        title=title,
        first_author_last=first_author.split()[-1] if first_author else "",
        year=year,
    )


# ---------------------------------------------------------------------------
# Pure computation helpers (for unit testing)
# ---------------------------------------------------------------------------


def _compute_token_count(text: str) -> int:
    """Compute token count for a text string using tiktoken cl100k_base.

    Args:
        text: Input text string.

    Returns:
        Integer token count.
    """
    import tiktoken
    enc = tiktoken.get_encoding("cl100k_base")
    if not text or not text.strip():
        return 0
    return len(enc.encode(text))


def _compute_tldr(abstract: str | None) -> dict:
    """Compute tldr from abstract text.

    Returns dict with "tldr" key (always present) set to string or None.

    Args:
        abstract: Full abstract text or None.

    Returns:
        Dict {"tldr": str | None}.
    """
    if not abstract or not abstract.strip():
        return {"tldr": None}

    # Split on ". " boundary
    if ". " in abstract:
        parts = abstract.split(". ")
        sentences = [s.strip() for s in parts if s.strip()]
        tldr_sentences = sentences[:3]
        tldr = ". ".join(tldr_sentences)
        # Re-add period if original ended with period
        if not tldr.endswith("."):
            tldr += "."
    else:
        # No sentence boundary — use entire abstract
        tldr = abstract.strip()

    return {"tldr": tldr}


def _compute_dedup_fingerprint(
    title: str,
    first_author_last: str,
    year: int,
) -> str | None:
    """Compute SHA-256 dedup fingerprint from title, first author last name, year.

    Format: sha256("{normalized_title}|{normalized_last_name}|{year}")

    Args:
        title: Paper title string.
        first_author_last: Last name of first author.
        year: Publication year (integer).

    Returns:
        64-char hex string or None if inputs are insufficient.
    """
    if not title or not first_author_last or not year:
        return None

    norm_title = re.sub(r"[^a-z0-9]", "", title.lower())
    last_name = re.sub(r"[^a-z0-9]", "", first_author_last.lower())
    raw = f"{norm_title}|{last_name}|{year}"
    return hashlib.sha256(raw.encode()).hexdigest()


# ---------------------------------------------------------------------------
# URL builder
# ---------------------------------------------------------------------------


def _build_src_url(paper) -> str:
    """Build canonical source URL from paper identifiers.

    Args:
        paper: Paper ORM object with arxiv_id and pmc_id attributes.

    Returns:
        URL string, or empty string if no identifier available.
    """
    if paper.arxiv_id:
        return f"https://arxiv.org/abs/{paper.arxiv_id}"
    if paper.pmc_id:
        return f"https://www.ncbi.nlm.nih.gov/pmc/articles/{paper.pmc_id}/"
    return ""


# ---------------------------------------------------------------------------
# DB upsert helpers
# ---------------------------------------------------------------------------


def _check_dedup_and_link(session, paper, paper_json: dict) -> bool:
    """Check for duplicate papers by dedup fingerprint; link via id_map if found.

    Args:
        session: SQLAlchemy session.
        paper: Paper ORM object being normalized.
        paper_json: Normalized paper dict with dedup_fingerprint key.

    Returns:
        True if a duplicate was found and linked (caller should skip upsert).
        False otherwise.
    """
    from sqlalchemy import text
    from app.models import IdMap

    fp = paper_json.get("dedup_fingerprint")
    if not fp:
        return False

    row = session.execute(
        text(
            "SELECT canonical_id, arxiv_id, pmc_id FROM papers"
            " WHERE content->>'dedup_fingerprint' = :fp"
            " AND canonical_id != :cid LIMIT 1"
        ),
        {"fp": fp, "cid": str(paper.canonical_id)},
    ).fetchone()

    if row is None:
        return False

    # Link this paper's identifiers to the existing canonical record
    canonical_id = row[0]
    id_map_row = IdMap(
        canonical_id=canonical_id,
        arxiv_id=paper.arxiv_id,
        pmc_id=paper.pmc_id,
        doi=paper.doi,
    )
    session.merge(id_map_row)
    return True


def _upsert_paper(session, paper, paper_json: dict) -> None:
    """Upsert Paper row with normalized content.

    Uses PostgreSQL INSERT ... ON CONFLICT DO UPDATE.

    Args:
        session: SQLAlchemy session.
        paper: Paper ORM object (source of canonical_id).
        paper_json: Normalized paper dict.
    """
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    from sqlalchemy import func
    from app.models import Paper

    stmt = pg_insert(Paper.__table__).values(
        canonical_id=paper.canonical_id,
        arxiv_id=paper.arxiv_id,
        pmc_id=paper.pmc_id,
        doi=paper.doi,
        title=paper_json.get("title") or paper.title,
        abstract=paper_json.get("abstract") or paper.abstract,
        year=paper_json.get("year") or paper.year,
        parse_source=paper.parse_source,
        parse_quality=paper_json.get("parse_quality"),
        token_count=paper_json.get("token_count"),
        tldr=paper_json.get("tldr"),
        content=paper_json,
        updated_at=func.now(),
    ).on_conflict_do_update(
        index_elements=["canonical_id"],
        set_={
            "content": paper_json,
            "token_count": paper_json.get("token_count"),
            "tldr": paper_json.get("tldr"),
            "parse_source": paper.parse_source,
            "parse_quality": paper_json.get("parse_quality"),
            "title": paper_json.get("title") or paper.title,
            "abstract": paper_json.get("abstract") or paper.abstract,
            "updated_at": func.now(),
        },
    )
    session.execute(stmt)


def _upsert_citations(session, paper, citations: list[dict]) -> None:
    """Upsert citations to paper_citations table with id_map resolution.

    Resolves target_paper_id from IdMap when possible.
    Skips citations without target_arxiv_id or target_doi (no conflict key).

    Args:
        session: SQLAlchemy session.
        paper: Source paper ORM object.
        citations: List of citation dicts from normalized paper_json.
    """
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    from app.models import PaperCitation, IdMap

    for cit in citations:
        target_arxiv_id = cit.get("arxiv_id")
        target_doi = cit.get("doi")

        # Skip citations with no identifying key — can't upsert without conflict target
        if not target_arxiv_id and not target_doi:
            continue

        # Resolve target_paper_id via id_map
        target_paper_id = None
        if target_arxiv_id:
            id_row = session.query(IdMap).filter(
                IdMap.arxiv_id == target_arxiv_id
            ).first()
            if id_row:
                target_paper_id = id_row.canonical_id
        if target_paper_id is None and target_doi:
            id_row = session.query(IdMap).filter(IdMap.doi == target_doi).first()
            if id_row:
                target_paper_id = id_row.canonical_id

        if target_arxiv_id:
            # Has unique constraint on (source_paper_id, target_arxiv_id) — safe to upsert
            stmt = pg_insert(PaperCitation.__table__).values(
                source_paper_id=paper.canonical_id,
                target_paper_id=target_paper_id,
                target_arxiv_id=target_arxiv_id,
                target_doi=target_doi,
                context_text=cit.get("raw_text"),
            ).on_conflict_do_update(
                constraint="uq_paper_citations_source_target_arxiv",
                set_={
                    "context_text": cit.get("raw_text"),
                    "target_paper_id": target_paper_id,
                },
            )
        else:
            # doi-only: no unique constraint on doi — use DO NOTHING
            stmt = pg_insert(PaperCitation.__table__).values(
                source_paper_id=paper.canonical_id,
                target_paper_id=target_paper_id,
                target_arxiv_id=None,
                target_doi=target_doi,
                context_text=cit.get("raw_text"),
            ).on_conflict_do_nothing()

        session.execute(stmt)
