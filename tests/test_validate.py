"""Phase 5 tests — validation report."""

from __future__ import annotations

from quizgen.blueprint import Blueprint
from quizgen.schema import BloomLevel, Difficulty, Question, QuestionType, Quiz
from quizgen.validate import report_to_markdown, validate_exam


def _q(qid, chapter, difficulty, qtype=QuestionType.MCQ, source_ref="ch1_chunk_001", answer="A"):
    return Question(
        id=qid, chapter=chapter, section=f"{chapter}.1", qtype=qtype,
        bloom_level=BloomLevel.UNDERSTAND, difficulty=difficulty,
        stem=f"A clear question number {qid} about the topic.",
        options=["A) one", "B) two", "C) three", "D) four"] if qtype == QuestionType.MCQ else None,
        answer=answer, explanation="A sufficiently long explanation for validation.",
        source_ref=source_ref,
    )


def _exam():
    qs = (
        [_q(f"a{i}", 1, Difficulty.EASY) for i in range(2)]
        + [_q(f"b{i}", 2, Difficulty.MEDIUM) for i in range(2)]
    )
    return Quiz(title="T", questions=qs)


def _blueprint():
    return Blueprint.model_validate(dict(
        total_questions=4, chapters={1: 2, 2: 2},
        difficulty_mix={"easy": 0.5, "medium": 0.5},
    ))


def test_schema_validity_all_valid():
    report = validate_exam(_exam())
    assert report.schema_valid == 4
    assert report.schema_invalid == 0


def test_blueprint_compliant():
    report = validate_exam(_exam(), _blueprint())
    assert report.blueprint_checked
    assert report.blueprint_compliant
    assert report.passed


def test_blueprint_noncompliant_detected():
    # Wrong chapter mix: all chapter 1.
    qs = [_q(f"x{i}", 1, Difficulty.EASY) for i in range(4)]
    report = validate_exam(Quiz(title="bad", questions=qs), _blueprint())
    assert not report.blueprint_compliant
    assert report.blueprint_issues
    assert not report.passed


def test_traceability_share():
    qs = [_q("a", 1, Difficulty.EASY), _q("b", 1, Difficulty.EASY, source_ref="")]
    report = validate_exam(Quiz(title="t", questions=qs))
    assert report.traceable_share == 0.5


def test_grounding_with_source_text():
    # Answer text overlaps the supplied source chunk -> grounded.
    q = _q("a", 1, Difficulty.EASY, qtype=QuestionType.SHORT_ANSWER,
           answer="resolution and unification bind variables")
    source = {"ch1_chunk_001": "Resolution and unification bind variables during inference."}
    report = validate_exam(Quiz(title="t", questions=[q]), source_chunks=source)
    assert report.grounded_share == 1.0


def test_duplicate_rate():
    q1 = _q("a", 1, Difficulty.EASY, qtype=QuestionType.SHORT_ANSWER)
    q2 = _q("a", 1, Difficulty.EASY, qtype=QuestionType.SHORT_ANSWER)  # identical text
    q2.id = "b"
    report = validate_exam(Quiz(title="t", questions=[q1, q2]), duplicate_threshold=0.9)
    assert report.n_duplicate_pairs == 1
    assert report.duplicate_rate == 1.0


def test_markdown_renders():
    md = report_to_markdown(validate_exam(_exam(), _blueprint()))
    assert "# Exam Validation Report" in md
    assert "Schema validity" in md
    assert "Blueprint compliance" in md
    assert "Grounding coverage" in md
    assert "Duplicate rate" in md
