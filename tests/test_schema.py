"""Schema round-trip tests — Phase 0 gate.

These tests verify that:
1.  A ``Question`` can be created, serialised to JSON, and deserialised back
    without data loss.
2.  A ``Quiz`` containing questions round-trips correctly.
3.  Invalid data is rejected by Pydantic validation.
4.  The JSON Schema export produces valid files.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest
from pydantic import ValidationError

from quizgen.schema import (
    BloomLevel,
    Difficulty,
    Question,
    QuestionType,
    Quiz,
    export_json_schemas,
)


# ── Fixtures ────────────────────────────────────────────────────────


def _sample_question(**overrides) -> Question:
    """Return a valid ``Question`` with sensible defaults, overridable."""
    defaults = dict(
        id="test_q_001",
        chapter=2,
        section="2.1",
        qtype=QuestionType.MCQ,
        bloom_level=BloomLevel.UNDERSTAND,
        difficulty=Difficulty.MEDIUM,
        stem="Which data structure provides O(1) average-case lookup?",
        options=["Linked list", "Hash table", "Binary tree", "Stack"],
        answer="B",
        explanation=(
            "Hash tables use a hash function to map keys to buckets, "
            "giving O(1) average-case lookup time."
        ),
        source_ref="ch2_s1_chunk_003",
    )
    defaults.update(overrides)
    return Question(**defaults)


# ── Question tests ──────────────────────────────────────────────────


class TestQuestion:
    """Tests for the ``Question`` model."""

    def test_round_trip_json(self):
        """Serialise → deserialise → compare."""
        original = _sample_question()
        json_str = original.model_dump_json()
        restored = Question.model_validate_json(json_str)
        assert restored == original

    def test_round_trip_dict(self):
        """Serialise to dict → back → compare."""
        original = _sample_question()
        data = original.model_dump()
        restored = Question.model_validate(data)
        assert restored == original

    def test_all_bloom_levels(self):
        """Every Bloom level is accepted."""
        for level in BloomLevel:
            q = _sample_question(bloom_level=level)
            assert q.bloom_level == level

    def test_all_difficulties(self):
        """Every difficulty tier is accepted."""
        for diff in Difficulty:
            q = _sample_question(difficulty=diff)
            assert q.difficulty == diff

    def test_all_question_types(self):
        """Every qtype is accepted."""
        for qtype in QuestionType:
            q = _sample_question(qtype=qtype)
            assert q.qtype == qtype

    def test_optional_section_none(self):
        """Section may be None."""
        q = _sample_question(section=None)
        assert q.section is None

    def test_optional_options_none(self):
        """Options may be None (e.g. for short_answer)."""
        q = _sample_question(options=None)
        assert q.options is None

    def test_auto_generated_id(self):
        """When id is omitted, a hex id is generated."""
        q = _sample_question()
        data = q.model_dump()
        del data["id"]
        restored = Question.model_validate(data)
        assert isinstance(restored.id, str) and len(restored.id) == 12

    def test_invalid_bloom_rejected(self):
        """An invalid Bloom level raises ValidationError."""
        with pytest.raises(ValidationError):
            _sample_question(bloom_level="memorize")  # not a valid level

    def test_invalid_difficulty_rejected(self):
        """An invalid difficulty raises ValidationError."""
        with pytest.raises(ValidationError):
            _sample_question(difficulty="nightmare")

    def test_invalid_qtype_rejected(self):
        """An invalid qtype raises ValidationError."""
        with pytest.raises(ValidationError):
            _sample_question(qtype="essay")

    def test_empty_stem_rejected(self):
        """Stem must have at least 10 characters."""
        with pytest.raises(ValidationError):
            _sample_question(stem="Short?")

    def test_empty_answer_rejected(self):
        """Answer must be non-empty."""
        with pytest.raises(ValidationError):
            _sample_question(answer="")

    def test_chapter_must_be_positive(self):
        """Chapter must be >= 1."""
        with pytest.raises(ValidationError):
            _sample_question(chapter=0)


# ── Quiz tests ──────────────────────────────────────────────────────


class TestQuiz:
    """Tests for the ``Quiz`` model."""

    def test_round_trip_json(self):
        """Full Quiz with questions round-trips through JSON."""
        q1 = _sample_question(id="q1")
        q2 = _sample_question(id="q2", chapter=3, difficulty=Difficulty.HARD)
        quiz = Quiz(
            quiz_id="exam_v1",
            title="Test Exam",
            blueprint={"total_questions": 2, "chapters": {2: 1, 3: 1}},
            questions=[q1, q2],
        )
        json_str = quiz.model_dump_json()
        restored = Quiz.model_validate_json(json_str)
        assert len(restored.questions) == 2
        assert restored.quiz_id == "exam_v1"
        assert restored.questions[0].id == "q1"
        assert restored.questions[1].chapter == 3

    def test_empty_quiz_valid(self):
        """A quiz with no questions is valid (template state)."""
        quiz = Quiz(title="Empty draft")
        assert len(quiz.questions) == 0

    def test_created_at_auto(self):
        """created_at is auto-populated."""
        quiz = Quiz(title="Auto timestamp")
        assert quiz.created_at is not None


# ── JSON Schema export test ─────────────────────────────────────────


class TestSchemaExport:
    """Tests for ``export_json_schemas()``."""

    def test_export_creates_valid_json_files(self):
        """The exported files are valid JSON and contain expected keys."""
        with tempfile.TemporaryDirectory() as tmp:
            export_json_schemas(tmp)
            for name in ("question", "quiz"):
                path = Path(tmp) / f"{name}.schema.json"
                assert path.exists(), f"{path} was not created"
                schema = json.loads(path.read_text())
                assert "properties" in schema or "$defs" in schema
                assert schema.get("type") == "object" or "$defs" in schema
