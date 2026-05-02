# pyright: reportMissingImports=false
"""Unit tests for Phase 7 benchmark metrics and sample selection.

benchmark.* modules are resolved at runtime via sys.path insert below; Pyright
cannot follow the dynamic path, so reportMissingImports is suppressed file-wide.
"""
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
    # Leading arabic section number "1." is stripped by the prefix rule.
    assert normalize_heading("1. Introduction!") == {"introduction"}


def test_normalize_heading_strips_section_number_arabic():
    from benchmark.metrics import normalize_heading, heading_matched
    assert normalize_heading("3. Methodology") == {"methodology"}
    assert normalize_heading("3.1. Dataset") == {"dataset"}
    assert normalize_heading("3.1.2 Sub-Sub") == {"subsub"}
    assert heading_matched("3. Methodology", ["Methodology"]) is True
    assert heading_matched("3.1 Dataset Collection", ["Dataset Collection"]) is True


def test_normalize_heading_strips_section_number_roman():
    from benchmark.metrics import normalize_heading, heading_matched
    assert normalize_heading("III. Methodology") == {"methodology"}
    assert normalize_heading("IV. Experimental Results") == {"experimental", "results"}
    assert heading_matched("III. Methodology", ["METHODOLOGY"]) is True
    assert heading_matched("VIII. Conclusion", ["Conclusion"]) is True


def test_normalize_heading_strips_single_letter_subsection():
    from benchmark.metrics import normalize_heading, heading_matched
    assert normalize_heading("A. ResNet50") == {"resnet50"}
    assert heading_matched("A. ResNet50", ["ResNet50"]) is True


def test_normalize_heading_preserves_leading_article():
    """'A Survey of ...' must NOT be treated as section 'A' — no trailing period."""
    from benchmark.metrics import normalize_heading
    assert normalize_heading("A Survey of GANs") == {"a", "survey", "of", "gans"}
    assert normalize_heading("V Experiments") == {"v", "experiments"}  # roman without period preserved


def test_normalize_heading_chapter_section_prefix():
    from benchmark.metrics import normalize_heading, heading_matched
    assert normalize_heading("Chapter 3. Results") == {"results"}
    assert normalize_heading("Section 2 Methods") == {"methods"}
    assert heading_matched("Chapter 3. Results", ["Results"]) is True


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
      - benchmark.csv has v2 schema       → assert column set + 900 rows
                                           (150 papers × 6 conditions:
                                           mineru/grobid/docling + router_t5/8/10).
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
        assert len(rows) == 900, f"expected 900 rows (150 papers × 6 conditions), got {len(rows)}"


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
        # Content richness — raw counts + symmetric precision/recall/f1
        # (penalizes over- AND under-extraction per count_match_precision_recall_f1)
        "body_token_count",
        "figure_count_parser", "figure_count_gt",
        "figure_precision", "figure_recall", "figure_f1",
        "formula_count_parser", "formula_count_gt",
        "formula_precision", "formula_recall", "formula_f1",
        "reference_count_parser", "reference_count_gt",
        "reference_precision", "reference_recall", "reference_f1",
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
    assert len(CSV_COLUMNS) == len(expected) == 33, (
        f"expected 33 columns, got {len(CSV_COLUMNS)}"
    )


# ============================================================
# Plan 07-02.5 Task 7 — metric tests for recall-aware + hierarchy + content
# ============================================================
#
# Each new metric added in Task 3 gets at least one test covering the core
# contract plus edge cases flagged by the plan ("all matched", "no match",
# "partial", "no sec_num", "missing parents", depth-mismatch).

# ---- compute_heading_precision_recall_f1 ----

def test_heading_prf_all_matched():
    from benchmark.metrics import compute_heading_precision_recall_f1
    p, r, f1 = compute_heading_precision_recall_f1(
        parser_headings=["Introduction", "Methods", "Results"],
        gt_headings=["Introduction", "Methods", "Results"],
    )
    assert p == 1.0
    assert r == 1.0
    assert f1 == 1.0


def test_heading_prf_no_match():
    from benchmark.metrics import compute_heading_precision_recall_f1
    p, r, f1 = compute_heading_precision_recall_f1(
        parser_headings=["Conclusions", "Acknowledgements"],
        gt_headings=["Introduction", "Methods"],
    )
    assert p == 0.0
    assert r == 0.0
    assert f1 == 0.0


