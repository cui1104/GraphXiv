"""GROBID reference extraction client.

Calls GROBID /api/processReferences to extract citation data from PDFs.
Returns list of citation dicts or [] on any failure (non-blocking per D-07).
"""

import logging
from lxml import etree
import httpx

logger = logging.getLogger(__name__)

GROBID_URL = "http://grobid:8070"
TEI_NS = "http://www.tei-c.org/ns/1.0"


def extract_references(pdf_path: str, timeout: int = 30) -> list[dict]:
    """POST PDF to GROBID /api/processReferences, return citation dicts.

    Returns [] on any failure -- GROBID is non-blocking (D-07).

    Args:
        pdf_path: Absolute path to PDF file on disk.
        timeout: HTTP timeout in seconds (default 30 per D-07).

    Returns:
        List of dicts with keys: title, authors, year, doi, raw_text.
        Empty list on any failure.
    """
    try:
        with open(pdf_path, "rb") as f:
            pdf_bytes = f.read()
        with httpx.Client(timeout=timeout) as client:
            resp = client.post(
                f"{GROBID_URL}/api/processReferences",
                files={"input": ("paper.pdf", pdf_bytes, "application/pdf")},
                data={"includeRawCitations": "1"},
            )
        if resp.status_code != 200:
            logger.warning("GROBID returned status %d for %s", resp.status_code, pdf_path)
            return []
        return _parse_tei_references(resp.content)
    except Exception as exc:
        logger.warning("GROBID call failed for %s: %s", pdf_path, exc)
        return []


def extract_fulltext(pdf_path: str, timeout: int = 60) -> tuple[list[dict], list[dict]]:
    """POST PDF to GROBID /api/processFulltextDocument, return (sections, citations).

    PRIMARY parser mode for D-03 cascade path (parse_pdf_grobid as primary).
    Returns ([], []) on any failure -- non-blocking per D-07.

    Args:
        pdf_path: Absolute path to PDF file on disk.
        timeout: HTTP timeout in seconds (default 60 -- fulltext is heavier than refs-only).

    Returns:
        Tuple of (sections, citations):
          sections: list of dicts with keys heading, sec_num, text, paragraphs, token_count
          citations: list of dicts with keys title, authors, year, doi, raw_text
        Both empty on any failure.
    """
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
            logger.warning(
                "GROBID processFulltextDocument returned status %d for %s",
                resp.status_code,
                pdf_path,
            )
            return [], []
        sections = _parse_tei_fulltext_sections(resp.content)
        citations = _parse_tei_references(resp.content)
        return sections, citations
    except Exception as exc:
        logger.warning("GROBID fulltext call failed for %s: %s", pdf_path, exc)
        return [], []


def _parse_tei_fulltext_sections(tei_xml: bytes) -> list[dict]:
    """Parse TEI XML body from GROBID processFulltextDocument into section dicts.

    Each section dict has keys: heading, sec_num, text, paragraphs, token_count.
    paragraphs is a list of dicts: {text, cite_spans, ref_spans}.
    token_count is 0 (filled in by normalizer using tiktoken).

    Returns empty list if body element is missing or parsing fails.
    """
    try:
        root = etree.fromstring(tei_xml)
        body = root.find(f".//{{{TEI_NS}}}body")
        if body is None:
            return []
        sections = []
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
                "token_count": 0,
            })
        return sections
    except Exception as exc:
        logger.warning("TEI fulltext section parse failed: %s", exc)
        return []


def _parse_tei_references(tei_xml: bytes) -> list[dict]:
    """Parse TEI XML from GROBID into citation dicts."""
    root = etree.fromstring(tei_xml)
    citations = []
    for bibl in root.iter(f"{{{TEI_NS}}}biblStruct"):
        analytic = bibl.find(f"{{{TEI_NS}}}analytic")
        monogr = bibl.find(f"{{{TEI_NS}}}monogr")

        # Title
        title_el = analytic.find(f"{{{TEI_NS}}}title") if analytic is not None else None
        if title_el is None and monogr is not None:
            title_el = monogr.find(f"{{{TEI_NS}}}title")
        title = title_el.text if title_el is not None else None

        # Authors
        authors = []
        author_source = analytic if analytic is not None else (monogr if monogr is not None else bibl)
        for pers in author_source.findall(f".//{{{TEI_NS}}}persName"):
            forename = pers.findtext(f"{{{TEI_NS}}}forename", default="")
            surname = pers.findtext(f"{{{TEI_NS}}}surname", default="")
            name = f"{forename} {surname}".strip()
            if name:
                authors.append(name)

        # Year
        date_el = bibl.find(f".//{{{TEI_NS}}}date[@type='published']")
        year_str = date_el.get("when", "")[:4] if date_el is not None else ""
        year = int(year_str) if year_str.isdigit() else None

        # DOI
        doi_el = bibl.find(f".//{{{TEI_NS}}}idno[@type='DOI']")
        doi = doi_el.text if doi_el is not None else None

        # Raw reference text
        raw_el = bibl.find(f"{{{TEI_NS}}}note[@type='raw_reference']")
        raw_text = raw_el.text if raw_el is not None else None

        citations.append({
            "title": title,
            "authors": authors,
            "year": year,
            "doi": doi,
            "raw_text": raw_text,
        })
    return citations
