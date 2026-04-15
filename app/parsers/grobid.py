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
