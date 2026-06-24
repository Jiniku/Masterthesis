"""Tests for the selection CLI — flag parsing and blueprint overrides.

The CLI lets constraints come from a blueprint YAML and/or command-line flags,
with **flags overriding the YAML**. These tests cover the parse helpers and the
override precedence in :func:`quizgen.__main__.build_blueprint`.
"""

from __future__ import annotations

import argparse

import pytest

from quizgen.__main__ import (
    build_blueprint,
    parse_chapter_counts,
    parse_difficulty_mix,
    parse_qtype_mix,
    parse_qtypes,
)
from quizgen.schema import Difficulty, QuestionType

# ── Flag parsers ────────────────────────────────────────────────────


class TestParsers:
    def test_chapter_counts_integers(self):
        assert parse_chapter_counts("1:10,2:6,3:4") == {1: 10, 2: 6, 3: 4}

    def test_chapter_counts_percentages_kept_as_strings(self):
        assert parse_chapter_counts("1:50%,2:30%,3:20%") == {1: "50%", 2: "30%", 3: "20%"}

    def test_chapter_counts_fractions(self):
        assert parse_chapter_counts("1:0.5,2:0.5") == {1: 0.5, 2: 0.5}

    def test_difficulty_positional(self):
        assert parse_difficulty_mix("0.4,0.4,0.2") == {"easy": 0.4, "medium": 0.4, "hard": 0.2}

    def test_difficulty_named(self):
        assert parse_difficulty_mix("easy:0.5,hard:0.5") == {"easy": 0.5, "hard": 0.5}

    def test_qtypes_valid(self):
        assert parse_qtypes("mcq,short_answer") == ["mcq", "short_answer"]

    def test_qtypes_invalid_rejected(self):
        with pytest.raises(ValueError):
            parse_qtypes("essay")

    def test_qtype_mix_named(self):
        assert parse_qtype_mix("mcq:0.4,true_false:0.2,short_answer:0.2,cloze:0.2") == {
            "mcq": 0.4, "true_false": 0.2, "short_answer": 0.2, "cloze": 0.2,
        }

    def test_qtype_mix_percentages(self):
        assert parse_qtype_mix("mcq:50%,cloze:50%") == {"mcq": 0.5, "cloze": 0.5}

    def test_qtype_mix_invalid_type_rejected(self):
        with pytest.raises(ValueError):
            parse_qtype_mix("essay:0.5,mcq:0.5")

    def test_qtype_mix_requires_named_pairs(self):
        with pytest.raises(ValueError):
            parse_qtype_mix("0.4,0.2,0.2,0.2")


# ── Blueprint construction & override precedence ────────────────────


def _args(**over) -> argparse.Namespace:
    base = dict(
        blueprint=None, title=None, total=None, chapters=None, difficulty=None,
        qtypes=None, qtype_mix=None, versions=None, selector=None, dedup_similarity=None,
    )
    base.update(over)
    return argparse.Namespace(**base)


class TestBuildBlueprint:
    def test_pure_cli(self):
        bp = build_blueprint(_args(total=20, chapters="1:10,2:6,3:4",
                                   difficulty="0.4,0.4,0.2", selector="mip", versions=2))
        assert bp.total_questions == 20
        assert bp.resolve_chapter_counts() == {1: 10, 2: 6, 3: 4}
        assert bp.resolve_difficulty_counts()[Difficulty.HARD] == 4
        assert bp.selector == "mip"
        assert bp.versions == 2

    def test_yaml_defaults(self, tmp_path):
        yml = tmp_path / "bp.yaml"
        yml.write_text(
            "total_questions: 20\nchapters: {1: '50%', 2: '30%', 3: '20%'}\n"
            "versions: 1\nselector: greedy\n"
        )
        bp = build_blueprint(_args(blueprint=str(yml)))
        assert bp.versions == 1
        assert bp.selector == "greedy"
        assert bp.resolve_chapter_counts() == {1: 10, 2: 6, 3: 4}

    def test_flags_override_yaml(self, tmp_path):
        yml = tmp_path / "bp.yaml"
        yml.write_text("total_questions: 20\nversions: 1\nselector: greedy\n")
        bp = build_blueprint(_args(blueprint=str(yml), versions=3, selector="mip"))
        assert bp.versions == 3       # overridden
        assert bp.selector == "mip"   # overridden
        assert bp.total_questions == 20  # from YAML

    def test_missing_total_errors(self):
        with pytest.raises(ValueError):
            build_blueprint(_args(selector="mip"))

    def test_qtype_mix_override(self):
        bp = build_blueprint(_args(
            total=20, qtype_mix="mcq:0.4,true_false:0.2,short_answer:0.2,cloze:0.2",
        ))
        counts = {q.value: c for q, c in bp.resolve_qtype_counts().items()}
        assert counts == {"mcq": 8, "true_false": 4, "short_answer": 4, "cloze": 4}
        assert QuestionType.MCQ in bp.resolve_qtype_counts()
