"""Phase 3 tests — controlled Bloom/difficulty generation & valid JSON.

These run fully offline using :class:`~quizgen.mock_client.MockLLMClient`,
so they assert the *control* guarantees (schema validity, requested
bloom_level/difficulty respected, planned distributions) without a live LLM.
"""

from __future__ import annotations

from collections import Counter

from quizgen.bloom import (
    BLOOM_DESCRIPTIONS,
    BLOOM_FEWSHOT,
    QuestionSpec,
    build_balanced_plan,
    build_difficulty_plan,
)
from quizgen.generate import generate_controlled_for_chapter
from quizgen.ingest import Chapter, Chunk, Section
from quizgen.mock_client import MockLLMClient
from quizgen.schema import BloomLevel, Difficulty, Question, QuestionType, question_batch_schema


# ── Fixtures ────────────────────────────────────────────────────────


def _toy_chapter(num: int = 3) -> Chapter:
    """A minimal chapter with one section and two chunks of real-ish text."""
    text = (
        "Logic programming uses Horn clauses. Unification matches terms. "
        "Backtracking explores alternative resolutions when a branch fails. "
        "The closed-world assumption treats unprovable facts as false."
    )
    chunks = [
        Chunk(
            chunk_id=f"ch{num}_s{num}.1_chunk_{i:03d}",
            chapter_num=num,
            section_label=f"{num}.1",
            text=text,
            token_count=40,
            page_start=1,
            page_end=2,
        )
        for i in (1, 2)
    ]
    sec = Section(label=f"{num}.1", title="Logic Programming", page_start=1, page_end=2)
    sec.chunks = chunks
    return Chapter(number=num, title="Logic Programming", page_start=1, page_end=2,
                   sections=[sec], chunks=chunks)


# ── Planning helpers ────────────────────────────────────────────────


class TestDifficultyPlan:
    def test_default_mix_sums_to_total(self):
        plan = build_difficulty_plan(10)
        assert sum(plan.values()) == 10

    def test_default_mix_is_40_40_20(self):
        plan = build_difficulty_plan(10)
        assert plan[Difficulty.EASY] == 4
        assert plan[Difficulty.MEDIUM] == 4
        assert plan[Difficulty.HARD] == 2

    def test_custom_mix_normalised(self):
        plan = build_difficulty_plan(12, {"easy": 1, "hard": 1})  # 50/50, no medium
        assert sum(plan.values()) == 12
        assert plan.get(Difficulty.MEDIUM, 0) == 0

    def test_indivisible_total_still_exact(self):
        plan = build_difficulty_plan(7)  # 0.4/0.4/0.2 of 7
        assert sum(plan.values()) == 7


class TestBalancedPlan:
    def test_total_and_levels(self):
        specs = build_balanced_plan(12)
        assert len(specs) == 12
        assert {s.bloom_level for s in specs} == set(BloomLevel)

    def test_even_bloom_split(self):
        specs = build_balanced_plan(12)
        counts = Counter(s.bloom_level for s in specs)
        assert all(c == 2 for c in counts.values())

    def test_difficulty_mix_respected_overall(self):
        specs = build_balanced_plan(10)
        counts = Counter(s.difficulty for s in specs)
        assert counts[Difficulty.EASY] == 4
        assert counts[Difficulty.MEDIUM] == 4
        assert counts[Difficulty.HARD] == 2

    def test_subset_of_levels(self):
        specs = build_balanced_plan(4, bloom_levels=[BloomLevel.REMEMBER, BloomLevel.APPLY])
        assert {s.bloom_level for s in specs} == {BloomLevel.REMEMBER, BloomLevel.APPLY}


# ── Few-shot / descriptions present for every level ─────────────────


def test_every_bloom_level_has_description_and_fewshot():
    for level in BloomLevel:
        assert level in BLOOM_DESCRIPTIONS and BLOOM_DESCRIPTIONS[level]
        assert BLOOM_FEWSHOT.get(level), f"missing few-shot for {level}"


# ── Generation control guarantees ───────────────────────────────────


class TestControlledGeneration:
    def test_all_items_parse_against_schema(self):
        chapter = _toy_chapter()
        specs = build_balanced_plan(12)
        questions = generate_controlled_for_chapter(chapter, specs, MockLLMClient())
        assert len(questions) == 12
        # Round-trip every item through the schema to prove validity.
        for q in questions:
            assert isinstance(q, Question)
            Question.model_validate_json(q.model_dump_json())

    def test_requested_bloom_and_difficulty_respected(self):
        chapter = _toy_chapter()
        specs = [
            QuestionSpec(BloomLevel.ANALYZE, Difficulty.HARD, QuestionType.SHORT_ANSWER),
            QuestionSpec(BloomLevel.REMEMBER, Difficulty.EASY, QuestionType.MCQ),
            QuestionSpec(BloomLevel.CREATE, Difficulty.HARD),
        ]
        questions = generate_controlled_for_chapter(chapter, specs, MockLLMClient())

        # Group results match the requested (bloom, difficulty) multiset.
        got = Counter((q.bloom_level, q.difficulty) for q in questions)
        want = Counter((s.bloom_level, s.difficulty) for s in specs)
        assert got == want

    def test_distribution_matches_plan(self):
        chapter = _toy_chapter()
        specs = build_balanced_plan(12)
        questions = generate_controlled_for_chapter(chapter, specs, MockLLMClient())
        bloom_counts = Counter(q.bloom_level.value for q in questions)
        assert all(c == 2 for c in bloom_counts.values())
        diff_counts = Counter(q.difficulty.value for q in questions)
        assert diff_counts["easy"] == 5
        assert diff_counts["medium"] == 5
        assert diff_counts["hard"] == 2

    def test_source_ref_populated(self):
        chapter = _toy_chapter()
        specs = build_balanced_plan(6)
        questions = generate_controlled_for_chapter(chapter, specs, MockLLMClient())
        assert all(q.source_ref for q in questions)


# ── Structured-output schema ────────────────────────────────────────


def test_batch_schema_shape():
    schema = question_batch_schema()
    assert schema["type"] == "object"
    assert "questions" in schema["properties"]
    assert schema["properties"]["questions"]["type"] == "array"
