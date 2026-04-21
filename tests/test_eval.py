# pyright: reportMissingImports=false
"""Unit tests for Phase 8 eval scripts (build_questions, run_eval, score, analyze).

Wave 0 scope (plan 08-01): build_questions promote/reject/schema coverage only.
Plans 08-02 and 08-03 extend this file with runner, scorer, and analyzer tests.

All tests are mocked — no live OpenAI or Reader calls per D-23/D-24.
"""
import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

FIXTURE_DIR = Path(__file__).parent / "fixtures"
MOCK_QUESTIONS_PATH = FIXTURE_DIR / "mock_questions.json"


# ---------- Fixtures ----------

@pytest.fixture
def mock_questions_doc():
    """Load the 3-item mock question set used by every Wave 0 test."""
    with open(MOCK_QUESTIONS_PATH) as f:
        return json.load(f)


@pytest.fixture
def mock_reader_in_corpus():
    """A Reader MagicMock whose head/sections return non-empty content for any id.

    Tests that want to simulate specific corpus membership override
    `reader.references.return_value` per-test.
    """
    reader = MagicMock()
    reader.head.return_value = {"sections": [{"heading": "Introduction", "text": "..."}]}
    reader.sections.return_value = {"sections": [{"heading": "Introduction", "text": "..."}]}
    reader.references.return_value = {"references": [
        {"arxiv_id": "1706.03762", "in_corpus": True, "context_text": "..."},
        {"arxiv_id": "1810.04805", "in_corpus": True, "context_text": "..."},
        {"arxiv_id": "2005.14165", "in_corpus": True, "context_text": "..."},
    ]}
    return reader


# ---------- build_questions tests (EVAL-01) ----------

def test_questions_schema_valid_on_load(mock_questions_doc):
    """Every entry must have the D-04 keys; schema-version present per D-26."""
    assert mock_questions_doc.get("questions_schema_version") == 1
    required = {
        "question_id",
        "question_type",
        "seed_arxiv_id",
        "gold_cited_arxiv_ids",
        "gold_answer_keywords",
        "question_text",
        "human_notes",
    }
    for q in mock_questions_doc["questions"]:
        missing = required - set(q.keys())
        assert not missing, f"missing keys for {q.get('question_id')}: {missing}"
        assert q["question_type"] in (
            "method-dependency",
            "comparative",
            "claim-grounding",
        )
        assert len(q["gold_cited_arxiv_ids"]) >= 2


def test_promote_moves_candidate(tmp_path, mock_reader_in_corpus):
    """--promote Q001 must move a candidate from candidates.json into questions.json per D-05."""
    from eval.build_questions import promote_candidate, load_questions

    candidates = tmp_path / "candidates.json"
    questions = tmp_path / "questions.json"
    candidate = {
        "question_id": "Q001",
        "question_type": "method-dependency",
        "seed_arxiv_id": "2401.00001",
        "gold_cited_arxiv_ids": ["1706.03762"],
        "gold_answer_keywords": ["attention"],
        "question_text": "How does paper X adapt attention?",
        "human_notes": "test fixture",
    }
    candidates.write_text(json.dumps({"questions_schema_version": 1, "questions": [candidate]}))
    questions.write_text(json.dumps({"questions_schema_version": 1, "questions": []}))

    promote_candidate(
        question_id="Q001",
        candidates_path=candidates,
        questions_path=questions,
        reader=mock_reader_in_corpus,
    )

    promoted = load_questions(questions)
    assert len(promoted["questions"]) == 1
    assert promoted["questions"][0]["question_id"] == "Q001"

    # Candidate must have been removed from the candidates file
    remaining = load_questions(candidates)
    assert remaining["questions"] == []


def test_reject_insufficient_in_corpus_refs(mock_reader_in_corpus):
    """Seeds with <3 in-corpus cited papers with sections must be rejected per D-07."""
    from eval.build_questions import _has_min_in_corpus_cites

    # Only 2 in-corpus cites -> rejected at the >=3 threshold
    mock_reader_in_corpus.references.return_value = {"references": [
        {"arxiv_id": "1706.03762", "in_corpus": True, "context_text": "..."},
        {"arxiv_id": "1810.04805", "in_corpus": True, "context_text": "..."},
        {"arxiv_id": "9999.99999", "in_corpus": False},
    ]}
    assert _has_min_in_corpus_cites("2401.00001", mock_reader_in_corpus, min_cites=3) is False

    # 3 in-corpus cites -> accepted
    mock_reader_in_corpus.references.return_value = {"references": [
        {"arxiv_id": "1706.03762", "in_corpus": True, "context_text": "..."},
        {"arxiv_id": "1810.04805", "in_corpus": True, "context_text": "..."},
        {"arxiv_id": "2005.14165", "in_corpus": True, "context_text": "..."},
    ]}
    assert _has_min_in_corpus_cites("2401.00001", mock_reader_in_corpus, min_cites=3) is True


