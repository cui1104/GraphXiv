"""Benchmark metric library — Phase 7.

Pure functions used by run_benchmark.py (Plan 07-02) and analyze_results.py (Plan 07-03).
No network, no DB, no heavy imports at module level.

Implements D-10 (heading match >=80% token overlap), D-11 (coherence dual signal),
D-19 (table completeness 0.0/0.5/1.0), and two-column detection (Pattern 6).
"""

import os
import string
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Reuse existing helper — DO NOT reimplement (Pitfall: duplicating project logic).
from app.tasks.parse_helpers import _sentence_length_degraded


# ============================================================
# Heading match (D-10)
# ============================================================

def normalize_heading(h: str) -> set:
    """Lowercase + strip punctuation, return set of non-empty tokens.

    Example:
        normalize_heading("1. Introduction!") == {"1", "introduction"}
    """
    if not h:
        return set()
    h = h.lower()
    h = h.translate(str.maketrans("", "", string.punctuation))
    return {t for t in h.split() if t}


def heading_matched(parser_heading: str, gt_headings: list, threshold: float = 0.8) -> bool:
    """True if any gt_heading has token overlap >= threshold with parser_heading.

    overlap = |A ∩ B| / max(|A|, |B|) per 07-RESEARCH.md Pattern 3.
    D-10: threshold = 0.8 default.
    """
    p_tokens = normalize_heading(parser_heading)
    if not p_tokens:
        return False
    for gt in gt_headings:
        g_tokens = normalize_heading(gt)
        if not g_tokens:
            continue
        overlap = len(p_tokens & g_tokens) / max(len(p_tokens), len(g_tokens))
        if overlap >= threshold:
            return True
    return False


def compute_heading_match_rate(parser_headings: list, gt_headings: list) -> float:
    """Fraction of GT headings for which SOME parser heading passes heading_matched.

    BENCH-02 metric: heading match rate per (paper, condition) pair.
    Returns 0.0 when gt_headings is empty.
    """
    if not gt_headings:
        return 0.0
    matched = 0
    for gt in gt_headings:
        if heading_matched(gt, parser_headings):
            matched += 1
    return matched / len(gt_headings)


def compute_heading_precision_recall_f1(
    parser_headings: list,
    gt_headings: list,
    threshold: float = 0.8,
) -> tuple:
    """Recall-aware heading evaluation — returns (precision, recall, f1).

    Uses the same `heading_matched` normalisation/token-overlap rule as v1 but
    produces all three signals so we stop rewarding under-extraction (v1
    `heading_match_rate` is precision-only; GROBID wins by emitting fewer
    headings — see 07-02-SUMMARY key_decisions).

    Definitions:
      precision = | parser headings that match SOME gt heading | / |parser headings|
      recall    = | gt headings matched by SOME parser heading | / |gt headings|
      f1        = 2 * p * r / (p + r) when p + r > 0 else 0.0

    Edge cases:
      - both empty:           (0.0, 0.0, 0.0)
      - parser empty:         (0.0, 0.0, 0.0)
      - gt empty:             (0.0, 0.0, 0.0)

    Args:
        parser_headings: strings emitted by the parser.
        gt_headings: GT strings (may be raw strings or {"text": str, ...} dicts; .get("text") is honored).
        threshold: token-overlap threshold (default 0.8, matches D-10).
    """
    gt_texts = _coerce_heading_strings(gt_headings)
    parser_texts = _coerce_heading_strings(parser_headings)
    if not parser_texts or not gt_texts:
        return 0.0, 0.0, 0.0
    # Precision — how many parser headings find at least one gt match?
    matched_parser = sum(
        1 for ph in parser_texts
        if heading_matched(ph, gt_texts, threshold=threshold)
    )
    precision = matched_parser / len(parser_texts)
    # Recall — how many gt headings are matched by at least one parser heading?
    matched_gt = sum(
        1 for gt in gt_texts
        if heading_matched(gt, parser_texts, threshold=threshold)
    )
    recall = matched_gt / len(gt_texts)
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0
    return precision, recall, f1


def _coerce_heading_strings(items) -> list:
    """Accept list of strings OR list of {text, ...} dicts; return list of strings."""
    out = []
    for it in items or []:
        if isinstance(it, str):
            out.append(it)
        elif isinstance(it, dict):
            t = it.get("text") or it.get("heading") or ""
            if t:
                out.append(t)
    return out


# ============================================================
# Hierarchy F1 (Plan 07-02.5 — router's claimed unique win)
# ============================================================

