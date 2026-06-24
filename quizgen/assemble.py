"""Automated Test Assembly (ATA): select a quiz from a question pool.

Given a *pool* of candidate questions (the JSON produced by ``quizgen.generate``)
and a *blueprint* (a YAML file of constraints), this module selects a subset
that exactly satisfies the blueprint and writes one or more assembled quiz
forms to an output directory.

The blueprint expresses **exact-count quotas** over any of four dimensions —
``chapters``, ``qtypes``, ``difficulty``, ``bloom`` — plus a ``total_questions``
target.  Selection is solved as a 0/1 integer program (via PuLP); each quota
becomes an equality constraint and a random objective (seeded) spreads variety
across forms.

CLI::

    python -m quizgen.assemble \\
        --pool questions.json \\
        --blueprint blueprint.yaml \\
        --out-dir out

Blueprint example (all dimensions optional — omit one to leave it
unconstrained)::

    title: "AI-1 Practice Exam"
    total_questions: 8
    forms: 1
    seed: 42
    qtypes:
        mcq: 2
        true_false: 2
        short_answer: 2
        cloze: 2
    chapters:
        2: 5
        3: 3
"""

from __future__ import annotations

import argparse
import json
import logging
import random
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Callable

import yaml

from quizgen.schema import Question, Quiz

logger = logging.getLogger(__name__)

# Maps a blueprint dimension key to the function that reads the matching value
# off a Question.  Values are stringified so YAML ints (chapters) and enum
# values (qtypes/difficulty/bloom) compare uniformly.
DIMENSIONS: dict[str, Callable[[Question], str]] = {
    "chapters": lambda q: str(q.chapter),
    "qtypes": lambda q: q.qtype.value,
    "difficulty": lambda q: q.difficulty.value,
    "bloom": lambda q: q.bloom_level.value,
}


# ── Loading ─────────────────────────────────────────────────────────


def load_pool(path: str | Path) -> list[Question]:
    """Load a question pool from a Quiz JSON (``{"questions": [...]}``) or a
    bare list of question objects."""
    data = json.loads(Path(path).read_text())
    if isinstance(data, dict):
        raw = data.get("questions", [])
    elif isinstance(data, list):
        raw = data
    else:
        raise ValueError(f"Unrecognised pool format in {path}: {type(data)}")

    pool = [Question.model_validate(q) for q in raw]
    if not pool:
        raise ValueError(f"Pool {path} contains no questions.")
    logger.info("Loaded %d questions from %s", len(pool), path)
    return pool


def load_blueprint(path: str | Path) -> dict[str, Any]:
    """Load and lightly validate a blueprint YAML file."""
    bp = yaml.safe_load(Path(path).read_text()) or {}
    if "total_questions" not in bp:
        raise ValueError("Blueprint must define 'total_questions'.")

    total = int(bp["total_questions"])
    for dim in DIMENSIONS:
        quotas = bp.get(dim)
        if quotas is None:
            continue
        if not isinstance(quotas, dict):
            raise ValueError(f"Blueprint '{dim}' must be a mapping of value -> count.")
        quota_sum = sum(int(v) for v in quotas.values())
        if quota_sum > total:
            raise ValueError(
                f"Blueprint '{dim}' quotas sum to {quota_sum}, "
                f"exceeding total_questions={total}."
            )
    return bp


# ── Feasibility diagnostics ─────────────────────────────────────────


def _check_pool_supply(pool: list[Question], blueprint: dict[str, Any]) -> list[str]:
    """Return human-readable reasons the pool cannot satisfy the blueprint
    (empty list = no obvious supply problem)."""
    problems: list[str] = []
    total = int(blueprint["total_questions"])
    forms = int(blueprint.get("forms", 1))
    needed = total * forms

    if len(pool) < needed:
        problems.append(
            f"pool has {len(pool)} questions but {needed} are needed "
            f"({total} × {forms} form(s))."
        )

    for dim, getter in DIMENSIONS.items():
        quotas = blueprint.get(dim)
        if not quotas:
            continue
        available = Counter(getter(q) for q in pool)
        for value, count in quotas.items():
            have = available.get(str(value), 0)
            want = int(count) * forms
            if have < want:
                problems.append(
                    f"{dim}={value}: need {want} (× {forms} form(s)) but pool has {have}."
                )
    return problems


# ── Assembly (ILP) ──────────────────────────────────────────────────