def test_heading_prf_partial():
    """Parser under-extracts (high precision, low recall)."""
    from benchmark.metrics import compute_heading_precision_recall_f1
    p, r, f1 = compute_heading_precision_recall_f1(
        parser_headings=["Introduction", "Methods"],
        gt_headings=["Introduction", "Methods", "Results", "Discussion"],
    )
    assert p == 1.0  # every parser heading found in GT
    assert r == 0.5  # 2 of 4 GT headings found
    # F1 = 2 * 1.0 * 0.5 / 1.5 = 0.666...
    assert f1 == pytest.approx(2 / 3, abs=1e-4)


def test_heading_prf_over_extraction_hurts_precision():
    """Parser over-extracts (low precision, full recall) — GROBID's v1 bias escaped."""
    from benchmark.metrics import compute_heading_precision_recall_f1
    p, r, f1 = compute_heading_precision_recall_f1(
        parser_headings=[
            "Introduction", "Methods", "Results",
            "Acknowledgements", "Author Contributions", "Appendix A", "Appendix B",
        ],
        gt_headings=["Introduction", "Methods", "Results"],
    )
    assert p == pytest.approx(3 / 7, abs=1e-4)  # 3 of 7 parser headings match
    assert r == 1.0                             # all 3 GT headings matched
    assert f1 == pytest.approx(2 * (3/7) / (3/7 + 1), abs=1e-4)


def test_heading_prf_accepts_gt_dict_shape():
    """GT v2 uses [{text, sec_num}, ...]; function must coerce transparently."""
    from benchmark.metrics import compute_heading_precision_recall_f1
    p, r, f1 = compute_heading_precision_recall_f1(
        parser_headings=["Introduction", "Methods"],
        gt_headings=[
            {"text": "Introduction", "sec_num": "1"},
            {"text": "Methods", "sec_num": "2"},
        ],
    )
    assert p == 1.0
    assert r == 1.0
    assert f1 == 1.0


def test_heading_prf_empty_inputs():
    from benchmark.metrics import compute_heading_precision_recall_f1
    assert compute_heading_precision_recall_f1([], []) == (0.0, 0.0, 0.0)
    assert compute_heading_precision_recall_f1(["Intro"], []) == (0.0, 0.0, 0.0)
    assert compute_heading_precision_recall_f1([], ["Intro"]) == (0.0, 0.0, 0.0)


# ---- compute_hierarchy_f1 ----

def test_hierarchy_f1_exact():
    """Parser produces the same (heading, depth) pairs as GT → F1 = 1.0."""
    from benchmark.metrics import compute_hierarchy_f1
    parser_sections = [
        {"heading": "Introduction", "sec_num": "1", "depth": 1},
        {"heading": "Methods",      "sec_num": "2", "depth": 1},
        {"heading": "Model",        "sec_num": "2.1", "depth": 2},
        {"heading": "Training",     "sec_num": "2.2", "depth": 2},
    ]
    gt_sections = [
        {"text": "Introduction", "sec_num": "1"},
        {"text": "Methods",      "sec_num": "2"},
        {"text": "Model",        "sec_num": "2.1"},
        {"text": "Training",     "sec_num": "2.2"},
    ]
    assert compute_hierarchy_f1(parser_sections, gt_sections) == 1.0


def test_hierarchy_f1_depth_mismatch():
    """Parser has right headings but wrong depths → hierarchy_f1 = 0.0."""
    from benchmark.metrics import compute_hierarchy_f1
    parser_sections = [
        # Parser flattened the hierarchy — all at depth 1.
        {"heading": "Introduction", "sec_num": "1",   "depth": 1},
        {"heading": "Model",        "sec_num": "2",   "depth": 1},  # should be 2
        {"heading": "Training",     "sec_num": "3",   "depth": 1},  # should be 2
    ]
    gt_sections = [
        {"text": "Introduction", "sec_num": "1"},
        {"text": "Model",        "sec_num": "2.1"},
        {"text": "Training",     "sec_num": "2.2"},
    ]
    f1 = compute_hierarchy_f1(parser_sections, gt_sections)
    # "Introduction" matches (depth 1 vs depth 1); "Model" + "Training" mismatched.
    # tp = 1, |parser|=3, |gt|=3 → p = r = 1/3 → f1 = 1/3
    assert f1 == pytest.approx(1 / 3, abs=1e-4)


