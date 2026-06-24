"""Automated Test Assembly — select exam(s) from a pool (Phase 4).

Generation (Phases 1-3) produces a large, tagged *pool* of candidate
questions.  Assembly is the separate *selection* step that picks the subset
matching the professor's :class:`~quizgen.blueprint.Blueprint`.  Two selectors
sit behind one :class:`Selector` interface so they can be compared in the
thesis:

``GreedySelector``
    A fast, content-balancing greedy/random fill.  Honours per-chapter counts
    and tries to respect the difficulty marginal, skipping near-duplicates and
    questions already used in another version.

``MIPSelector``
    A mixed-integer program (PuLP/CBC) that meets per-chapter **and**
    difficulty counts exactly, maximises total question quality/coverage,
    keeps parallel versions disjoint, and forbids near-duplicate pairs across
    versions.  Falls back to a difficulty-relaxed model (recorded in
    diagnostics) only if the exact program is infeasible for the given pool.

The selector is chosen by ``blueprint.selector`` so switching is a config edit.
"""

from __future__ import annotations

import logging
import random
from abc import ABC, abstractmethod
from collections import defaultdict
from dataclasses import dataclass, field

from quizgen.blueprint import Blueprint
from quizgen.schema import Difficulty, Question, Quiz
from quizgen.similarity import find_near_duplicate_pairs

logger = logging.getLogger(__name__)


# ── Quality heuristic ───────────────────────────────────────────────


def question_quality(q: Question) -> float:
    """A cheap proxy for question quality used to rank candidates.

    Rewards substantive explanations, well-formed MCQ option sets, and the
    more discriminating Bloom levels.  Not a substitute for the Phase 5
    LLM-as-judge — just a tie-breaker / objective weight for selection.
    """
    score = 1.0
    if len(q.explanation) >= 60:
        score += 0.3
    elif len(q.explanation) >= 30:
        score += 0.15
    if q.qtype.value == "mcq" and q.options and len(q.options) == 4:
        score += 0.2
    if q.bloom_level.value in ("analyze", "evaluate", "create"):
        score += 0.2
    if q.difficulty.value == "hard":
        score += 0.1
    return score


# ── Result container ────────────────────────────────────────────────


@dataclass
class AssemblyResult:
    """Outcome of an assembly run."""

    versions: list[list[Question]]
    resolved: dict
    selector_name: str
    diagnostics: dict = field(default_factory=dict)

    def to_quizzes(self) -> list[Quiz]:
        """Wrap each version as a :class:`Quiz` embedding the resolved blueprint."""
        quizzes: list[Quiz] = []
        for i, qs in enumerate(self.versions, 1):
            blueprint = dict(self.resolved)
            blueprint["version"] = i
            blueprint["selector"] = self.selector_name
            blueprint["diagnostics"] = self.diagnostics
            quizzes.append(
                Quiz(
                    title=f"{self.resolved.get('title', 'Exam')} — Version {chr(64 + i)}",
                    blueprint=blueprint,
                    questions=qs,
                )
            )
        return quizzes


# ── Selector interface ──────────────────────────────────────────────


class Selector(ABC):
    """Strategy interface: pick *blueprint.versions* exams from *pool*."""

    name: str = "base"

    @abstractmethod
    def select(self, pool: list[Question], blueprint: Blueprint) -> AssemblyResult:
        ...


def _index_pool(pool: list[Question], allowed_qtypes) -> list[Question]:
    """Filter the pool to allowed question types (empty = all allowed)."""
    if not allowed_qtypes:
        return list(pool)
    allowed = {q.value for q in allowed_qtypes}
    return [q for q in pool if q.qtype.value in allowed]


def _check_pool_capacity(
    pool: list[Question], chapter_counts: dict[int, int], versions: int
) -> list[str]:
    """Return human-readable warnings when the pool can't satisfy the demand."""
    warnings: list[str] = []
    by_chapter: dict[int, int] = defaultdict(int)
    for q in pool:
        by_chapter[q.chapter] += 1
    for ch, need in chapter_counts.items():
        have = by_chapter.get(ch, 0)
        if have < need * versions:
            warnings.append(
                f"Chapter {ch}: need {need}×{versions}={need * versions} "
                f"non-overlapping questions but pool has only {have}."
            )
    return warnings


# ── Greedy selector ─────────────────────────────────────────────────


