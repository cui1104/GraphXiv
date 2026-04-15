"""Shared helper functions for parse tasks.

This module is imported by parse_latex (03-01), parse_jats (03-02),
parse_pdf_mineru (03-03), and the router (03-04). It MUST be created
before any of those plans execute.
"""

import re


def _backslash_ratio_degraded(text: str, threshold: float = 0.02) -> bool:
    """Check if >threshold fraction of whitespace-delimited tokens start with backslash.

    Used to detect TEX2JSON output that still contains raw LaTeX commands,
    indicating a degraded parse (PARSE-01).

    Args:
        text: The parsed body text to check.
        threshold: Fraction threshold (default 0.02 = 2%).

    Returns:
        True if backslash token ratio exceeds threshold.
    """
    tokens = text.split()
    if not tokens:
        return False
    backslash_count = sum(1 for t in tokens if t.startswith("\\"))
    return backslash_count / len(tokens) > threshold


def _strip_jats_doctype(raw: bytes) -> bytes:
    """Remove DOCTYPE declaration from JATS XML to prevent lxml DTD fetch hangs.

    Handles both simple DOCTYPE and DOCTYPE with internal subset [...].
    Per PARSE-02 / Pitfall 6.

    Args:
        raw: Raw XML bytes potentially containing DOCTYPE.

    Returns:
        XML bytes with DOCTYPE removed.
    """
    return re.sub(
        rb'<!DOCTYPE[^>]*(?:>|(?:\[.*?\])[^>]*>)',
        b'',
        raw,
        count=1,
        flags=re.DOTALL,
    )


def _has_text_layer(asset_path: str, threshold: int = 100) -> bool:
    """Check if a PDF has a meaningful text layer (not scanned).

    Uses pymupdf to extract text from all pages. If total text length
    is below threshold, the PDF is likely scanned/image-only.
    Per PARSE-03.

    Args:
        asset_path: Absolute path to PDF file.
        threshold: Minimum character count to consider text-bearing.

    Returns:
        True if PDF has text layer with >= threshold characters.
    """
    import pymupdf

    doc = pymupdf.open(asset_path)
    try:
        total_text = ""
        for page in doc:
            total_text += page.get_text()
        return len(total_text.strip()) >= threshold
    finally:
        doc.close()


def _sentence_length_degraded(text: str, threshold: int = 80) -> bool:
    """Check if average sentence length exceeds threshold words.

    Detects multi-column PDF concatenation artifacts where sentence
    boundaries are lost, producing abnormally long "sentences".
    Per PARSE-05.

    Args:
        text: Parsed text to check.
        threshold: Max average words per sentence before flagging degraded.

    Returns:
        True if average sentence length > threshold words.
    """
    sentences = [s.strip() for s in text.split(". ") if s.strip()]
    if not sentences:
        return False
    avg_words = sum(len(s.split()) for s in sentences) / len(sentences)
    return avg_words > threshold


def _count_pdf_tables(asset_path: str) -> int:
    """Count tables detected in a PDF using pymupdf heuristic.

    Uses pymupdf's find_tables() API to count tables across all pages.
    Used by D-03 routing logic: when no .tex file has \\documentclass,
    route to pdf_grobid if <=3 tables, pdf_mineru if >3 tables.

    Args:
        asset_path: Absolute path to PDF file.

    Returns:
        Total number of tables detected across all pages.
    """
    import pymupdf

    doc = pymupdf.open(asset_path)
    try:
        table_count = 0
        for page in doc:
            tables = page.find_tables()
            table_count += len(tables.tables)
        return table_count
    finally:
        doc.close()
