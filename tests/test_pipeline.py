"""Phase 5 end-to-end test — ingest → generate → dedup → assemble → validate.

Runs the whole generate-then-select pipeline on a tiny Markdown fixture using
the offline MockLLMClient, and asserts the final exam is schema-valid and
blueprint-compliant. Fully hermetic: no network, no real LLM.
"""

from __future__ import annotations

from pathlib import Path

from quizgen.blueprint import Blueprint
from quizgen.mock_client import MockLLMClient
from quizgen.pipeline import run_pipeline
from quizgen.schema import Question

FIXTURE = Path(__file__).parent / "fixtures" / "tiny_textbook.md"


def _blueprint(selector: str) -> Blueprint:
    return Blueprint.model_validate(dict(
        title="Tiny Exam",
        total_questions=6,
        chapters={1: 3, 2: 2, 3: 1},
        difficulty_mix={"easy": 0.5, "medium": 0.5},
        allowed_qtypes=["mcq", "true_false", "short_answer", "cloze"],
        versions=1,
        selector=selector,
        dedup_similarity=0.85,
    ))


def _run(selector: str):
    return run_pipeline(
        str(FIXTURE),
        chapters_to_process=[1, 2, 3],
        blueprint=_blueprint(selector),
        client=MockLLMClient(),
        per_chapter_pool=12,
        use_rag=False,          # hermetic: skip embeddings
        config_path=None,
        dedup_threshold=0.92,
    )


def test_pipeline_produces_one_compliant_exam_mip():
    result = _run("mip")
    assert len(result.exams) == 1
    quiz = result.exams[0]

    # Schema-valid: every question round-trips.
    assert len(quiz.questions) == 6
    for q in quiz.questions:
        Question.model_validate(q.model_dump())

    # Blueprint-compliant per the validation report.
    report = result.reports[0]
    assert report.passed
    assert report.blueprint_compliant
    assert report.chapter_counts == {1: 3, 2: 2, 3: 1}
    assert report.schema_invalid == 0


def test_pipeline_greedy_also_compliant():
    result = _run("greedy")
    report = result.reports[0]
    assert report.passed
    assert report.chapter_counts == {1: 3, 2: 2, 3: 1}


def test_pipeline_dedup_runs():
    result = _run("greedy")
    # Dedup result is populated and consistent.
    assert result.dedup.n_kept + result.dedup.n_removed >= 6
    assert result.dedup.method in ("token", "embedding")


def test_pipeline_embeds_blueprint_in_exam():
    result = _run("mip")
    blueprint = result.exams[0].blueprint
    assert blueprint["chapter_counts"] == {1: 3, 2: 2, 3: 1}
    assert blueprint["selector"] == "mip"
    # Every question retains its provenance tag.
    for q in result.exams[0].questions:
        assert q.source_ref