def test_hierarchy_f1_missing_parents():
    """GT has nested structure but parser emits only top-level headings."""
    from benchmark.metrics import compute_hierarchy_f1
    parser_sections = [
        {"heading": "Methods", "sec_num": "1", "depth": 1},
    ]
    gt_sections = [
        {"text": "Methods", "sec_num": "1"},
        {"text": "Model",   "sec_num": "1.1"},
        {"text": "Data",    "sec_num": "1.2"},
    ]
    f1 = compute_hierarchy_f1(parser_sections, gt_sections)
    # tp=1, p=1/1=1.0, r=1/3, f1=2*1.0*(1/3)/(1+1/3)=0.5
    assert f1 == pytest.approx(0.5, abs=1e-4)


def test_hierarchy_f1_standalone_parser_scores_zero():
    """Non-router conditions have sections WITHOUT depth → hierarchy_f1 = 0.0.

    This is the explicit design intent of plan 07-02.5: only the router earns
    hierarchy credit (because only the router applies _apply_dot_count_hierarchy).
    """
    from benchmark.metrics import compute_hierarchy_f1
    parser_sections = [
        {"heading": "Introduction"},  # no depth, no sec_num — standalone parser
        {"heading": "Methods"},
    ]
    gt_sections = [
        {"text": "Introduction", "sec_num": "1"},
        {"text": "Methods",      "sec_num": "2"},
    ]
    assert compute_hierarchy_f1(parser_sections, gt_sections) == 0.0


def test_hierarchy_f1_empty_inputs():
    from benchmark.metrics import compute_hierarchy_f1
    assert compute_hierarchy_f1([], []) == 0.0
    assert compute_hierarchy_f1([{"heading": "A", "depth": 1}], []) == 0.0
    assert compute_hierarchy_f1([], [{"text": "A", "sec_num": "1"}]) == 0.0


def test_hierarchy_f1_infers_depth_from_sec_num():
    """GT sections don't carry explicit depth; function infers from sec_num dots."""
    from benchmark.metrics import compute_hierarchy_f1
    parser_sections = [
        {"heading": "A", "sec_num": "1",   "depth": 1},
        {"heading": "B", "sec_num": "1.1", "depth": 2},
    ]
    gt_sections = [
        {"text": "A", "sec_num": "1"},
        {"text": "B", "sec_num": "1.1"},
    ]
    assert compute_hierarchy_f1(parser_sections, gt_sections) == 1.0


# ---- _apply_dot_count_hierarchy (router builder from Task 2) ----

def test_dot_count_hierarchy_single_level():
    """Only top-level headings → every section has depth=1, parent_sec_num=None."""
    from benchmark.run_benchmark import _apply_dot_count_hierarchy
    out = _apply_dot_count_hierarchy([
        {"heading": "Introduction", "sec_num": "1", "text": "a"},
        {"heading": "Methods",      "sec_num": "2", "text": "b"},
        {"heading": "Results",      "sec_num": "3", "text": "c"},
    ])
    assert all(s["depth"] == 1 for s in out)
    assert all(s["parent_sec_num"] is None for s in out)
    # Payload preserved.
    assert [s["text"] for s in out] == ["a", "b", "c"]


def test_dot_count_hierarchy_nested():
    """Multi-level hierarchy → depth + parent_sec_num computed correctly."""
    from benchmark.run_benchmark import _apply_dot_count_hierarchy
    out = _apply_dot_count_hierarchy([
        {"heading": "Introduction", "sec_num": "1",     "text": ""},
        {"heading": "Methods",      "sec_num": "2",     "text": ""},
        {"heading": "Model",        "sec_num": "2.1",   "text": ""},
        {"heading": "Training",     "sec_num": "2.2",   "text": ""},
        {"heading": "Hyper",        "sec_num": "2.2.1", "text": ""},
        {"heading": "Results",      "sec_num": "3",     "text": ""},
    ])
    depths = [s["depth"] for s in out]
    parents = [s["parent_sec_num"] for s in out]
    assert depths == [1, 1, 2, 2, 3, 1]
    assert parents == [None, None, "2", "2", "2.2", None]


def test_dot_count_hierarchy_no_secnum():
    """Sections without sec_num pass through with depth=None, parent=None."""
    from benchmark.run_benchmark import _apply_dot_count_hierarchy
    out = _apply_dot_count_hierarchy([
        {"heading": "A", "sec_num": None, "text": ""},
        {"heading": "B", "sec_num": "",   "text": ""},
        {"heading": "C", "text": ""},  # missing key entirely
    ])
    for s in out:
        assert s["depth"] is None
        assert s["parent_sec_num"] is None


