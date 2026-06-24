"""Validation & quality report for an assembled exam (Phase 5).

Produces a structured report (dict → JSON, or rendered Markdown) covering the
four quality dimensions the thesis cares about:

1. **Schema validity** — every question still round-trips through the
   :class:`~quizgen.schema.Question` model.
2. **Blueprint compliance** — per-chapter counts, difficulty mix, total, and
   allowed question types match the blueprint exactly.
3. **Grounding coverage** — share of questions traceable to source text (a
   ``source_ref`` is present and, when the source chunks are supplied, the
   answer's content words overlap the referenced passage).
4. **Duplicate rate** — share of questions involved in a near-duplicate pair.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass, field
from typing import Any

from pydantic import ValidationError

from quizgen.schema import Question, Quiz
from quizgen.similarity import find_near_duplicate_pairs
from quizgen.textmatch import extract_content_words


@dataclass
class ValidationReport:
    """Structured validation result; serialise via :meth:`to_dict`."""

    n_questions: int
    schema_valid: int
    schema_invalid: int
    schema_errors: list[str] = field(default_factory=list)

    blueprint_checked: bool = False
    blueprint_compliant: bool = False
    chapter_counts: dict[int, int] = field(default_factory=dict)
    chapter_expected: dict[int, int] = field(default_factory=dict)
    difficulty_counts: dict[str, int] = field(default_factory=dict)
    difficulty_expected: dict[str, int] = field(default_factory=dict)
    qtype_counts: dict[str, int] = field(default_factory=dict)
    qtype_expected: dict[str, int] = field(default_factory=dict)
    blueprint_issues: list[str] = field(default_factory=list)

    traceable_share: float = 0.0
    grounded_share: float | None = None

    duplicate_rate: float = 0.0
    n_duplicate_pairs: int = 0

    @property
    def passed(self) -> bool:
        """Overall gate: schema-valid and (if checked) blueprint-compliant."""
        return self.schema_invalid == 0 and (
            not self.blueprint_checked or self.blueprint_compliant
        )

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["passed"] = self.passed
        return d


def validate_exam(
    quiz: Quiz,
    blueprint: "Blueprint | None" = None,  # noqa: F821
    *,
    source_chunks: dict[str, str] | None = None,
    duplicate_threshold: float = 0.9,
    encoder=None,
) -> ValidationReport:
    """Validate *quiz* and return a :class:`ValidationReport`.

    Parameters
    ----------
    quiz
        The assembled exam to check.
    blueprint
        If given, compliance (chapter/difficulty/total/qtypes) is checked
        against it.
    source_chunks
        Optional ``{chunk_id: text}`` map enabling the answer-overlap grounding
        check; without it, grounding falls back to "has a source_ref".
    duplicate_threshold
        Similarity threshold for the duplicate-rate measure.
    encoder
        Optional embedding encoder for the duplicate measure.
    """
    questions = quiz.questions
    n = len(questions)

    # 1. Schema validity.
    valid, invalid, errors = 0, 0, []
    for q in questions:
        try:
            Question.model_validate(q.model_dump())
            valid += 1
        except ValidationError as e:
            invalid += 1
            errors.append(f"{q.id}: {e.error_count()} error(s)")

    report = ValidationReport(
        n_questions=n, schema_valid=valid, schema_invalid=invalid, schema_errors=errors,
    )

    # 2. Blueprint compliance.
    if blueprint is not None:
        report.blueprint_checked = True
        _check_blueprint(report, questions, blueprint)

    # 3. Grounding coverage.
    _check_grounding(report, questions, source_chunks)

    # 4. Duplicate rate.
    pairs = find_near_duplicate_pairs(questions, duplicate_threshold, encoder)
    involved = {i for pair in pairs for i in pair}
    report.n_duplicate_pairs = len(pairs)
    report.duplicate_rate = round(len(involved) / n, 4) if n else 0.0

    return report


def _check_blueprint(report: ValidationReport, questions, blueprint) -> None:
    chap = Counter(q.chapter for q in questions)
    report.chapter_counts = dict(sorted(chap.items()))
    report.chapter_expected = blueprint.resolve_chapter_counts()

    diff = Counter(q.difficulty.value for q in questions)
    report.difficulty_counts = dict(diff)
    report.difficulty_expected = {
        d.value: c for d, c in blueprint.resolve_difficulty_counts().items()
    }

    qty = Counter(q.qtype.value for q in questions)
    report.qtype_counts = dict(qty)
    report.qtype_expected = {
        q.value: c for q, c in blueprint.resolve_qtype_counts().items()
    }

    issues: list[str] = []
    if len(questions) != blueprint.total_questions:
        issues.append(
            f"total {len(questions)} != expected {blueprint.total_questions}"
        )
    if report.chapter_expected and report.chapter_counts != report.chapter_expected:
        issues.append(
            f"chapter mix {report.chapter_counts} != {report.chapter_expected}"
        )
    if report.difficulty_expected:
        for d, need in report.difficulty_expected.items():
            if report.difficulty_counts.get(d, 0) != need:
                issues.append(
                    f"difficulty '{d}' {report.difficulty_counts.get(d, 0)} != {need}"
                )
    if report.qtype_expected:
        for t, need in report.qtype_expected.items():
            if report.qtype_counts.get(t, 0) != need:
                issues.append(
                    f"qtype '{t}' {report.qtype_counts.get(t, 0)} != {need}"
                )
    if blueprint.allowed_qtypes:
        allowed = {q.value for q in blueprint.allowed_qtypes}
        bad = {q.qtype.value for q in questions} - allowed
        if bad:
            issues.append(f"disallowed qtypes present: {sorted(bad)}")

    report.blueprint_issues = issues
    report.blueprint_compliant = not issues


def _check_grounding(report, questions, source_chunks) -> None:
    n = len(questions)
    if not n:
        return
    traceable = sum(1 for q in questions if q.source_ref and q.source_ref.strip())
    report.traceable_share = round(traceable / n, 4)

    if source_chunks:
        grounded = 0
        for q in questions:
            refs = [r.strip() for r in q.source_ref.replace(";", ",").split(",")]
            context = " ".join(source_chunks.get(r, "") for r in refs)
            if not context.strip():
                continue
            ctx_words = extract_content_words(context)
            ans_words = extract_content_words(q.answer) or extract_content_words(q.stem)
            if not ans_words:
                grounded += 1
                continue
            overlap = len(ans_words & ctx_words) / len(ans_words)
            if overlap >= 0.3:
                grounded += 1
        report.grounded_share = round(grounded / n, 4)


# ── Rendering ───────────────────────────────────────────────────────


def report_to_markdown(report: ValidationReport, title: str = "Exam Validation Report") -> str:
    """Render a :class:`ValidationReport` as Markdown."""
    r = report
    lines = [f"# {title}", ""]
    lines.append(f"**Overall:** {'✅ PASS' if r.passed else '❌ FAIL'}  ")
    lines.append(f"**Questions:** {r.n_questions}")
    lines.append("")

    lines.append("## 1. Schema validity")
    lines.append(f"- Valid: **{r.schema_valid} / {r.n_questions}**")
    lines.append(f"- Invalid: {r.schema_invalid}")
    for err in r.schema_errors:
        lines.append(f"  - {err}")
    lines.append("")

    lines.append("## 2. Blueprint compliance")
    if not r.blueprint_checked:
        lines.append("- _No blueprint supplied — skipped._")
    else:
        lines.append(f"- Compliant: **{'yes' if r.blueprint_compliant else 'NO'}**")
        lines.append(f"- Chapters (got → expected): {r.chapter_counts} → {r.chapter_expected}")
        lines.append(
            f"- Difficulty (got → expected): {r.difficulty_counts} → {r.difficulty_expected}"
        )
        if r.qtype_expected:
            lines.append(
                f"- Q-types (got → expected): {r.qtype_counts} → {r.qtype_expected}"
            )
        for issue in r.blueprint_issues:
            lines.append(f"  - ⚠ {issue}")
    lines.append("")

    lines.append("## 3. Grounding coverage")
    lines.append(f"- Traceable (has source_ref): **{r.traceable_share:.0%}**")
    if r.grounded_share is None:
        lines.append("- Answer-overlap grounding: _source text not supplied — skipped._")
    else:
        lines.append(f"- Answer supported by source text: **{r.grounded_share:.0%}**")
    lines.append("")

    lines.append("## 4. Duplicate rate")
    lines.append(f"- Near-duplicate pairs: {r.n_duplicate_pairs}")
    lines.append(f"- Questions involved in a duplicate: **{r.duplicate_rate:.0%}**")
    lines.append("")

    return "\n".join(lines)


# ── CLI ─────────────────────────────────────────────────────────────


def main() -> None:
    import argparse
    import json
    import sys
    from pathlib import Path

    from quizgen.blueprint import load_blueprint

    parser = argparse.ArgumentParser(
        prog="quizgen.validate",
        description="Validate an assembled exam and emit a quality report.",
    )
    parser.add_argument("--exam", required=True, help="Path to exam/quiz JSON")
    parser.add_argument("--blueprint", default=None, help="Blueprint YAML for compliance")
    parser.add_argument("--out", default=None, help="Write Markdown report to this path")
    parser.add_argument("--json-out", default=None, help="Write JSON report to this path")
    args = parser.parse_args()

    quiz = Quiz.model_validate_json(Path(args.exam).read_text())
    blueprint = load_blueprint(args.blueprint) if args.blueprint else None

    report = validate_exam(quiz, blueprint)
    md = report_to_markdown(report, title=f"Validation — {quiz.title}")
    print("\n" + md)

    if args.out:
        Path(args.out).write_text(md)
        print(f"💾 Markdown report -> {args.out}")
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(report.to_dict(), indent=2))
        print(f"💾 JSON report -> {args.json_out}")

    sys.exit(0 if report.passed else 1)


if __name__ == "__main__":
    main()
