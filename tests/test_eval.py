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


# ---------- Placeholder surfaces filled in by 08-02 / 08-03 ----------
# (Intentionally left here to signal intent; bodies land with those plans.)