class GreedySelector(Selector):
    """Greedy/random content-balanced selection."""

    name = "greedy"

    def __init__(self, seed: int | None = 42) -> None:
        self._rng = random.Random(seed)

    def select(self, pool: list[Question], blueprint: Blueprint) -> AssemblyResult:
        candidates = _index_pool(pool, blueprint.allowed_qtypes)
        chapter_counts = blueprint.resolve_chapter_counts()
        difficulty_counts = blueprint.resolve_difficulty_counts()

        diagnostics: dict = {
            "capacity_warnings": _check_pool_capacity(
                candidates, chapter_counts, blueprint.versions
            )
        }

        dup_pairs = find_near_duplicate_pairs(candidates, blueprint.dedup_similarity)
        dup_map: dict[int, set[int]] = defaultdict(set)
        for i, j in dup_pairs:
            dup_map[i].add(j)
            dup_map[j].add(i)

        used_global: set[int] = set()          # question indices used anywhere
        blocked: set[int] = set()              # + their near-duplicates
        versions: list[list[Question]] = []

        for _ in range(blueprint.versions):
            chosen = self._fill_one_version(
                candidates, chapter_counts, difficulty_counts,
                used_global, blocked, dup_map,
            )
            versions.append([candidates[i] for i in chosen])
            for i in chosen:
                used_global.add(i)
                blocked.add(i)
                blocked.update(dup_map[i])

        return AssemblyResult(versions, blueprint.resolve(), self.name, diagnostics)

    def _fill_one_version(
        self, candidates, chapter_counts, difficulty_counts,
        used_global, blocked, dup_map,
    ) -> list[int]:
        by_chapter: dict[int, list[int]] = defaultdict(list)
        for idx, q in enumerate(candidates):
            by_chapter[q.chapter].append(idx)

        diff_remaining = dict(difficulty_counts)  # may be empty (no constraint)
        chosen: list[int] = []
        used_local = set(blocked)

        for ch, need in chapter_counts.items():
            pool_ch = [i for i in by_chapter.get(ch, []) if i not in used_local]
            self._rng.shuffle(pool_ch)
            # Prefer questions whose difficulty still has quota left.
            picked = 0
            # Two passes: first honour difficulty quota, then fill remainder.
            for prefer_quota in (True, False):
                for i in list(pool_ch):
                    if picked >= need:
                        break
                    if i in used_local:
                        continue
                    d = Difficulty(candidates[i].difficulty.value)
                    if prefer_quota and diff_remaining and diff_remaining.get(d, 0) <= 0:
                        continue
                    chosen.append(i)
                    used_local.add(i)
                    used_local.update(dup_map[i])
                    if diff_remaining.get(d, 0) > 0:
                        diff_remaining[d] -= 1
                    picked += 1
                if picked >= need:
                    break
        return chosen


# ── MIP selector ────────────────────────────────────────────────────


class MIPSelector(Selector):
    """Mixed-integer programming selection via PuLP/CBC."""

    name = "mip"

    def select(self, pool: list[Question], blueprint: Blueprint) -> AssemblyResult:
        import pulp

        candidates = _index_pool(pool, blueprint.allowed_qtypes)
        chapter_counts = blueprint.resolve_chapter_counts()
        difficulty_counts = blueprint.resolve_difficulty_counts()
        V = list(range(blueprint.versions))
        n = len(candidates)

        diagnostics: dict = {
            "capacity_warnings": _check_pool_capacity(
                candidates, chapter_counts, blueprint.versions
            )
        }

        dup_pairs = find_near_duplicate_pairs(candidates, blueprint.dedup_similarity)
        quality = [question_quality(q) for q in candidates]

        def build_and_solve(enforce_difficulty: bool):
            prob = pulp.LpProblem("exam_assembly", pulp.LpMaximize)
            x = {
                (i, v): pulp.LpVariable(f"x_{i}_{v}", cat="Binary")
                for i in range(n) for v in V
            }
            # Objective: maximise total quality across all selected items.
            prob += pulp.lpSum(quality[i] * x[(i, v)] for i in range(n) for v in V)

            for v in V:
                # Exact per-chapter counts.
                for ch, need in chapter_counts.items():
                    members = [i for i in range(n) if candidates[i].chapter == ch]
                    prob += pulp.lpSum(x[(i, v)] for i in members) == need
                # Exact difficulty counts (optionally relaxed).
                if enforce_difficulty and difficulty_counts:
                    for d, need in difficulty_counts.items():
                        members = [
                            i for i in range(n)
                            if candidates[i].difficulty.value == d.value
                        ]
                        prob += pulp.lpSum(x[(i, v)] for i in members) == need

            # Each question used in at most one version (disjoint versions).
            for i in range(n):
                prob += pulp.lpSum(x[(i, v)] for v in V) <= 1

            # Forbid near-duplicate pairs anywhere across versions.
            for i, j in dup_pairs:
                prob += (
                    pulp.lpSum(x[(i, v)] for v in V)
                    + pulp.lpSum(x[(j, v)] for v in V)
                    <= 1
                )

            status = prob.solve(pulp.PULP_CBC_CMD(msg=False))
            return prob, x, status

        prob, x, status = build_and_solve(enforce_difficulty=True)
        if pulp.LpStatus[status] != "Optimal":
            logger.warning(
                "Exact MIP infeasible (%s); relaxing difficulty constraints.",
                pulp.LpStatus[status],
            )
            diagnostics["difficulty_relaxed"] = True
            prob, x, status = build_and_solve(enforce_difficulty=False)

        diagnostics["solver_status"] = pulp.LpStatus[status]
        if pulp.LpStatus[status] != "Optimal":
            raise RuntimeError(
                f"MIP assembly failed: {pulp.LpStatus[status]}. "
                "Pool too small/imbalanced for the blueprint — see capacity warnings."
            )

        versions: list[list[Question]] = []
        for v in V:
            chosen = [
                candidates[i] for i in range(n)
                if pulp.value(x[(i, v)]) and pulp.value(x[(i, v)]) > 0.5
            ]
            versions.append(chosen)

        return AssemblyResult(versions, blueprint.resolve(), self.name, diagnostics)