def test_dot_count_hierarchy_parent_only_when_strict_nesting():
    """'2.1' nests under '2' but NOT under an earlier '1'."""
    from benchmark.run_benchmark import _apply_dot_count_hierarchy
    out = _apply_dot_count_hierarchy([
        {"heading": "First",  "sec_num": "1",   "text": ""},
        {"heading": "Second", "sec_num": "2",   "text": ""},
        {"heading": "Sub",    "sec_num": "2.1", "text": ""},
    ])
    assert out[2]["parent_sec_num"] == "2"
    # Make sure "1" was never erroneously picked.
    assert out[2]["parent_sec_num"] != "1"


# ---- body_token_count (Task 3) ----

def test_body_token_count():
    """Sum of tiktoken cl100k_base tokens across non-empty section.text fields."""
    from benchmark.metrics import body_token_count
    sections = [
        {"text": "Hello world."},
        {"text": "  "},                 # whitespace-only, skipped
        {"text": ""},                   # empty, skipped
        {"text": "Another short sentence for counting."},
        {"not_text_field": "ignored"},  # no text key, skipped
    ]
    # Exact token counts depend on the encoder, so assert a reasonable range
    # plus the monotonicity (more text → at least as many tokens).
    n = body_token_count(sections)
    assert n > 0
    # "Hello world." alone
    n_short = body_token_count([{"text": "Hello world."}])
    assert n >= n_short
    # Empty input → 0
    assert body_token_count([]) == 0
    assert body_token_count([{"text": ""}]) == 0


def test_body_token_count_deterministic_for_fixed_string():
    """tiktoken cl100k_base is deterministic — lock a specific count."""
    from benchmark.metrics import body_token_count
    # "Hello world." encodes to exactly 3 tokens under cl100k_base.
    assert body_token_count([{"text": "Hello world."}]) == 3


# ---- count_figures / count_formulas / count_references (Task 3) ----

def test_struct_count_passthroughs():
    from benchmark.metrics import count_figures, count_formulas, count_references
    sc = {"figure_count": 4, "formula_count": 11, "reference_count": 27, "table_count": 2}
    assert count_figures(sc) == 4
    assert count_formulas(sc) == 11
    assert count_references(sc) == 27


def test_struct_count_missing_keys_default_to_zero():
    from benchmark.metrics import count_figures, count_formulas, count_references
    assert count_figures({}) == 0
    assert count_formulas({}) == 0
    assert count_references({}) == 0


def test_struct_count_handles_non_int_gracefully():
    from benchmark.metrics import count_figures, count_formulas, count_references
    assert count_figures({"figure_count": "7"}) == 7   # coerced
    assert count_formulas({"formula_count": None}) == 0
    assert count_references({"reference_count": "not a number"}) == 0


# ---- count_match_precision_recall_f1 (symmetric count agreement) ----

def test_count_match_perfect_agreement():
    from benchmark.metrics import count_match_precision_recall_f1
    assert count_match_precision_recall_f1(10, 10) == (1.0, 1.0, 1.0)


def test_count_match_over_extraction_penalized():
    # GROBID's paper-2 case: parser=21, gt=17 → precision 17/21, recall 1.0
    from benchmark.metrics import count_match_precision_recall_f1
    p, r, f1 = count_match_precision_recall_f1(21, 17)
    assert abs(p - 17 / 21) < 1e-9
    assert r == 1.0
    assert f1 < 1.0  # over-extraction dings f1


def test_count_match_under_extraction_penalized():
    p, r, f1 = __import__("benchmark.metrics", fromlist=["count_match_precision_recall_f1"]).count_match_precision_recall_f1(10, 20)
    assert p == 1.0
    assert r == 0.5
    assert 0.0 < f1 < 1.0


def test_count_match_both_zero_is_vacuous_perfect():
    from benchmark.metrics import count_match_precision_recall_f1
    assert count_match_precision_recall_f1(0, 0) == (1.0, 1.0, 1.0)


def test_count_match_one_zero_is_total_mismatch():
    from benchmark.metrics import count_match_precision_recall_f1
    assert count_match_precision_recall_f1(0, 5) == (0.0, 0.0, 0.0)
    assert count_match_precision_recall_f1(5, 0) == (0.0, 0.0, 0.0)


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