def compute_hierarchy_f1(parser_sections: list, gt_sections: list, threshold: float = 0.8) -> float:
    """F1 over (normalized_heading, depth) pairs — depth-aware heading match.

    Each GT heading carries an implicit depth derived from its sec_num dot
    count (".1" = 2, "1" = 1). Each parser section similarly — the router's
    _apply_dot_count_hierarchy adds `depth` to router-produced sections; other
    conditions leave sections without depth, so their (heading, depth) tuples
    collapse to (heading, None) and cannot match GT (heading, int_depth).
    This is by design — the router is the only parser that EARNS hierarchy
    credit.

    Args:
        parser_sections: list of dicts with {heading, depth, sec_num, ...}.
        gt_sections: list of dicts with {text, sec_num} (GT v2 schema).
                     Depth is inferred from sec_num.count(".") + 1.
        threshold: token overlap threshold for heading normalization (D-10 compat).

    Returns:
        F1 in [0.0, 1.0]. Returns 0.0 if either side empty or no valid
        (heading, depth) pairs on either side.
    """
    parser_pairs = _section_pairs(parser_sections)
    gt_pairs = _section_pairs(gt_sections)
    if not parser_pairs or not gt_pairs:
        return 0.0
    # Greedy matching: each gt_pair consumed by at most one parser_pair.
    gt_pool = list(gt_pairs)
    tp = 0
    for ph, pd in parser_pairs:
        for idx, (gh, gd) in enumerate(gt_pool):
            if pd != gd:
                continue
            if heading_matched(ph, [gh], threshold=threshold):
                tp += 1
                gt_pool.pop(idx)
                break
    precision = tp / len(parser_pairs) if parser_pairs else 0.0
    recall = tp / len(gt_pairs) if gt_pairs else 0.0
    if precision + recall == 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)


def _section_pairs(sections: list) -> list:
    """Return list of (heading_text, depth_int) pairs; skip rows with no depth.

    Accepts:
      - parser shape: {"heading": ..., "depth": int|None, "sec_num": str|None, ...}
      - GT v2 shape:  {"text": ..., "sec_num": str} — depth inferred from sec_num.

    Rows without a resolvable depth are skipped (the whole point of hierarchy_f1
    is that sec_num-less parsers score 0.0).
    """
    out = []
    for sec in sections or []:
        if not isinstance(sec, dict):
            continue
        heading = sec.get("heading") or sec.get("text") or ""
        if not heading:
            continue
        depth = sec.get("depth")
        if depth is None:
            sn = sec.get("sec_num")
            if isinstance(sn, str) and sn:
                depth = sn.count(".") + 1
        if depth is None:
            continue
        try:
            depth_int = int(depth)
        except (TypeError, ValueError):
            continue
        out.append((heading, depth_int))
    return out


# ============================================================
# Body token count (Plan 07-02.5 — content-richness metric)
# ============================================================

def body_token_count(sections: list) -> int:
    """Sum of tiktoken cl100k_base token counts across section.text.

    Matches the encoder used in app/tasks/normalize.py::_compute_token_count
    for consistency with the production pipeline. Returns 0 if sections is
    empty or all texts are blank.

    tiktoken is imported lazily to keep this module import-cheap (metrics.py
    is imported by the test suite).
    """
    if not sections:
        return 0
    import tiktoken  # lazy
    enc = tiktoken.get_encoding("cl100k_base")
    total = 0
    for sec in sections:
        if not isinstance(sec, dict):
            continue
        text = sec.get("text") or ""
        if text and text.strip():
            total += len(enc.encode(text))
    return total


# ============================================================
# Structural count passthroughs (Plan 07-02.5)
# ============================================================
# Identity passthroughs — exist so run_benchmark.py has a single call-site
# surface for structural metrics, and so unit tests can assert the contract
# (dict keys, missing-key defaults) without poking at the counting code.

def count_figures(struct_counts: dict) -> int:
    """Return struct_counts['figure_count'], or 0 if missing/invalid."""
    if not isinstance(struct_counts, dict):
        return 0
    val = struct_counts.get("figure_count", 0)
    try:
        return int(val)
    except (TypeError, ValueError):
        return 0


def count_formulas(struct_counts: dict) -> int:
    """Return struct_counts['formula_count'], or 0 if missing/invalid."""
    if not isinstance(struct_counts, dict):
        return 0
    val = struct_counts.get("formula_count", 0)
    try:
        return int(val)
    except (TypeError, ValueError):
        return 0


def count_references(struct_counts: dict) -> int:
    """Return struct_counts['reference_count'], or 0 if missing/invalid."""
    if not isinstance(struct_counts, dict):
        return 0
    val = struct_counts.get("reference_count", 0)
    try:
        return int(val)
    except (TypeError, ValueError):
        return 0


# ============================================================
# Coherence (D-11 dual signal)
# ============================================================

def _non_ascii_ratio_degraded(text: str, threshold: float = 0.05) -> bool:
    """True if >threshold of whitespace-split tokens contain non-ASCII or no alpha chars."""
    tokens = text.split()
    if not tokens:
        return False
    bad = sum(
        1 for t in tokens
        if not t.isascii() or not any(c.isalpha() for c in t)
    )
    return bad / len(tokens) > threshold


def section_is_coherent(text: str) -> bool:
    """True iff BOTH sentence-length AND non-ASCII signals are within threshold.

    Per D-11: section is coherent only when both pass.
    """
    if not text or not text.strip():
        return False
    return (
        not _sentence_length_degraded(text, threshold=80)
        and not _non_ascii_ratio_degraded(text, threshold=0.05)
    )