# ── Factory & top-level entry point ─────────────────────────────────


def get_selector(blueprint: Blueprint) -> Selector:
    """Instantiate the selector named by the blueprint."""
    return MIPSelector() if blueprint.selector == "mip" else GreedySelector()


def assemble(pool: list[Question], blueprint: Blueprint) -> AssemblyResult:
    """Assemble exam version(s) from *pool* per *blueprint*."""
    selector = get_selector(blueprint)
    logger.info(
        "Assembling %d version(s) from a pool of %d using the '%s' selector",
        blueprint.versions, len(pool), selector.name,
    )
    return selector.select(pool, blueprint)


def load_pool(path: str | Path) -> list[Question]:  # noqa: F821
    """Load a pool of questions from a Quiz JSON file (or a bare list)."""
    import json
    from pathlib import Path

    data = json.loads(Path(path).read_text())
    raw = data.get("questions", data) if isinstance(data, dict) else data
    return [Question.model_validate(q) for q in raw]


# ── CLI ─────────────────────────────────────────────────────────────


def main() -> None:
    import argparse
    import sys
    from pathlib import Path

    from quizgen.blueprint import load_blueprint

    parser = argparse.ArgumentParser(
        prog="quizgen.assemble",
        description="Assemble exam(s) from a question pool using a blueprint (ATA).",
    )
    parser.add_argument("--blueprint", required=True, help="Path to blueprint.yaml")
    parser.add_argument("--pool", required=True, help="Path to pool JSON (Quiz or list)")
    parser.add_argument("--out", default="exam.json", help="Output path for version A")
    parser.add_argument(
        "--selector", choices=["greedy", "mip"], default=None,
        help="Override the selector named in the blueprint",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s  %(name)s  %(message)s",
    )

    blueprint = load_blueprint(args.blueprint)
    if args.selector:
        blueprint.selector = args.selector
    pool = load_pool(args.pool)

    print(f"\n📋 Blueprint: {blueprint.title}")
    resolved = blueprint.resolve()
    print(f"   Total/version: {resolved['total_questions']}")
    print(f"   Per chapter:   {resolved['chapter_counts']}")
    print(f"   Difficulty:    {resolved['difficulty_counts']}")
    print(f"   Versions:      {resolved['versions']}   Selector: {blueprint.selector}")
    print(f"   Pool size:     {len(pool)}")

    result = assemble(pool, blueprint)

    for w in result.diagnostics.get("capacity_warnings", []):
        print(f"   ⚠ {w}")

    quizzes = result.to_quizzes()
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    for i, quiz in enumerate(quizzes):
        # version A -> --out path; B, C... -> suffixed siblings
        if i == 0:
            path = out_path
        else:
            path = out_path.with_name(f"{out_path.stem}_v{i + 1}{out_path.suffix}")
        path.write_text(quiz.model_dump_json(indent=2))
        _print_version_report(quiz, blueprint, i + 1)
        print(f"   💾 Saved version {chr(65 + i)} -> {path}")

    # Final blueprint-compliance check across all versions.
    ok = all(_version_compliant(q, blueprint) for q in quizzes)
    print(f"\n{'✅' if ok else '❌'} Blueprint compliance: "
          f"{'all versions match exactly' if ok else 'MISMATCH — see report above'}")
    if not ok:
        sys.exit(1)


def _print_version_report(quiz: Quiz, blueprint: Blueprint, n: int) -> None:
    from collections import Counter

    chap = Counter(q.chapter for q in quiz.questions)
    diff = Counter(q.difficulty.value for q in quiz.questions)
    print(f"\n   ── Version {chr(64 + n)} ({len(quiz.questions)} questions) ──")
    print(f"      Per chapter: {dict(sorted(chap.items()))}")
    print(f"      Difficulty:  {dict(diff)}")


def _version_compliant(quiz: Quiz, blueprint: Blueprint) -> bool:
    from collections import Counter

    chap = Counter(q.chapter for q in quiz.questions)
    if dict(chap) != blueprint.resolve_chapter_counts():
        return False
    if len(quiz.questions) != blueprint.total_questions:
        return False
    return True


if __name__ == "__main__":
    main()
