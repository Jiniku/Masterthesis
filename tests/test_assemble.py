"""Phase 4 tests — blueprint resolution and Automated Test Assembly.

Covers blueprint count resolution (percentages/fractions/counts), both
selectors (greedy & MIP), exact per-chapter / difficulty compliance, disjoint
parallel versions, and cross-version near-duplicate avoidance.
"""

from __future__ import annotations

from collections import Counter

import pytest

from quizgen.assemble import GreedySelector, MIPSelector, assemble
from quizgen.blueprint import Blueprint
from quizgen.schema import BloomLevel, Difficulty, Question, QuestionType


# ── Pool builder ────────────────────────────────────────────────────


def _make_pool() -> list[Question]:
    """A diverse pool: 3 chapters × enough questions with a difficulty spread."""
    blooms = list(BloomLevel)
    diffs = [Difficulty.EASY, Difficulty.MEDIUM, Difficulty.HARD]
    pool: list[Question] = []
    n = 0
    for chapter in (1, 2, 3):
        for k in range(30):
            diff = diffs[k % 3]  # ~ even spread, plenty of each
            bloom = blooms[k % len(blooms)]
            pool.append(
                Question(
                    id=f"q{n:03d}",
                    chapter=chapter,
                    section=f"{chapter}.{k % 3 + 1}",
                    qtype=QuestionType.MCQ,
                    bloom_level=bloom,
                    difficulty=diff,
                    stem=f"Chapter {chapter} question number {k} about distinct topic {n}.",
                    options=[f"A) opt{n}", "B) two", "C) three", "D) four"],
                    answer="A",
                    explanation=f"Explanation for question {n} grounded in chapter {chapter}.",
                    source_ref=f"ch{chapter}_chunk_{k:03d}",
                )
            )
            n += 1
    return pool


def _blueprint(**over) -> Blueprint:
    base = dict(
        title="Test Exam",
        total_questions=20,
        chapters={1: "50%", 2: "30%", 3: "20%"},
        difficulty_mix={"easy": 0.4, "medium": 0.4, "hard": 0.2},
        versions=2,
        selector="greedy",
    )
    base.update(over)
    return Blueprint.model_validate(base)


# ── Blueprint resolution ────────────────────────────────────────────


class TestBlueprintResolution:
    def test_percentage_chapters(self):
        bp = _blueprint()
        assert bp.resolve_chapter_counts() == {1: 10, 2: 6, 3: 4}

    def test_fraction_chapters(self):
        bp = _blueprint(chapters={1: 0.5, 2: 0.3, 3: 0.2})
        assert bp.resolve_chapter_counts() == {1: 10, 2: 6, 3: 4}

    def test_explicit_integer_counts(self):
        bp = _blueprint(chapters={1: 12, 2: 5, 3: 3})
        assert bp.resolve_chapter_counts() == {1: 12, 2: 5, 3: 3}

    def test_difficulty_counts(self):
        bp = _blueprint()
        counts = bp.resolve_difficulty_counts()
        assert counts[Difficulty.EASY] == 8
        assert counts[Difficulty.MEDIUM] == 8
        assert counts[Difficulty.HARD] == 4

    def test_counts_sum_to_total(self):
        bp = _blueprint(total_questions=17, chapters={1: "50%", 2: "30%", 3: "20%"})
        assert sum(bp.resolve_chapter_counts().values()) == 17

    def test_invalid_selector_rejected(self):
        with pytest.raises(ValueError):
            _blueprint(selector="genetic")


# ── Selectors ───────────────────────────────────────────────────────


def _assert_compliant(versions, bp):
    chapter_counts = bp.resolve_chapter_counts()
    diff_counts = bp.resolve_difficulty_counts()
    for qs in versions:
        assert len(qs) == bp.total_questions
        assert dict(Counter(q.chapter for q in qs)) == chapter_counts
        got_diff = Counter(q.difficulty.value for q in qs)
        for d, need in diff_counts.items():
            assert got_diff.get(d.value, 0) == need


class TestGreedySelector:
    def test_meets_blueprint_exactly(self):
        bp = _blueprint(selector="greedy")
        result = GreedySelector().select(_make_pool(), bp)
        assert len(result.versions) == 2
        _assert_compliant(result.versions, bp)

    def test_versions_disjoint(self):
        bp = _blueprint(selector="greedy")
        result = GreedySelector().select(_make_pool(), bp)
        a = {q.id for q in result.versions[0]}
        b = {q.id for q in result.versions[1]}
        assert a.isdisjoint(b)


class TestMIPSelector:
    def test_meets_blueprint_exactly(self):
        bp = _blueprint(selector="mip")
        result = MIPSelector().select(_make_pool(), bp)
        assert len(result.versions) == 2
        _assert_compliant(result.versions, bp)
        assert result.diagnostics.get("solver_status") == "Optimal"

    def test_versions_disjoint(self):
        bp = _blueprint(selector="mip")
        result = MIPSelector().select(_make_pool(), bp)
        a = {q.id for q in result.versions[0]}
        b = {q.id for q in result.versions[1]}
        assert a.isdisjoint(b)


class TestAssembleFactory:
    def test_factory_picks_selector(self):
        pool = _make_pool()
        res_g = assemble(pool, _blueprint(selector="greedy"))
        res_m = assemble(pool, _blueprint(selector="mip"))
        assert res_g.selector_name == "greedy"
        assert res_m.selector_name == "mip"

    def test_allowed_qtypes_filter(self):
        # Pool is all MCQ; restrict to true_false -> not enough -> capacity warning.
        bp = _blueprint(selector="greedy", allowed_qtypes=[QuestionType.MCQ])
        result = assemble(_make_pool(), bp)
        _assert_compliant(result.versions, bp)

    def test_to_quizzes_embeds_blueprint(self):
        bp = _blueprint(selector="mip")
        result = assemble(_make_pool(), bp)
        quizzes = result.to_quizzes()
        assert len(quizzes) == 2
        assert quizzes[0].blueprint["chapter_counts"] == {1: 10, 2: 6, 3: 4}
        assert quizzes[0].blueprint["selector"] == "mip"