def coherent_section_pct(sections: list) -> float:
    """Fraction of non-empty sections where section_is_coherent(text) is True.

    BENCH-02 metric: coherent_section_pct per (paper, condition) pair.
    Returns 0.0 when sections is empty or all sections have empty text.
    """
    texts = [s.get("text", "") for s in sections if s.get("text", "").strip()]
    if not texts:
        return 0.0
    return sum(1 for t in texts if section_is_coherent(t)) / len(texts)


# ============================================================
# Table completeness (D-19)
# ============================================================

def _table_completeness_score(has_caption: bool, has_headers: bool, has_data_rows: bool) -> float:
    """D-19: 1.0 = caption + headers + >=1 data row; 0.5 = caption only; 0.0 = absent/empty."""
    if has_caption and has_headers and has_data_rows:
        return 1.0
    if has_caption:
        return 0.5
    return 0.0


def table_completeness_docling(table_item, doc) -> float:
    """Score a Docling TableItem per D-19.

    Uses table_item.export_to_dataframe(doc=doc) — Pitfall 9: doc kwarg is REQUIRED.
    """
    try:
        df = table_item.export_to_dataframe(doc=doc)
        has_caption = bool(getattr(table_item, "caption", None))
        has_headers = (
            len(df.columns) > 0
            and not all(str(c).startswith("Unnamed") for c in df.columns)
        )
        has_data_rows = len(df) >= 1
        return _table_completeness_score(has_caption, has_headers, has_data_rows)
    except Exception:
        return 0.0


def table_completeness_grobid(tei_xml_bytes: bytes) -> list:
    """Score each table in GROBID TEI XML per D-19.

    GROBID encodes tables as <figure type="table"> with <figDesc> (caption)
    and <table><row><cell>...</cell></row></table> children.
    """
    from lxml import etree  # type: ignore[attr-defined]
    TEI_NS = "http://www.tei-c.org/ns/1.0"
    try:
        root = etree.fromstring(tei_xml_bytes)
    except Exception:
        return []
    scores = []
    for fig in root.iter(f"{{{TEI_NS}}}figure"):
        if fig.get("type") != "table":
            continue
        has_caption = fig.find(f"{{{TEI_NS}}}figDesc") is not None
        table_el = fig.find(f"{{{TEI_NS}}}table")
        if table_el is None:
            scores.append(_table_completeness_score(has_caption, False, False))
            continue
        rows = table_el.findall(f".//{{{TEI_NS}}}row")
        has_data_rows = len(rows) >= 2  # header row + >=1 data row
        header_cells = rows[0].findall(f"{{{TEI_NS}}}cell") if rows else []
        has_headers = len(header_cells) > 0
        scores.append(_table_completeness_score(has_caption, has_headers, has_data_rows))
    return scores


def table_completeness_mineru(content_list: list) -> list:
    """Score each table in MinerU content_list per D-19.

    MinerU tables: {"type": "table", "img_path": ..., "table_caption": [...], "table_body": "<html>...", "table_footnote": [...]}.
    has_caption = table_caption non-empty.
    has_headers + has_data_rows = parse table_body HTML for <th>/<td> counts.
    """
    scores = []
    for item in content_list:
        if item.get("type") != "table":
            continue
        caption = item.get("table_caption") or []
        has_caption = bool(caption) and any(str(c).strip() for c in caption)
        body = item.get("table_body") or ""
        # Heuristic header detection: any <th> tag, OR first row's <tr><td> content
        has_headers = "<th" in body.lower() or ("<tr" in body.lower() and "<td" in body.lower())
        # Data rows: count <tr> minus 1 (header row)
        tr_count = body.lower().count("<tr")
        has_data_rows = tr_count >= 2 or (has_headers and tr_count >= 1)
        scores.append(_table_completeness_score(has_caption, has_headers, has_data_rows))
    return scores


# ============================================================
# Two-column detection (Pattern 6)
# ============================================================

def is_two_column(pdf_path: str, sample_pages: int = 3) -> bool:
    """Heuristic: True if text blocks cluster in two x-coordinate groups.

    Per 07-RESEARCH.md Pattern 6. Called by select_sample.py as the second filter
    (parse_quality degradation flag first, this PDF heuristic second, per D-05).
    """
    import pymupdf  # type: ignore[import-untyped]
    doc = pymupdf.open(pdf_path)
    try:
        if len(doc) == 0:
            return False
        page_width = doc[0].rect.width
        mid = page_width / 2
        left_blocks = 0
        right_blocks = 0
        pages_to_scan = min(sample_pages, len(doc))
        for i in range(pages_to_scan):
            page = doc[i]
            blocks = page.get_text("dict").get("blocks", [])
            for block in blocks:
                if block.get("type") != 0:  # text blocks only
                    continue
                bbox = block.get("bbox")
                if not bbox or len(bbox) < 4:
                    continue
                x0, _, x1, _ = bbox
                width = x1 - x0
                if width < page_width * 0.55:  # narrow blocks = genuine column
                    if x0 < mid * 0.6:
                        left_blocks += 1
                    elif x0 > mid * 0.9:
                        right_blocks += 1
        return left_blocks >= 3 and right_blocks >= 3
    finally:
        doc.close()