# ---------- run_eval tests (EVAL-02 / D-27 / D-30 / D-31) ----------
#
# All tests below are hermetic: no live OpenAI call, no live Reader call.
# with_tools pipeline is exercised by stubbing deepxiv_sdk.agent.Agent and
# deepxiv_sdk.reader.Reader; title_only pipeline stubs openai.OpenAI and
# eval.run_eval.fetch_seed_title_abstract.

SAMPLE_QUESTION = {
    "question_id": "Q001",
    "question_type": "method-dependency",
    "seed_arxiv_id": "2401.00001",
    "gold_cited_arxiv_ids": ["1706.03762", "1810.04805"],
    "gold_answer_keywords": ["attention"],
    "question_text": "How does paper X adapt attention?",
    "human_notes": "test fixture",
}


def _usage_mock(prompt=10, completion=5, total=15):
    u = MagicMock()
    u.prompt_tokens = prompt
    u.completion_tokens = completion
    u.total_tokens = total
    return u


def test_build_row_shape_matches_schema():
    """D-31: every row carries the full D-13 descendant schema keys."""
    from eval.run_eval import build_row, JSONL_SCHEMA_VERSION, RunOutcome

    outcome = RunOutcome(
        answer_text="mocked",
        tool_calls=[{"name": "search_papers", "arguments": {"q": "a"}, "arxiv_id_hit": None}],
        usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        system_fingerprint="fp_test",
        latency_s=1.234,
        error=None,
    )
    row = build_row(SAMPLE_QUESTION, "with_tools", outcome,
                    model="gpt-4o-mini", seed=42, system_tag="tag|v1")
    expected_keys = {
        "jsonl_schema_version", "run_id", "question_id", "condition", "model",
        "seed", "timestamp", "prompt_hash", "system_fingerprint", "answer_text",
        "tool_calls", "tokens_used", "latency_s", "error",
    }
    assert expected_keys.issubset(row.keys()), row.keys()
    assert row["jsonl_schema_version"] == JSONL_SCHEMA_VERSION
    assert row["question_id"] == "Q001"
    assert row["condition"] == "with_tools"
    assert row["model"] == "gpt-4o-mini"
    assert row["seed"] == 42
    assert row["system_fingerprint"] == "fp_test"
    assert row["answer_text"] == "mocked"
    assert len(row["tool_calls"]) == 1
    assert row["tool_calls"][0]["name"] == "search_papers"
    assert row["tokens_used"]["total_tokens"] == 15
    assert row["error"] is None
    # prompt_hash is 16 hex chars per _prompt_hash
    assert isinstance(row["prompt_hash"], str) and len(row["prompt_hash"]) == 16


def test_append_row_jsonl_roundtrip(tmp_path):
    """D-31: append_row writes one JSON object per line, reread reproduces the dict."""
    from eval.run_eval import append_row

    path = tmp_path / "sub" / "rows.jsonl"
    row_a = {"question_id": "Q001", "condition": "with_tools",
             "answer_text": "unicode café ✓", "error": None}
    row_b = {"question_id": "Q001", "condition": "title_only",
             "answer_text": "baseline answer", "error": None}
    append_row(path, row_a)
    append_row(path, row_b)

    lines = [l for l in path.read_text(encoding="utf-8").splitlines() if l]
    assert len(lines) == 2
    loaded = [json.loads(l) for l in lines]
    assert loaded[0] == row_a
    assert loaded[1] == row_b


def test_run_title_only_with_mocked_openai(monkeypatch):
    """D-27: title_only makes a direct chat completion with NO tools using only
    the seed paper's title+abstract. OpenAI + Reader are both mocked."""
    from eval import run_eval as re_mod

    monkeypatch.setattr(
        re_mod,
        "fetch_seed_title_abstract",
        lambda arxiv_id, base_url=None: ("Attention is All You Need", "We propose a Transformer..."),
    )

    fake_client = MagicMock()
    fake_msg = MagicMock()
    fake_msg.content = "Answer grounded in title+abstract only."
    fake_choice = MagicMock()
    fake_choice.message = fake_msg
    fake_resp = MagicMock()
    fake_resp.choices = [fake_choice]
    fake_resp.usage = _usage_mock(prompt=150, completion=50, total=200)
    fake_resp.system_fingerprint = "fp_title_only"
    fake_client.chat.completions.create.return_value = fake_resp
    monkeypatch.setattr("openai.OpenAI", lambda **kw: fake_client)

    outcome = re_mod.run_title_only(
        SAMPLE_QUESTION,
        api_key="sk-test",
        base_url="http://stub",
        model="gpt-4o-mini",
        seed=42,
    )

    assert outcome.error is None
    assert outcome.answer_text == "Answer grounded in title+abstract only."
    assert outcome.tool_calls == []
    assert outcome.usage["total_tokens"] == 200
    assert outcome.usage["prompt_tokens"] == 150
    assert outcome.usage["completion_tokens"] == 50
    assert outcome.system_fingerprint == "fp_title_only"
    # Must have invoked chat.completions.create exactly once with seed=42 and no tools
    fake_client.chat.completions.create.assert_called_once()
    call_kwargs = fake_client.chat.completions.create.call_args.kwargs
    assert call_kwargs["seed"] == 42
    assert call_kwargs["temperature"] == 0.0
    assert "tools" not in call_kwargs, "title_only condition must not pass tools to the API"
    # The user message must contain the seed arxiv id and the fetched title/abstract
    user_msg = next(m for m in call_kwargs["messages"] if m["role"] == "user")
    assert "2401.00001" in user_msg["content"]
    assert "Attention is All You Need" in user_msg["content"]
    assert "We propose a Transformer" in user_msg["content"]


