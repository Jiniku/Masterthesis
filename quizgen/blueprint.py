"""Professor-facing exam blueprint (Phase 4).

A *blueprint* is the small YAML file a professor edits to specify what the
final exam(s) must look like: how many questions in total, how they split
across chapters, the target difficulty mix, which question types are allowed,
and how many parallel versions to assemble.  It is deliberately separate from
the (LLM-driven) generation step — the generator produces a large tagged
*pool*; the blueprint drives the *selection* (Automated Test Assembly).

Chapter and difficulty quantities may be given as integer counts, fractions
(``0.5``) or percentages (``"50%"``); :meth:`Blueprint.resolve` converts them
into exact integer counts that sum to ``total_questions`` using the
largest-remainder method, so the blueprint is unambiguous downstream.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, field_validator

from quizgen.schema import Difficulty, QuestionType

# ── Apportionment helpers ───────────────────────────────────────────
#
# These turn fractional targets into integer counts that sum exactly to the
# total, using the largest-remainder (Hamilton) method.  They live here
# because blueprint resolution is their only consumer.

_DEFAULT_DIFFICULTY_MIX: dict[Difficulty, float] = {
    Difficulty.EASY: 0.4,
    Difficulty.MEDIUM: 0.4,
    Difficulty.HARD: 0.2,
}


def _largest_remainder(weights: dict, total: int) -> dict:
    """Allocate *total* integer units across *weights* (fractions summing ~1).

    Guarantees the allocation sums to exactly *total*.
    """
    raw = {k: w * total for k, w in weights.items()}
    floors = {k: int(v) for k, v in raw.items()}
    allocated = sum(floors.values())
    remainder = total - allocated

    # Hand out leftover units to the largest fractional remainders.
    order = sorted(raw, key=lambda k: raw[k] - floors[k], reverse=True)
    for k in order[:remainder]:
        floors[k] += 1
    return floors


def build_difficulty_plan(
    total: int,
    mix: dict[str, float] | dict[Difficulty, float] | None = None,
) -> dict[Difficulty, int]:
    """Turn a target difficulty *mix* (fractions) into integer counts.

    The largest-remainder method is used so the counts always sum to *total*
    exactly, even when the fractions don't divide evenly.  Defaults to a
    40 / 40 / 20 easy/medium/hard spread.
    """
    if mix is None:
        mix = dict(_DEFAULT_DIFFICULTY_MIX)

    # Normalise keys to Difficulty enums and drop non-positive weights.
    norm: dict[Difficulty, float] = {}
    for key, frac in mix.items():
        diff = key if isinstance(key, Difficulty) else Difficulty(str(key))
        if frac > 0:
            norm[diff] = float(frac)

    weight_sum = sum(norm.values()) or 1.0
    return _largest_remainder({d: w / weight_sum for d, w in norm.items()}, total)


class Blueprint(BaseModel):
    """Constraints that drive Automated Test Assembly."""

    title: str = "Generated Exam"
    total_questions: int = Field(..., ge=1)

    # Per-chapter amounts: int counts, fractions, or "NN%" strings.
    chapters: dict[int, float | str | int] = Field(default_factory=dict)

    # Target difficulty mix (fractions or percentages). Empty = no constraint.
    difficulty_mix: dict[str, float | str] = Field(default_factory=dict)

    # Restrict the question formats that may be selected. Empty = all allowed.
    allowed_qtypes: list[QuestionType] = Field(default_factory=list)

    versions: int = Field(default=1, ge=1)
    selector: str = Field(default="greedy")  # "greedy" | "mip"

    # Cross-version near-duplicate threshold (token/cosine similarity).
    dedup_similarity: float = Field(default=0.85, ge=0.0, le=1.0)

    @field_validator("selector")
    @classmethod
    def _check_selector(cls, v: str) -> str:
        if v not in ("greedy", "mip"):
            raise ValueError("selector must be 'greedy' or 'mip'")
        return v

    # ── Resolution helpers ──────────────────────────────────────────

    def resolve_chapter_counts(self) -> dict[int, int]:
        """Resolve per-chapter amounts into integer counts summing to total."""
        if not self.chapters:
            return {}
        weights = {ch: _as_fraction(v) for ch, v in self.chapters.items()}

        # If the supplied values are plainly integer counts that already sum to
        # the total, trust them verbatim (professor specified exact counts).
        if all(_is_int_count(v) for v in self.chapters.values()):
            counts = {ch: int(v) for ch, v in self.chapters.items()}
            if sum(counts.values()) == self.total_questions:
                return counts

        total_w = sum(weights.values()) or 1.0
        return _largest_remainder(
            {ch: w / total_w for ch, w in weights.items()}, self.total_questions
        )

    def resolve_difficulty_counts(self) -> dict[Difficulty, int]:
        """Resolve the difficulty mix into integer counts summing to total."""
        if not self.difficulty_mix:
            return {}
        mix = {k: _as_fraction(v) for k, v in self.difficulty_mix.items()}
        return build_difficulty_plan(self.total_questions, mix)

    def resolve(self) -> dict[str, Any]:
        """Return a fully-resolved, JSON-serialisable view of the blueprint."""
        return {
            "title": self.title,
            "total_questions": self.total_questions,
            "chapter_counts": self.resolve_chapter_counts(),
            "difficulty_counts": {
                d.value: n for d, n in self.resolve_difficulty_counts().items()
            },
            "allowed_qtypes": [q.value for q in self.allowed_qtypes],
            "versions": self.versions,
            "selector": self.selector,
            "dedup_similarity": self.dedup_similarity,
        }


def _as_fraction(value: float | str | int) -> float:
    """Coerce a count / fraction / 'NN%' string to a float weight."""
    if isinstance(value, str):
        s = value.strip()
        if s.endswith("%"):
            return float(s[:-1]) / 100.0
        return float(s)
    return float(value)


def _is_int_count(value: float | str | int) -> bool:
    """True if *value* is an integer count (not a fraction or percentage)."""
    if isinstance(value, str):
        return value.strip().isdigit()
    if isinstance(value, bool):
        return False
    return isinstance(value, int) or (isinstance(value, float) and value.is_integer() and value > 1)


def load_blueprint(path: str | Path) -> Blueprint:
    """Load and validate a blueprint YAML file."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Blueprint not found: {path}")
    data = yaml.safe_load(path.read_text()) or {}
    return Blueprint.model_validate(data)
