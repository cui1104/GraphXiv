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


# ---- CSV schema tests (enabled in Plan 07-02) ----

def test_csv_schema_columns():
    """CSV must have exactly these columns per D-17. Enabled when benchmark.csv is generated."""
    csv_path = os.path.join(os.path.dirname(__file__), "..", "benchmark", "results", "benchmark.csv")
    if not os.path.exists(csv_path):
        pytest.skip("benchmark.csv not yet generated (Plan 07-02)")
    import csv
    with open(csv_path) as f:
        reader = csv.DictReader(f)
        expected = {
            "paper_id", "arxiv_id", "source_type", "column_layout", "subject",
            "condition", "heading_count_gt", "heading_count_parser",
            "heading_match_rate", "coherent_section_pct",
            "table_presence", "table_structural_completeness", "error",
        }
        assert set(reader.fieldnames) == expected
        rows = list(reader)
        assert len(rows) == 600, f"expected 600 rows (150 papers × 4 conditions), got {len(rows)}"


# ---- Sample selection tests (enabled in Task 3) ----

def test_sample_json_structure():
    """benchmark/sample.json must exist with 150 entries; >=30 two-column."""
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
    two_col = [e for e in sample if e["column_layout"] == "two"]
    assert len(two_col) >= 30, f"expected >=30 two-column papers, got {len(two_col)}"
