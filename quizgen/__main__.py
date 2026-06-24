"""quizgen — assemble an exam from an existing question bank.

You bring a JSON file of questions-with-metadata (the *pool*); quizgen selects
a blueprint-compliant subset via Automated Test Assembly (greedy or MIP),
optionally de-duplicating the pool first and validating the result. There is
no LLM and no PDF ingestion — selection only.

Constraints come from a blueprint YAML and/or command-line flags; **flags
override the YAML**, so you can keep a base ``blueprint.yaml`` and tweak a run
from the command line.

Examples
--------
    # Pure command-line: pick 20 questions, 10/6/4 across chapters, 40/40/20
    # difficulty, two disjoint versions, optimal (MIP) selection.
    python -m quizgen --pool questions.json \
        --total 20 --chapters 1:10,2:6,3:4 \
        --difficulty 0.4,0.4,0.2 --versions 2 --selector mip

    # Use a blueprint file, override just the version count and selector:
    python -m quizgen --pool questions.json --blueprint blueprint.yaml \
        --versions 3 --selector greedy

    # Deduplicate the pool first, then write a validation report per version:
    python -m quizgen --pool questions.json --blueprint blueprint.yaml \
        --dedup --validate --out-dir out
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import yaml

from quizgen.assemble import assemble, load_pool
from quizgen.blueprint import Blueprint
from quizgen.schema import QuestionType

logger = logging.getLogger(__name__)


# ── Argument parsers for the override flags ─────────────────────────


def parse_chapter_counts(spec: str) -> dict[int, float | str | int]:
    """Parse ``'1:10,2:6,3:4'`` or ``'1:50%,2:30%,3:20%'`` into a mapping.

    Values keep their natural type so the blueprint can resolve them:
    ``"50%"`` stays a percentage string, ``"0.5"`` a fraction, ``"10"`` an int.
    """
    out: dict[int, float | str | int] = {}
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        key, _, val = part.partition(":")
        val = val.strip()
        chapter = int(key.strip())
        if val.endswith("%"):
            out[chapter] = val
        elif "." in val:
            out[chapter] = float(val)
        else:
            out[chapter] = int(val)
    return out


def parse_difficulty_mix(spec: str) -> dict[str, float]:
    """Parse a difficulty mix.

    Accepts positional fractions ``'0.4,0.4,0.2'`` (easy, medium, hard) or
    named pairs ``'easy:0.4,medium:0.4,hard:0.2'``.
    """
    spec = spec.strip()
    if ":" in spec:
        mix: dict[str, float] = {}
        for part in spec.split(","):
            key, _, val = part.partition(":")
            mix[key.strip()] = float(val)
        return mix
    fracs = [float(x) for x in spec.split(",") if x.strip()]
    names = ["easy", "medium", "hard"]
    if len(fracs) > len(names):
        raise ValueError("difficulty mix takes at most 3 positional values")
    return {names[i]: fracs[i] for i in range(len(fracs))}


def parse_qtypes(spec: str) -> list[str]:
    """Parse ``'mcq,short_answer'`` into a list of qtype strings (validated)."""
    types: list[str] = []
    valid = {t.value for t in QuestionType}
    for part in spec.split(","):
        t = part.strip()
        if not t:
            continue
        if t not in valid:
            raise ValueError(f"unknown qtype '{t}'; valid: {sorted(valid)}")
        types.append(t)
    return types


# ── Blueprint construction (YAML defaults + flag overrides) ─────────


def build_blueprint(args: argparse.Namespace) -> Blueprint:
    """Build a :class:`Blueprint` from an optional YAML plus CLI overrides."""
    data: dict = {}
    if args.blueprint:
        path = Path(args.blueprint)
        if not path.exists():
            raise FileNotFoundError(f"Blueprint not found: {path}")
        data = yaml.safe_load(path.read_text()) or {}

    # CLI flags override the YAML, field by field.
    if args.title is not None:
        data["title"] = args.title
    if args.total is not None:
        data["total_questions"] = args.total
    if args.chapters is not None:
        data["chapters"] = parse_chapter_counts(args.chapters)
    if args.difficulty is not None:
        data["difficulty_mix"] = parse_difficulty_mix(args.difficulty)
    if args.qtypes is not None:
        data["allowed_qtypes"] = parse_qtypes(args.qtypes)
    if args.versions is not None:
        data["versions"] = args.versions
    if args.selector is not None:
        data["selector"] = args.selector
    if args.dedup_similarity is not None:
        data["dedup_similarity"] = args.dedup_similarity

    if "total_questions" not in data:
        raise ValueError(
            "total number of questions is required — pass --total N or set "
            "'total_questions' in the blueprint YAML."
        )
    return Blueprint.model_validate(data)


# ── CLI ─────────────────────────────────────────────────────────────


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="quizgen",
        description="Assemble exam(s) from a question-bank JSON using a "
        "blueprint and/or CLI flags (Automated Test Assembly).",
    )
    p.add_argument("--pool", required=True, help="Path to question-bank JSON (Quiz or bare list)")
    p.add_argument("--blueprint", default=None, help="Blueprint YAML (defaults; flags override)")

    g = p.add_argument_group("blueprint overrides (take precedence over the YAML)")
    g.add_argument("--title", default=None, help="Exam title")
    g.add_argument("--total", type=int, default=None, help="Total questions per version")
    g.add_argument("--chapters", default=None,
                   help="Per-chapter amounts, e.g. '1:10,2:6,3:4' or '1:50%%,2:30%%,3:20%%'")
    g.add_argument("--difficulty", default=None,
                   help="Difficulty mix, e.g. '0.4,0.4,0.2' or 'easy:0.4,medium:0.4,hard:0.2'")
    g.add_argument("--qtypes", default=None, help="Allowed types, e.g. 'mcq,short_answer'")
    g.add_argument("--versions", type=int, default=None, help="Number of parallel versions")
    g.add_argument("--selector", choices=["greedy", "mip"], default=None, help="Selection method")
    g.add_argument("--dedup-similarity", type=float, default=None,
                   help="Near-duplicate threshold used during assembly")

    p.add_argument("--dedup", action="store_true",
                   help="Drop near-duplicate questions from the pool before assembly")
    p.add_argument("--embeddings", action="store_true",
                   help="Use embeddings for --dedup (default: token overlap)")
    p.add_argument("--validate", action="store_true",
                   help="Write a Markdown validation report per version")
    p.add_argument("--out", default="exam.json", help="Output path for version A")
    p.add_argument("--out-dir", default=None,
                   help="Directory for all versions + reports (overrides --out)")
    p.add_argument("-v", "--verbose", action="store_true")
    return p


def main() -> None:
    args = _build_parser().parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s  %(name)s  %(message)s",
    )

    blueprint = build_blueprint(args)
    pool = load_pool(args.pool)

    print(f"\n📋 Blueprint: {blueprint.title}")
    resolved = blueprint.resolve()
    print(f"   Total/version: {resolved['total_questions']}")
    print(f"   Per chapter:   {resolved['chapter_counts']}")
    print(f"   Difficulty:    {resolved['difficulty_counts']}")
    print(f"   Versions:      {resolved['versions']}   Selector: {blueprint.selector}")
    print(f"   Pool size:     {len(pool)}")

    # Optional pool deduplication before assembly.
    if args.dedup:
        from quizgen.dedup import deduplicate

        res = deduplicate(
            pool,
            threshold=blueprint.dedup_similarity,
            use_embeddings=args.embeddings,
        )
        print(f"   Dedup ({res.method}, t={res.threshold}): "
              f"removed {res.n_removed}, {res.n_kept} remain")
        pool = res.kept

    result = assemble(pool, blueprint)
    for w in result.diagnostics.get("capacity_warnings", []):
        print(f"   ⚠ {w}")
    if result.diagnostics.get("difficulty_relaxed"):
        print("   ⚠ difficulty constraints relaxed to reach a feasible selection")

    quizzes = result.to_quizzes()

    # Resolve output paths.
    if args.out_dir:
        out_dir = Path(args.out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        paths = [out_dir / f"exam_v{i + 1}.json" for i in range(len(quizzes))]
    else:
        base = Path(args.out)
        base.parent.mkdir(parents=True, exist_ok=True)
        paths = [base if i == 0 else base.with_name(f"{base.stem}_v{i + 1}{base.suffix}")
                 for i in range(len(quizzes))]

    all_ok = True
    for i, (quiz, path) in enumerate(zip(quizzes, paths, strict=False), 1):
        path.write_text(quiz.model_dump_json(indent=2))
        _print_version_report(quiz, i)
        print(f"   💾 Saved version {chr(64 + i)} -> {path}")

        if args.validate:
            from quizgen.validate import report_to_markdown, validate_exam

            report = validate_exam(quiz, blueprint, duplicate_threshold=blueprint.dedup_similarity)
            md = report_to_markdown(report, title=f"Validation — {quiz.title}")
            report_path = path.with_suffix(".report.md")
            report_path.write_text(md)
            print(f"   📝 Report -> {report_path}  ({'PASS' if report.passed else 'FAIL'})")
            all_ok = all_ok and report.passed

    ok = all(_version_compliant(q, blueprint) for q in quizzes) and all_ok
    print(f"\n{'✅' if ok else '❌'} "
          f"{'All versions blueprint-compliant' if ok else 'MISMATCH — see report above'}")
    sys.exit(0 if ok else 1)


def _print_version_report(quiz, n: int) -> None:
    from collections import Counter

    chap = Counter(q.chapter for q in quiz.questions)
    diff = Counter(q.difficulty.value for q in quiz.questions)
    print(f"\n   ── Version {chr(64 + n)} ({len(quiz.questions)} questions) ──")
    print(f"      Per chapter: {dict(sorted(chap.items()))}")
    print(f"      Difficulty:  {dict(diff)}")


def _version_compliant(quiz, blueprint: Blueprint) -> bool:
    from collections import Counter

    chap = Counter(q.chapter for q in quiz.questions)
    if blueprint.resolve_chapter_counts() and dict(chap) != blueprint.resolve_chapter_counts():
        return False
    return len(quiz.questions) == blueprint.total_questions


if __name__ == "__main__":
    main()