def test_run_with_tools_captures_tool_calls_via_wrapping(monkeypatch):
    """D-30: with_tools runner wraps tool_executor + client.chat.completions.create
    on the Agent *instance* to capture tool calls, token usage, fingerprint — without
    editing any SDK files."""
    from eval import run_eval as re_mod

    fake_agent = MagicMock()

    fake_tool_exec = MagicMock()
    fake_tool_exec.execute_tool_call = MagicMock(return_value="tool result body")
    fake_agent.tool_executor = fake_tool_exec

    def fake_create(**kwargs):
        resp = MagicMock()
        resp.usage = _usage_mock(prompt=100, completion=20, total=120)
        resp.system_fingerprint = "fp_with_tools"
        return resp

    fake_client = MagicMock()
    fake_client.chat.completions.create = MagicMock(side_effect=fake_create)
    fake_agent.client = fake_client

    def _fake_query(q, reset_papers=False):
        # Simulate the agent invoking a tool and then a final LLM call.
        fake_agent.tool_executor.execute_tool_call(
            "search_papers", {"query": "attention"}, state={})
        fake_agent.tool_executor.execute_tool_call(
            "load_paper", {"arxiv_id": "1706.03762"}, state={})
        fake_agent.client.chat.completions.create(
            model="gpt-4o-mini", messages=[], temperature=0.0)
        return "<answer>Citation-aware answer</answer>"

    fake_agent.query = _fake_query

    monkeypatch.setattr(
        "deepxiv_sdk.agent.Agent",
        lambda **kw: fake_agent,
    )
    monkeypatch.setattr(
        "deepxiv_sdk.reader.Reader",
        lambda **kw: MagicMock(),
    )

    outcome = re_mod.run_with_tools(
        SAMPLE_QUESTION,
        api_key="sk-test",
        base_url="http://stub",
        model="gpt-4o-mini",
        seed=42,
    )

    assert outcome.error is None, outcome.error
    assert outcome.answer_text == "<answer>Citation-aware answer</answer>"
    # Two tool calls captured, in order
    assert len(outcome.tool_calls) == 2
    assert outcome.tool_calls[0]["name"] == "search_papers"
    assert outcome.tool_calls[1]["name"] == "load_paper"
    # arxiv_id_hit pulled from the load_paper call's arguments
    assert outcome.tool_calls[1]["arxiv_id_hit"] == "1706.03762"
    assert outcome.tool_calls[0]["arxiv_id_hit"] is None
    # Token usage accumulated from the single wrapped create() call
    assert outcome.usage["total_tokens"] == 120
    assert outcome.system_fingerprint == "fp_with_tools"


def test_run_with_tools_records_error_row_when_agent_raises(monkeypatch):
    """Unexpected exception inside Agent.query is captured into outcome.error,
    answer_text is None, runner does NOT re-raise (so the full batch can proceed)."""
    from eval import run_eval as re_mod

    fake_agent = MagicMock()
    fake_agent.tool_executor = MagicMock()
    fake_agent.tool_executor.execute_tool_call = MagicMock()
    fake_agent.client = MagicMock()
    fake_agent.client.chat.completions.create = MagicMock()
    fake_agent.query = MagicMock(side_effect=RuntimeError("boom"))

    monkeypatch.setattr("deepxiv_sdk.agent.Agent", lambda **kw: fake_agent)
    monkeypatch.setattr("deepxiv_sdk.reader.Reader", lambda **kw: MagicMock())

    outcome = re_mod.run_with_tools(
        SAMPLE_QUESTION,
        api_key="sk-test",
        base_url="http://stub",
        model="gpt-4o-mini",
        seed=42,
    )

    assert outcome.answer_text is None
    assert outcome.error is not None
    assert "RuntimeError" in outcome.error and "boom" in outcome.error


def test_run_all_dry_run_does_not_call_apis(tmp_path):
    """--dry-run reports planned pair count without calling Agent or OpenAI."""
    from eval import run_eval as re_mod

    questions_path = tmp_path / "questions.json"
    questions_path.write_text(json.dumps({
        "questions_schema_version": 1,
        "questions": [dict(SAMPLE_QUESTION, question_id=f"Q00{i}") for i in range(1, 4)],
    }))

    summary = re_mod.run_all(
        questions_path=questions_path,
        results_root=tmp_path / "results",
        dry_run=True,
        limit=2,
    )
    assert summary["dry_run"] is True
    assert summary["questions"] == 2
    assert summary["planned"] == 4  # 2 questions × 2 conditions
    assert sorted(summary["conditions"]) == ["title_only", "with_tools"]


