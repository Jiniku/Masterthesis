"""Pydantic v2 schemas for questions, quizzes, and blueprints.

Every enum and model here is the single source of truth.  The JSON Schema
export (see ``export_json_schemas()``) is generated from these models so the
two can never drift apart.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


# ── Enumerations ────────────────────────────────────────────────────


class QuestionType(str, Enum):
    """Supported question formats."""

    MCQ = "mcq"
    TRUE_FALSE = "true_false"
    SHORT_ANSWER = "short_answer"
    CLOZE = "cloze"


class BloomLevel(str, Enum):
    """Bloom's taxonomy cognitive levels (revised, 2001)."""

    REMEMBER = "remember"
    UNDERSTAND = "understand"
    APPLY = "apply"
    ANALYZE = "analyze"
    EVALUATE = "evaluate"
    CREATE = "create"


class Difficulty(str, Enum):
    """Three-tier difficulty scale."""

    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"


# ── Core models ─────────────────────────────────────────────────────


class Question(BaseModel):
    """A single exam / quiz question with full metadata.

    ``source_ref`` traces the question back to the text chunk(s) that
    grounded its generation — essential for the RAG audit trail.
    """

    id: str = Field(
        default_factory=lambda: uuid4().hex[:12],
        description="Unique question identifier.",
    )
    chapter: int = Field(..., ge=1, description="Chapter number the question belongs to.")
    section: str | None = Field(
        default=None,
        description="Section label within the chapter (e.g. '2.3').",
    )
    qtype: QuestionType = Field(..., description="Question format.")
    bloom_level: BloomLevel = Field(..., description="Bloom's taxonomy cognitive level.")
    difficulty: Difficulty = Field(..., description="Difficulty tier.")
    stem: str = Field(
        ...,
        min_length=10,
        description="The question text / prompt shown to the student.",
    )
    options: list[str] | None = Field(
        default=None,
        description="Answer options (required for MCQ, optional otherwise).",
    )
    answer: str = Field(
        ...,
        min_length=1,
        description="The correct answer (letter for MCQ, text otherwise).",
    )
    explanation: str = Field(
        ...,
        min_length=10,
        description="Explanation of why the answer is correct, for review.",
    )
    source_ref: str = Field(
        ...,
        description="Identifier(s) of the source chunk(s) this question is grounded in.",
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "id": "a1b2c3d4e5f6",
                    "chapter": 2,
                    "section": "2.1",
                    "qtype": "mcq",
                    "bloom_level": "understand",
                    "difficulty": "medium",
                    "stem": "Which data structure provides O(1) average-case lookup?",
                    "options": ["Linked list", "Hash table", "Binary tree", "Stack"],
                    "answer": "B",
                    "explanation": "Hash tables use a hash function to map keys to buckets, "
                    "giving O(1) average-case lookup time.",
                    "source_ref": "ch2_s1_chunk_003",
                }
            ]
        }
    }


class Quiz(BaseModel):
    """A complete quiz / exam consisting of selected questions.

    ``blueprint`` stores the professor's constraints that drove the
    Automated Test Assembly selection so the exam is fully reproducible.
    """

    quiz_id: str = Field(
        default_factory=lambda: uuid4().hex[:12],
        description="Unique quiz identifier.",
    )
    title: str = Field(..., description="Human-readable title for the quiz/exam.")
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC timestamp of creation.",
    )
    blueprint: dict[str, Any] = Field(
        default_factory=dict,
        description="The blueprint / constraints used to assemble this quiz.",
    )
    questions: list[Question] = Field(
        default_factory=list,
        description="Ordered list of questions in this quiz.",
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "quiz_id": "exam_2025_v1",
                    "title": "AI-1 Midterm Exam — Version A",
                    "created_at": "2025-07-01T10:00:00Z",
                    "blueprint": {
                        "total_questions": 20,
                        "chapters": {1: 10, 2: 6, 3: 4},
                        "difficulty_mix": {"easy": 0.4, "medium": 0.4, "hard": 0.2},
                    },
                    "questions": [],
                }
            ]
        }
    }


# ── JSON Schema export ──────────────────────────────────────────────


def export_json_schemas(out_dir: str | Path = "schemas") -> None:
    """Write ``Question`` and ``Quiz`` JSON Schemas to *out_dir*.

    These files are committed to the repo so external tools (validators,
    CI checks, the thesis appendix) always have a machine-readable
    reference that matches the Python models.
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    for name, model in [("question", Question), ("quiz", Quiz)]:
        schema = model.model_json_schema()
        path = out / f"{name}.schema.json"
        path.write_text(json.dumps(schema, indent=2) + "\n")
        print(f"  ✓ {path}")


if __name__ == "__main__":
    export_json_schemas()