def assemble(pool: list[Question], blueprint: dict[str, Any]) -> list[Quiz]:
    """Assemble ``forms`` non-overlapping quizzes satisfying the blueprint.

    Raises ``RuntimeError`` if no selection satisfies the constraints, with a
    diagnostic describing which quota the pool cannot supply.
    """
    try:
        import pulp
    except ImportError as exc:  # pragma: no cover - depends on optional extra
        raise RuntimeError(
            "Automated Test Assembly needs PuLP. Install the assembly extra:\n"
            '    pip install -e ".[assembly]"'
        ) from exc

    total = int(blueprint["total_questions"])
    forms = int(blueprint.get("forms", 1))
    seed = int(blueprint.get("seed", 0))
    rng = random.Random(seed)

    # Fail fast with a clear message before handing an infeasible model to CBC.
    supply_problems = _check_pool_supply(pool, blueprint)
    if supply_problems:
        raise RuntimeError(
            "Pool cannot satisfy blueprint:\n  - " + "\n  - ".join(supply_problems)
        )

    prob = pulp.LpProblem("automated_test_assembly", pulp.LpMaximize)

    # x[f, i] == 1  ⇔  question i is placed on form f.
    x = {
        (f, i): pulp.LpVariable(f"x_{f}_{i}", cat="Binary")
        for f in range(forms)
        for i in range(len(pool))
    }

    for f in range(forms):
        # Exact length per form.
        prob += pulp.lpSum(x[f, i] for i in range(len(pool))) == total

        # One equality constraint per specified quota value.
        for dim, getter in DIMENSIONS.items():
            quotas = blueprint.get(dim)
            if not quotas:
                continue
            for value, count in quotas.items():
                members = [
                    i for i in range(len(pool)) if getter(pool[i]) == str(value)
                ]
                prob += pulp.lpSum(x[f, i] for i in members) == int(count)

    # A question may appear on at most one form (forms are disjoint).
    for i in range(len(pool)):
        prob += pulp.lpSum(x[f, i] for f in range(forms)) <= 1

    # Random seeded objective → variety; ties broken reproducibly.
    weights = {(f, i): rng.random() for f in range(forms) for i in range(len(pool))}
    prob += pulp.lpSum(weights[k] * x[k] for k in x)

    status = prob.solve(pulp.PULP_CBC_CMD(msg=0))
    if pulp.LpStatus[status] != "Optimal":
        raise RuntimeError(
            f"No assembly satisfies the blueprint (solver status: "
            f"{pulp.LpStatus[status]}). Loosen the quotas or enlarge the pool."
        )

    quizzes: list[Quiz] = []
    for f in range(forms):
        selected = [pool[i] for i in range(len(pool)) if x[f, i].value() == 1]
        title = blueprint.get("title", "Assembled Quiz")
        if forms > 1:
            title = f"{title} — Form {f + 1}"
        quizzes.append(
            Quiz(title=title, blueprint=dict(blueprint), questions=selected)
        )
    return quizzes


# ── Output / reporting ──────────────────────────────────────────────


def _print_distribution(quiz: Quiz) -> None:
    by_ch = Counter(q.chapter for q in quiz.questions)
    by_qt = Counter(q.qtype.value for q in quiz.questions)
    by_df = Counter(q.difficulty.value for q in quiz.questions)
    print(f"    chapters:   {dict(sorted(by_ch.items()))}")
    print(f"    qtypes:     {dict(sorted(by_qt.items()))}")
    print(f"    difficulty: {dict(sorted(by_df.items()))}")


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="quizgen.assemble",
        description="Assemble a quiz from a question pool using a blueprint (ATA).",
    )
    parser.add_argument("--pool", required=True, help="Path to the question pool JSON.")
    parser.add_argument(
        "--blueprint", required=True, help="Path to the blueprint YAML file."
    )
    parser.add_argument(
        "--out-dir", default="out", help="Directory for assembled quiz(zes)."
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Enable verbose logging."
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s  %(name)s  %(message)s",
    )

    pool = load_pool(args.pool)
    blueprint = load_blueprint(args.blueprint)

    print(f"\n🧩 Assembling from pool of {len(pool)} questions")
    print(f"   Blueprint: {args.blueprint}")

    try:
        quizzes = assemble(pool, blueprint)
    except RuntimeError as exc:
        print(f"\n❌ {exc}")
        sys.exit(1)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    for f, quiz in enumerate(quizzes, 1):
        out_path = out_dir / (
            "quiz.json" if len(quizzes) == 1 else f"quiz_form{f}.json"
        )
        out_path.write_text(quiz.model_dump_json(indent=2))
        print(f"\n💾 Form {f}: {len(quiz.questions)} questions → {out_path}")
        _print_distribution(quiz)

    print(f"\n✅ Assembled {len(quizzes)} form(s) into {out_dir}/\n")


if __name__ == "__main__":
    main()