def test_run_all_end_to_end_with_both_conditions_stubbed(tmp_path, monkeypatch):
    """End-to-end run_all over 2 questions × 2 conditions with every external
    dependency stubbed. Produces the expected run directory layout and manifest
    with per-condition metrics aggregated correctly."""
    from eval import run_eval as re_mod

    # Stub with_tools path
    from eval.run_eval import RunOutcome

    def _fake_with_tools(question, **kw):
        return RunOutcome(
            answer_text=f"tools answer for {question['question_id']}",
            tool_calls=[
                {"name": "search_papers", "arguments": {"q": "x"}, "arxiv_id_hit": None},
                {"name": "load_paper", "arguments": {"arxiv_id": "1706.03762"},
                 "arxiv_id_hit": "1706.03762"},
            ],
            usage={"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120},
            system_fingerprint="fp_wt",
            latency_s=0.5,
            error=None,
        )

    def _fake_title_only(question, **kw):
        return RunOutcome(
            answer_text=f"title answer for {question['question_id']}",
            tool_calls=[],
            usage={"prompt_tokens": 50, "completion_tokens": 10, "total_tokens": 60},
            system_fingerprint="fp_to",
            latency_s=0.2,
            error=None,
        )

    monkeypatch.setattr(re_mod, "run_with_tools", _fake_with_tools)
    monkeypatch.setattr(re_mod, "run_title_only", _fake_title_only)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    questions_path = tmp_path / "questions.json"
    questions_path.write_text(json.dumps({
        "questions_schema_version": 1,
        "questions": [dict(SAMPLE_QUESTION, question_id=f"Q00{i}") for i in range(1, 3)],
    }))

    run_dir = tmp_path / "run_test"
    manifest = re_mod.run_all(
        questions_path=questions_path,
        results_root=tmp_path / "results",
        run_dir=run_dir,
        progress=False,
    )

    with_tools_path = run_dir / "with_tools" / "rows.jsonl"
    title_only_path = run_dir / "title_only" / "rows.jsonl"
    manifest_path = run_dir / "manifest.json"
    assert with_tools_path.exists()
    assert title_only_path.exists()
    assert manifest_path.exists()

    wt_rows = [json.loads(l) for l in with_tools_path.read_text().splitlines() if l]
    to_rows = [json.loads(l) for l in title_only_path.read_text().splitlines() if l]
    assert len(wt_rows) == 2
    assert len(to_rows) == 2
    assert all(r["condition"] == "with_tools" for r in wt_rows)
    assert all(r["condition"] == "title_only" for r in to_rows)
    assert all(r["error"] is None for r in wt_rows + to_rows)
    assert all(len(r["tool_calls"]) == 2 for r in wt_rows)
    assert all(r["tool_calls"] == [] for r in to_rows)

    # Manifest aggregation
    assert manifest["per_condition"]["with_tools"]["count"] == 2
    assert manifest["per_condition"]["with_tools"]["success"] == 2
    assert manifest["per_condition"]["with_tools"]["error"] == 0
    assert manifest["per_condition"]["with_tools"]["avg_tool_calls"] == 2.0
    assert manifest["per_condition"]["with_tools"]["avg_tokens_total"] == 120.0
    assert manifest["per_condition"]["title_only"]["avg_tool_calls"] == 0.0
    assert manifest["per_condition"]["title_only"]["avg_tokens_total"] == 60.0
    assert manifest["n_questions"] == 2


def test_run_all_aggregates_errors_and_non_error_rows_separately(tmp_path, monkeypatch):
    """Error rows are counted in the error bucket and do NOT contribute to the
    avg_tool_calls / avg_tokens_total averages."""
    from eval import run_eval as re_mod
    from eval.run_eval import RunOutcome

    call_state = {"count": 0}

    def _fake_with_tools(question, **kw):
        call_state["count"] += 1
        if call_state["count"] == 1:
            return RunOutcome(answer_text=None, tool_calls=[],
                              usage={"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
                              latency_s=0.1, error="RuntimeError: boom")
        return RunOutcome(answer_text="ok", tool_calls=[{"name": "x", "arguments": {}, "arxiv_id_hit": None}],
                          usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
                          latency_s=0.3, error=None)

    def _fake_title_only(question, **kw):
        return RunOutcome(answer_text="ok", tool_calls=[],
                          usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
                          latency_s=0.1, error=None)

    monkeypatch.setattr(re_mod, "run_with_tools", _fake_with_tools)
    monkeypatch.setattr(re_mod, "run_title_only", _fake_title_only)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    questions_path = tmp_path / "questions.json"
    questions_path.write_text(json.dumps({
        "questions_schema_version": 1,
        "questions": [dict(SAMPLE_QUESTION, question_id=f"Q00{i}") for i in range(1, 3)],
    }))
    run_dir = tmp_path / "run_err"
    manifest = re_mod.run_all(
        questions_path=questions_path,
        results_root=tmp_path / "results",
        run_dir=run_dir,
        progress=False,
    )

    wt = manifest["per_condition"]["with_tools"]
    assert wt["count"] == 2
    assert wt["success"] == 1
    assert wt["error"] == 1
    # Only the successful row's tool_calls & tokens feed the averages.
    assert wt["avg_tool_calls"] == 1.0
    assert wt["avg_tokens_total"] == 15.0
    # title_only has no errors
    to = manifest["per_condition"]["title_only"]
    assert to["error"] == 0 and to["success"] == 2


# ---------- score.py tests (EVAL-03) ----------

def test_score_rubric_parse_rejects_malformed_judge_json():
    """D-23: parse_judge_verdict rejects non-JSON, out-of-range ints, non-int dims,
    missing answer_b — and accepts a well-formed verdict."""
    from eval.score import parse_judge_verdict

    with pytest.raises(json.JSONDecodeError):
        parse_judge_verdict("not json at all")

    # non-int dimension
    with pytest.raises(ValueError):
        parse_judge_verdict(json.dumps({
            "answer_a": {"answer_correctness": "five", "faithfulness": 3,
                         "citation_coverage": 3, "completeness": 3, "notes": ""},
            "answer_b": {"answer_correctness": 3, "faithfulness": 3,
                         "citation_coverage": 3, "completeness": 3, "notes": ""},
        }))

    # out-of-range dimension
    with pytest.raises(ValueError):
        parse_judge_verdict(json.dumps({
            "answer_a": {"answer_correctness": 7, "faithfulness": 3,
                         "citation_coverage": 3, "completeness": 3, "notes": ""},
            "answer_b": {"answer_correctness": 3, "faithfulness": 3,
                         "citation_coverage": 3, "completeness": 3, "notes": ""},
        }))

    # missing answer_b
    with pytest.raises(ValueError):
        parse_judge_verdict(json.dumps({
            "answer_a": {"answer_correctness": 3, "faithfulness": 3,
                         "citation_coverage": 3, "completeness": 3, "notes": ""},
        }))

    good = {
        "answer_a": {"answer_correctness": 5, "faithfulness": 4,
                     "citation_coverage": 3, "completeness": 5, "notes": "ok"},
        "answer_b": {"answer_correctness": 2, "faithfulness": 3,
                     "citation_coverage": 2, "completeness": 2, "notes": "meh"},
    }
    assert parse_judge_verdict(json.dumps(good)) == good


def test_score_deterministic_citation_coverage_arithmetic():
    """D-19: |gold ∩ arxiv_ids_in_tool_calls| / |gold|. Empty gold => 0.0.
    Empty tool_calls => 0.0. Detects via arxiv_id_hit, arguments.arxiv_id,
    arguments.paper_id, arguments.id."""
    from eval.score import deterministic_citation_coverage

    gold = ["1706.03762", "1810.04805", "2005.14165"]

    tool_calls = [
        {"name": "search_papers", "arguments": {"q": "x"}, "arxiv_id_hit": None},
        {"name": "fetch_cited_paper_sections",
         "arguments": {"arxiv_id": "1706.03762"}, "arxiv_id_hit": "1706.03762"},
        {"name": "load_paper",
         "arguments": {"paper_id": "1810.04805"}, "arxiv_id_hit": "1810.04805"},
    ]
    assert deterministic_citation_coverage(gold, tool_calls) == pytest.approx(2 / 3)

    # Edge cases
    assert deterministic_citation_coverage([], tool_calls) == 0.0
    assert deterministic_citation_coverage(gold, []) == 0.0
    assert deterministic_citation_coverage(["9999.99999"], tool_calls) == 0.0
    # All three covered via different surfaces (id key + arxiv_id_hit)
    tool_calls_all = tool_calls + [
        {"name": "head", "arguments": {"id": "2005.14165"}, "arxiv_id_hit": None},
    ]
    assert deterministic_citation_coverage(gold, tool_calls_all) == pytest.approx(1.0)


def test_score_question_with_mocked_openai_client():
    """D-24: score_question works with a MagicMock OpenAI client — no network.
    Also asserts the Anti-Pattern 7 invariant (gold_answer_keywords NOT in prompt)
    and D-11/D-16 wiring (json_schema strict, temperature=0, seed=42)."""
    from eval.score import score_question

    mock_client = MagicMock()
    mock_resp = MagicMock()
    mock_resp.choices = [MagicMock(message=MagicMock(content=json.dumps({
        "answer_a": {"answer_correctness": 5, "faithfulness": 4,
                     "citation_coverage": 4, "completeness": 5, "notes": "A is thorough"},
        "answer_b": {"answer_correctness": 3, "faithfulness": 3,
                     "citation_coverage": 2, "completeness": 3, "notes": "B is shallower"},
    })))]
    mock_resp.system_fingerprint = "fp_test"
    mock_resp.usage = MagicMock(prompt_tokens=500, completion_tokens=80, total_tokens=580)
    mock_client.chat.completions.create.return_value = mock_resp

    question = {
        "question_id": "Q001",
        "question_type": "method-dependency",
        "seed_arxiv_id": "2401.00001",
        "gold_cited_arxiv_ids": ["1706.03762", "1810.04805"],
        "gold_answer_keywords": ["attention", "self-supervised"],  # MUST NOT leak
        "question_text": "How does X use attention?",
        "human_notes": "",
    }
    run_wt = {
        "question_id": "Q001", "condition": "with_tools",
        "answer_text": "with_tools answer body",
        "tool_calls": [
            {"name": "search_papers", "arguments": {"q": "x"}, "arxiv_id_hit": None},
            {"name": "fetch_cited_paper_sections",
             "arguments": {"arxiv_id": "1706.03762"}, "arxiv_id_hit": "1706.03762"},
        ],
    }
    run_to = {
        "question_id": "Q001", "condition": "title_only",
        "answer_text": "title_only answer body", "tool_calls": [],
    }

    rows = score_question(question, run_wt, run_to, mock_client, "RUBRIC TEXT HERE")
    assert len(rows) == 2
    assert {r["condition"] for r in rows} == {"with_tools", "title_only"}

    for r in rows:
        assert r["scores_schema_version"] == 1
        for dim in ("answer_correctness", "faithfulness", "citation_coverage", "completeness"):
            assert 1 <= r[dim] <= 5
        assert r["judge_model"] == "gpt-4o-mini"
        assert r["judge_seed"] == 42
        assert r["judge_temperature"] == 0.0
        assert r["judge_system_fingerprint"] == "fp_test"
        assert 0.0 <= r["deterministic_citation_coverage"] <= 1.0

    wt_row = next(r for r in rows if r["condition"] == "with_tools")
    to_row = next(r for r in rows if r["condition"] == "title_only")
    # title_only has no tool_calls → deterministic coverage is 0 by definition
    assert to_row["deterministic_citation_coverage"] == 0.0
    # with_tools hit 1 of 2 gold ids
    assert wt_row["deterministic_citation_coverage"] == pytest.approx(0.5)

    # Audit the judge call: gold_answer_keywords must NOT be in the prompt (Anti-Pattern 7)
    _, kwargs = mock_client.chat.completions.create.call_args
    system_content = kwargs["messages"][0]["content"]
    user_content = kwargs["messages"][1]["content"]
    assert "gold_answer_keywords" not in system_content
    assert "gold_answer_keywords" not in user_content
    assert "self-supervised" not in user_content  # individual keyword must not leak

    # response_format + sampling params (D-11 / D-16)
    assert kwargs["response_format"]["type"] == "json_schema"
    assert kwargs["response_format"]["json_schema"]["strict"] is True
    assert kwargs["temperature"] == 0.0
    assert kwargs["seed"] == 42
    assert kwargs["model"] == "gpt-4o-mini"

    # presentation_order is deterministic and consistent across both rows
    assert rows[0]["presentation_order"] == rows[1]["presentation_order"]
    assert set(rows[0]["presentation_order"]) == {"with_tools", "title_only"}


def test_score_run_resume_skips_done_questions(tmp_path, monkeypatch):
    """Resumability (D-14): a question with both-condition rows already in
    scores.jsonl is skipped on re-run; the OpenAI client is not called."""
    from eval import score as score_mod

    run_dir = tmp_path / "run_x"
    (run_dir / "with_tools").mkdir(parents=True)
    (run_dir / "title_only").mkdir(parents=True)

    def _wrow(qid):
        return {"question_id": qid, "condition": "with_tools",
                "answer_text": "a", "tool_calls": [], "error": None}

    def _trow(qid):
        return {"question_id": qid, "condition": "title_only",
                "answer_text": "b", "tool_calls": [], "error": None}

    with open(run_dir / "with_tools" / "rows.jsonl", "w") as f:
        for qid in ("Q001", "Q002"):
            f.write(json.dumps(_wrow(qid)) + "\n")
    with open(run_dir / "title_only" / "rows.jsonl", "w") as f:
        for qid in ("Q001", "Q002"):
            f.write(json.dumps(_trow(qid)) + "\n")

    qpath = tmp_path / "questions.json"
    qpath.write_text(json.dumps({
        "questions_schema_version": 1,
        "questions": [
            {"question_id": "Q001", "question_type": "method-dependency",
             "seed_arxiv_id": "2401.0001", "gold_cited_arxiv_ids": ["1.1"],
             "gold_answer_keywords": ["k"], "question_text": "q1", "human_notes": ""},
            {"question_id": "Q002", "question_type": "comparative",
             "seed_arxiv_id": "2401.0002", "gold_cited_arxiv_ids": ["2.2"],
             "gold_answer_keywords": ["k"], "question_text": "q2", "human_notes": ""},
        ],
    }))

    # Seed scores.jsonl with Q001 already done (both conditions)
    with open(run_dir / "scores.jsonl", "w") as f:
        for cond in ("with_tools", "title_only"):
            f.write(json.dumps({
                "scores_schema_version": 1, "question_id": "Q001",
                "condition": cond, "answer_correctness": 3, "faithfulness": 3,
                "citation_coverage": 3, "completeness": 3,
                "deterministic_citation_coverage": 0.0, "error": None,
            }) + "\n")

    # Build a mock client factory that records calls; wire only Q002 verdict
    call_counter = {"n": 0}

    def make_client():
        client = MagicMock()
        resp = MagicMock()
        resp.choices = [MagicMock(message=MagicMock(content=json.dumps({
            "answer_a": {"answer_correctness": 4, "faithfulness": 4,
                         "citation_coverage": 4, "completeness": 4, "notes": ""},
            "answer_b": {"answer_correctness": 2, "faithfulness": 2,
                         "citation_coverage": 2, "completeness": 2, "notes": ""},
        })))]
        resp.system_fingerprint = "fp_resume"
        resp.usage = MagicMock(prompt_tokens=1, completion_tokens=1, total_tokens=2)

        def _create(**kw):
            call_counter["n"] += 1
            return resp

        client.chat.completions.create = MagicMock(side_effect=_create)
        return client

    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    summary = score_mod.score_run(
        run_dir=run_dir,
        questions_path=qpath,
        rubric_path=Path(__file__).resolve().parents[1] / "eval" / "rubric.md",
        client_factory=make_client,
    )

    assert summary["done"] == 1  # Q001 was already scored
    assert summary["pending"] == 1  # only Q002 remained
    assert summary["written"] == 2  # two rows (one per condition) for Q002
    assert call_counter["n"] == 1  # exactly one judge call (Q002)


# ---------- analyze.py tests (EVAL-04) ----------

def test_analyze_aggregation_hand_computed():
    """Hand-computed expectation: paired_deltas returns with_tools - title_only
    per question, and summarize_condition averages correctly per dimension."""
    from eval.analyze import paired_deltas, summarize_condition

    scores = [
        {"question_id": "Q1", "condition": "title_only",
         "answer_correctness": 3, "faithfulness": 3, "citation_coverage": 2,
         "completeness": 3, "deterministic_citation_coverage": 0.0, "error": None},
        {"question_id": "Q1", "condition": "with_tools",
         "answer_correctness": 5, "faithfulness": 4, "citation_coverage": 5,
         "completeness": 4, "deterministic_citation_coverage": 1.0, "error": None},
        {"question_id": "Q2", "condition": "title_only",
         "answer_correctness": 4, "faithfulness": 4, "citation_coverage": 3,
         "completeness": 4, "deterministic_citation_coverage": 0.5, "error": None},
        {"question_id": "Q2", "condition": "with_tools",
         "answer_correctness": 4, "faithfulness": 5, "citation_coverage": 4,
         "completeness": 5, "deterministic_citation_coverage": 1.0, "error": None},
    ]
    deltas_ac = dict(paired_deltas(scores, "answer_correctness"))
    assert deltas_ac["Q1"] == 2.0
    assert deltas_ac["Q2"] == 0.0

    deltas_cc = dict(paired_deltas(scores, "citation_coverage"))
    assert deltas_cc["Q1"] == 3.0 and deltas_cc["Q2"] == 1.0

    summ_to = summarize_condition(scores, "title_only")
    assert summ_to["answer_correctness"]["mean"] == pytest.approx(3.5)
    assert summ_to["faithfulness"]["n"] == 2

    summ_wt = summarize_condition(scores, "with_tools")
    assert summ_wt["citation_coverage"]["mean"] == pytest.approx(4.5)


def test_analyze_wilcoxon_wrapper_all_zero_and_uniform_improvement():
    """Wilcoxon wrapper must (a) degrade gracefully to p=1 on all-zero deltas,
    and (b) detect a real uniform improvement at n=10 (p_greater < 0.05)."""
    from eval.analyze import wilcoxon_test_four_dims

    tied_scores = []
    for i in range(5):
        tied_scores.append({"question_id": f"Q{i}", "condition": "title_only",
                            "answer_correctness": 3, "faithfulness": 3,
                            "citation_coverage": 3, "completeness": 3,
                            "deterministic_citation_coverage": 0.5, "error": None})
        tied_scores.append({"question_id": f"Q{i}", "condition": "with_tools",
                            "answer_correctness": 3, "faithfulness": 3,
                            "citation_coverage": 3, "completeness": 3,
                            "deterministic_citation_coverage": 0.5, "error": None})
    w_tied = wilcoxon_test_four_dims(tied_scores)
    for dim in ("answer_correctness", "faithfulness",
                "citation_coverage", "completeness"):
        assert w_tied[dim]["p_two_sided"] == 1.0
        assert w_tied[dim]["p_greater"] == 1.0
        assert w_tied[dim]["median_delta"] == 0.0
        assert w_tied[dim]["effect_size_r"] == 0.0

    up_scores = []
    for i in range(10):
        up_scores.append({"question_id": f"Q{i}", "condition": "title_only",
                          "answer_correctness": 3, "faithfulness": 3,
                          "citation_coverage": 3, "completeness": 3,
                          "deterministic_citation_coverage": 0.0, "error": None})
        up_scores.append({"question_id": f"Q{i}", "condition": "with_tools",
                          "answer_correctness": 4, "faithfulness": 4,
                          "citation_coverage": 4, "completeness": 4,
                          "deterministic_citation_coverage": 1.0, "error": None})
    w_up = wilcoxon_test_four_dims(up_scores)
    for dim in ("answer_correctness", "faithfulness",
                "citation_coverage", "completeness"):
        assert w_up[dim]["median_delta"] == 1.0
        assert w_up[dim]["mean_delta"] == 1.0
        assert w_up[dim]["p_greater"] < 0.05
        assert w_up[dim]["effect_size_r"] == pytest.approx(1.0)


def test_analyze_deterministic_agreement_perfect_and_reversed():
    """Spearman ρ should be +1 on rank-perfect monotone data and −1 on reversed
    data. Also checks that the direction_agreement and exact_match_bucket
    metrics compute sensibly."""
    from eval.analyze import deterministic_agreement

    perfect = [
        {"question_id": "Q1", "condition": "with_tools",
         "citation_coverage": 5, "deterministic_citation_coverage": 1.0, "error": None},
        {"question_id": "Q2", "condition": "with_tools",
         "citation_coverage": 4, "deterministic_citation_coverage": 0.7, "error": None},
        {"question_id": "Q3", "condition": "with_tools",
         "citation_coverage": 3, "deterministic_citation_coverage": 0.4, "error": None},
        {"question_id": "Q4", "condition": "with_tools",
         "citation_coverage": 2, "deterministic_citation_coverage": 0.2, "error": None},
        {"question_id": "Q5", "condition": "with_tools",
         "citation_coverage": 1, "deterministic_citation_coverage": 0.0, "error": None},
    ]
    out = deterministic_agreement(perfect)
    assert out["n"] == 5
    assert out["spearman_r"] == pytest.approx(1.0)
    # All 5 rows pass the judge≥4 ↔ det≥0.5 direction test (row1/2 yes/yes,
    # row3 no/no, row4 no/no, row5 no/no)
    assert out["direction_agreement"] == pytest.approx(1.0)

    reversed_scores = [
        {"question_id": f"Q{i}", "condition": "with_tools",
         "citation_coverage": 6 - (i + 1), "deterministic_citation_coverage": (i + 1) / 5,
         "error": None}
        for i in range(5)
    ]
    out_rev = deterministic_agreement(reversed_scores)
    assert out_rev["spearman_r"] == pytest.approx(-1.0)


def test_analyze_render_findings_has_all_required_sections(tmp_path):
    """render_findings must produce ≥80 lines and contain the 8 mandated section
    headers (Executive Summary, Question-Set Overview, ..., Reproducibility Notes)
    plus 'Wilcoxon' and 'deterministic'."""
    from eval.analyze import render_findings

    scores = []
    for i in range(10):
        scores.append({"question_id": f"Q{i}", "condition": "title_only",
                       "answer_correctness": 3, "faithfulness": 3,
                       "citation_coverage": 2, "completeness": 3,
                       "deterministic_citation_coverage": 0.0, "error": None})
        scores.append({"question_id": f"Q{i}", "condition": "with_tools",
                       "answer_correctness": 4, "faithfulness": 4,
                       "citation_coverage": 4, "completeness": 4,
                       "deterministic_citation_coverage": 0.8, "error": None})

    runs_with = [
        {"question_id": f"Q{i}", "condition": "with_tools",
         "tool_calls": [{"name": "load_paper", "arguments": {"arxiv_id": "x"},
                         "arxiv_id_hit": "x"}],
         "tokens_used": {"total_tokens": 1000}, "latency_s": 10.0, "error": None}
        for i in range(10)
    ]
    runs_title = [
        {"question_id": f"Q{i}", "condition": "title_only", "tool_calls": [],
         "tokens_used": {"total_tokens": 200}, "latency_s": 1.0, "error": None}
        for i in range(10)
    ]
    questions = [
        {"question_id": f"Q{i}",
         "question_type": ["method-dependency", "comparative", "claim-grounding"][i % 3],
         "seed_arxiv_id": f"2401.{i:05d}",
         "gold_cited_arxiv_ids": ["x"], "gold_answer_keywords": [],
         "question_text": f"Q{i}", "human_notes": ""}
        for i in range(10)
    ]

    md = render_findings(scores, runs_with, runs_title, questions, run_dir=tmp_path)
    assert len(md.splitlines()) >= 80
    required_sections = [
        "## 1. Executive Summary",
        "## 2. Question-Set Overview",
        "## 3. Per-Condition Score Distributions",
        "## 4. Paired Deltas",
        "## 5. Statistical Tests",
        "## 6. LLM-vs-Deterministic Citation Coverage Agreement",
        "## 7. Latency & Cost",
        "## 8. Limitations",
        "## 9. Reproducibility Notes",
    ]
    for header in required_sections:
        assert header in md, f"missing header: {header}"
    assert "Wilcoxon" in md
    assert "deterministic" in md.lower()
