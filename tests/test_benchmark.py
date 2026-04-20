"""Unit tests for Phase 7 benchmark metrics and sample selection."""
import os
import sys
import json
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ---- Metric tests (enabled in Task 2 once metrics.py exists) ----

def test_heading_match_exact():
    from benchmark.metrics import heading_matched
    assert heading_matched("Introduction", ["Introduction"]) is True


def test_heading_match_80pct_token_overlap():
    from benchmark.metrics import heading_matched
    # 4-token GT, 4-token parser: 4/4 = 1.0 overlap after normalize (punctuation stripped)
    assert heading_matched("Results and Discussion of Experiments",
                           ["Results, and Discussion of Experiments"]) is True


def test_heading_match_below_threshold():
    from benchmark.metrics import heading_matched
    # "Results and Discussion" (3 tokens) vs "Results Discussion" (2 tokens) -> 2/3 = 0.67 < 0.8
    assert heading_matched("Results and Discussion", ["Results Discussion"]) is False


def test_heading_match_no_overlap():
    from benchmark.metrics import heading_matched
    assert heading_matched("Introduction", ["Methods"]) is False


def test_heading_match_case_and_punctuation_insensitive():
    from benchmark.metrics import heading_matched
    assert heading_matched("INTRODUCTION.", ["introduction"]) is True


def test_heading_match_empty_parser_heading():
    from benchmark.metrics import heading_matched
    assert heading_matched("", ["Introduction"]) is False


def test_compute_heading_match_rate_all_matched():
    from benchmark.metrics import compute_heading_match_rate
    rate = compute_heading_match_rate(
        parser_headings=["Introduction", "Methods", "Results"],
        gt_headings=["Introduction", "Methods", "Results"],
    )
    assert rate == 1.0


def test_compute_heading_match_rate_half_matched():
    from benchmark.metrics import compute_heading_match_rate
    rate = compute_heading_match_rate(
        parser_headings=["Introduction", "Methods"],
        gt_headings=["Introduction", "Methods", "Results", "Conclusion"],
    )
    assert rate == 0.5


def test_coherence_clean_text():
    from benchmark.metrics import coherent_section_pct
    sections = [{"text": "This is a short sentence. Another short one. Final."}]
    assert coherent_section_pct(sections) == 1.0


def test_coherence_garbled_long_sentences():
    from benchmark.metrics import coherent_section_pct
    # 100-word sentence, no periods -> degraded by _sentence_length_degraded
    long_sentence = " ".join(["word"] * 100)
    sections = [{"text": long_sentence}]
    assert coherent_section_pct(sections) == 0.0


def test_coherence_garbled_non_ascii():
    from benchmark.metrics import coherent_section_pct
    # >5% non-ASCII tokens
    sections = [{"text": "hello " + " ".join(["ééé"] * 5) + " world. Another sentence."}]
    assert coherent_section_pct(sections) == 0.0


def test_coherence_empty_sections():
    from benchmark.metrics import coherent_section_pct
    assert coherent_section_pct([]) == 0.0


def test_table_completeness_full():
    from benchmark.metrics import _table_completeness_score
    assert _table_completeness_score(has_caption=True, has_headers=True, has_data_rows=True) == 1.0


def test_table_completeness_caption_only():
    from benchmark.metrics import _table_completeness_score
    assert _table_completeness_score(has_caption=True, has_headers=False, has_data_rows=False) == 0.5


def test_table_completeness_absent():
    from benchmark.metrics import _table_completeness_score
    assert _table_completeness_score(has_caption=False, has_headers=False, has_data_rows=False) == 0.0


def test_normalize_heading_strips_punctuation():
    from benchmark.metrics import normalize_heading
    assert normalize_heading("1. Introduction!") == {"1", "introduction"}


# ---- CSV schema tests (Plan 07-02.5 — v2 schema supersedes D-17) ----

