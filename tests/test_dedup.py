"""Phase 5 tests — pool deduplication."""

from __future__ import annotations

from quizgen.dedup import deduplicate
from quizgen.schema import BloomLevel, Difficulty, Question, QuestionType


def _q(qid: str, stem: str, answer: str = "an answer here") -> Question:
    return Question(
        id=qid,
        chapter=1,
        section="1.1",
        qtype=QuestionType.SHORT_ANSWER,
        bloom_level=BloomLevel.UNDERSTAND,
        difficulty=Difficulty.EASY,
        stem=stem,
        answer=answer,
        explanation="An explanation long enough to pass validation.",
        source_ref="ch1_chunk_001",
    )


def test_drops_exact_duplicates():
    pool = [
        _q("a", "What is breadth first search in graph traversal?"),
        _q("b", "What is breadth first search in graph traversal?"),  # dup of a
        _q("c", "Explain depth first search and its memory usage clearly."),
    ]
    result = deduplicate(pool, threshold=0.9, use_embeddings=False)
    assert result.n_kept == 2
    assert result.n_removed == 1
    assert "b" in {q.id for q in result.removed}
    assert result.method == "token"


def test_keeps_distinct_questions():
    pool = [
        _q("a", "Describe the A star search algorithm and admissibility."),
        _q("b", "What is the closed world assumption in logic programming?"),
        _q("c", "How does unification bind variables during resolution steps?"),
    ]
    result = deduplicate(pool, threshold=0.9, use_embeddings=False)
    assert result.n_kept == 3
    assert result.n_removed == 0


def test_reports_pairs():
    pool = [
        _q("a", "What is breadth first search in graph traversal?"),
        _q("b", "What is breadth first search in graph traversal?"),
    ]
    result = deduplicate(pool, threshold=0.9, use_embeddings=False)
    assert result.duplicate_pairs == [("a", "b")]


def test_keeps_first_occurrence():
    pool = [
        _q("first", "Identical stem about resolution and unification here."),
        _q("second", "Identical stem about resolution and unification here."),
        _q("third", "Identical stem about resolution and unification here."),
    ]
    result = deduplicate(pool, threshold=0.9, use_embeddings=False)
    assert result.n_kept == 1
    assert result.kept[0].id == "first"