def test_csv_schema_columns():
    """CSV must have exactly the v2 column set (Plan 07-02.5).

    Asserts against benchmark.run_benchmark.CSV_COLUMNS so the expected set is a
    single source of truth and this test fails fast if the schema drifts.

    Behavior:
      - benchmark.csv absent              → skip (Task 6 not yet run).
      - benchmark.csv has v1 schema       → skip (pre-overhaul file; Task 6 will
                                           regenerate). Detected by presence of
                                           "heading_match_rate" column.
      - benchmark.csv has v2 schema       → assert column set + 600 rows.
    """
    csv_path = os.path.join(os.path.dirname(__file__), "..", "benchmark", "results", "benchmark.csv")
    if not os.path.exists(csv_path):
        pytest.skip("benchmark.csv not yet generated (Plan 07-02.5 Task 6)")
    import csv
    from benchmark.run_benchmark import CSV_COLUMNS  # type: ignore[import]
    expected = set(CSV_COLUMNS)
    with open(csv_path) as f:
        reader = csv.DictReader(f)
        field_set = set(reader.fieldnames or [])
        if "heading_match_rate" in field_set and "heading_f1" not in field_set:
            pytest.skip(
                "benchmark.csv is v1 schema (has heading_match_rate, missing heading_f1); "
                "Task 6 will regenerate with v2 schema."
            )
        assert field_set == expected, (
            f"benchmark.csv columns drift from CSV_COLUMNS; "
            f"missing={expected - field_set}, extra={field_set - expected}"
        )
        rows = list(reader)
        assert len(rows) == 600, f"expected 600 rows (150 papers × 4 conditions), got {len(rows)}"


def test_csv_columns_literal_v2_spec():
    """Lock the v2 column list as an explicit literal per 07-02.5 Task 5 spec.

    This guards against accidental column additions/removals in CSV_COLUMNS
    (the disk-CSV assertion above reads from CSV_COLUMNS, so without this test
    a typo in CSV_COLUMNS would be self-consistent but still wrong).
    """
    from benchmark.run_benchmark import CSV_COLUMNS  # type: ignore[import]
    expected = {
        # Identity
        "paper_id", "arxiv_id", "source_type", "column_layout", "subject",
        "condition",
        # Heading counts
        "heading_count_gt", "heading_count_parser",
        # v2 heading-quality triple (replaces v1 heading_match_rate)
        "heading_precision", "heading_recall", "heading_f1",
        # Hierarchy (router's differentiator)
        "hierarchy_f1",
        # Content richness
        "body_token_count",
        "figure_count_parser", "figure_count_gt",
        "formula_count_parser", "formula_count_gt",
        "reference_count_parser", "reference_count_gt",
        # Tables + coherence
        "table_presence", "table_structural_completeness",
        "coherent_section_pct",
        # Runtime / diagnostics
        "sec_per_doc", "error",
    }
    assert set(CSV_COLUMNS) == expected, (
        f"CSV_COLUMNS drift; missing={expected - set(CSV_COLUMNS)}, "
        f"extra={set(CSV_COLUMNS) - expected}"
    )
    # Column count sanity — catches stray duplicates.
    assert len(CSV_COLUMNS) == len(expected) == 24, (
        f"expected 24 columns, got {len(CSV_COLUMNS)}"
    )


# ---- Sample selection tests (enabled in Task 3) ----

def test_sample_json_structure():
    """benchmark/sample.json must exist with 150 entries (single-column corpus)."""
    sample_path = os.path.join(os.path.dirname(__file__), "..", "benchmark", "sample.json")
    if not os.path.exists(sample_path):
        pytest.skip("sample.json not yet generated (Task 3)")
    with open(sample_path) as f:
        sample = json.load(f)
    assert isinstance(sample, list)
    assert len(sample) == 150
    required_keys = {"paper_id", "arxiv_id", "source_type", "column_layout", "subject", "pdf_path"}
    for entry in sample:
        assert required_keys.issubset(entry.keys()), f"missing keys: {required_keys - set(entry.keys())}"
