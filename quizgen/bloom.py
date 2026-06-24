"""Bloom's-taxonomy and difficulty control for question generation (Phase 3).

This module is the single source of truth for *how* a requested cognitive
level and difficulty are communicated to the LLM.  It provides:

* short natural-language descriptions of every Bloom level and difficulty
  tier (injected into the prompt so the model knows what is being asked for),
* one or two few-shot examples per Bloom level (Bloom-aligned prompting),
* helpers that turn a high-level request ("12 questions across all Bloom
  levels with a 40/40/20 easy/medium/hard spread") into a concrete, ordered
  list of :class:`QuestionSpec` objects that generation can fulfil exactly.

Keeping this separate from :mod:`quizgen.generate` keeps the prompt-craft in
one auditable place — useful for the thesis discussion of prompting strategy.
"""

from __future__ import annotations

from dataclasses import dataclass

from quizgen.schema import BloomLevel, Difficulty, QuestionType

# ── Bloom level descriptions ────────────────────────────────────────
#
# Phrasings are aligned with the revised (2001) taxonomy and tuned to nudge
# the model toward the cognitive *operation* rather than just the topic.

BLOOM_DESCRIPTIONS: dict[BloomLevel, str] = {
    BloomLevel.REMEMBER: (
        "Recall or recognise facts, terms, definitions, or basic concepts "
        "exactly as stated in the source. Verbs: define, list, name, state, "
        "identify. The answer is found verbatim or near-verbatim in the text."
    ),
    BloomLevel.UNDERSTAND: (
        "Demonstrate comprehension by explaining ideas in one's own words, "
        "summarising, or classifying. Verbs: explain, describe, summarise, "
        "interpret, compare. Goes beyond recall but needs no new application."
    ),
    BloomLevel.APPLY: (
        "Use a concept, rule, or procedure from the text in a concrete, often "
        "novel, situation. Verbs: apply, compute, solve, demonstrate, use. "
        "Typically presents a small scenario the student must work through."
    ),
    BloomLevel.ANALYZE: (
        "Break material into parts and examine relationships, structure, or "
        "underlying assumptions. Verbs: analyse, differentiate, contrast, "
        "categorise, infer. Asks *why* or *how* components relate."
    ),
    BloomLevel.EVALUATE: (
        "Make and justify a judgement against criteria. Verbs: evaluate, "
        "justify, critique, assess, defend. The student must take a position "
        "and support it with reasoning grounded in the text."
    ),
    BloomLevel.CREATE: (
        "Combine elements into a new, coherent whole or propose an original "
        "solution. Verbs: design, construct, formulate, propose, devise. The "
        "answer synthesises ideas from the source into something new."
    ),
}

# ── Difficulty descriptions ─────────────────────────────────────────

DIFFICULTY_DESCRIPTIONS: dict[Difficulty, str] = {
    Difficulty.EASY: (
        "Answerable directly from a single sentence or definition; minimal "
        "reasoning; obvious distractors for MCQ."
    ),
    Difficulty.MEDIUM: (
        "Requires combining two or more ideas from the passage or a short "
        "chain of reasoning; plausible distractors."
    ),
    Difficulty.HARD: (
        "Requires multi-step reasoning, synthesis, or careful discrimination "
        "between closely related concepts; subtle distractors."
    ),
}

# ── Few-shot examples per Bloom level ───────────────────────────────
#
# Each example is a compact, schema-shaped dict.  They are illustrative
# templates (not tied to any specific source text) that show the model the
# *form* of a question at the given cognitive level.

BLOOM_FEWSHOT: dict[BloomLevel, list[dict]] = {
    BloomLevel.REMEMBER: [
        {
            "qtype": "mcq",
            "difficulty": "easy",
            "stem": "What does the acronym 'AI' stand for?",
            "options": [
                "A) Automated Inference",
                "B) Artificial Intelligence",
                "C) Applied Informatics",
                "D) Algorithmic Iteration",
            ],
            "answer": "B",
            "explanation": "The text introduces AI as the abbreviation for Artificial Intelligence.",
        },
    ],
    BloomLevel.UNDERSTAND: [
        {
            "qtype": "short_answer",
            "difficulty": "medium",
            "stem": "In your own words, explain the difference between a symbolic and a sub-symbolic approach to AI.",
            "options": None,
            "answer": "Symbolic AI manipulates explicit human-readable symbols and rules, whereas sub-symbolic AI learns distributed numerical representations from data.",
            "explanation": "Comprehension is shown by restating the contrast described in the passage.",
        },
    ],
    BloomLevel.APPLY: [
        {
            "qtype": "short_answer",
            "difficulty": "medium",
            "stem": "Given the unification rule from the text, what is the most general unifier of p(X, b) and p(a, Y)?",
            "options": None,
            "answer": "{X = a, Y = b}",
            "explanation": "Applies the unification procedure described in the source to a new pair of terms.",
        },
    ],
    BloomLevel.ANALYZE: [
        {
            "qtype": "short_answer",
            "difficulty": "hard",
            "stem": "Analyse why depth-first search may fail to terminate on the infinite search tree described, while breadth-first search would not.",
            "options": None,
            "answer": "DFS commits to one branch indefinitely, so an infinite leftmost branch traps it; BFS expands level by level and reaches any finite-depth goal.",
            "explanation": "Requires reasoning about the structural difference between the two strategies on the given tree.",
        },
    ],
    BloomLevel.EVALUATE: [
        {
            "qtype": "short_answer",
            "difficulty": "hard",
            "stem": "Evaluate whether the closed-world assumption is appropriate for the knowledge base described, and justify your answer.",
            "options": None,
            "answer": "It is appropriate only if the knowledge base is complete for the domain; otherwise unknown facts are wrongly treated as false, so its suitability depends on completeness.",
            "explanation": "Demands a justified judgement against a stated criterion (completeness).",
        },
    ],
    BloomLevel.CREATE: [
        {
            "qtype": "short_answer",
            "difficulty": "hard",
            "stem": "Using the inference rules introduced in the passage, design a small rule set that derives grandparent(X, Z) from parent facts.",
            "options": None,
            "answer": "grandparent(X, Z) :- parent(X, Y), parent(Y, Z).",
            "explanation": "Synthesises the given rules into a new, coherent rule not present in the text.",
        },
    ],
}


# ── Specification objects & planning ────────────────────────────────


@dataclass(frozen=True)
class QuestionSpec:
    """A request for one question at a specific cognitive level / difficulty.

    ``qtype`` is optional: ``None`` lets the model pick an appropriate format.
    """

    bloom_level: BloomLevel
    difficulty: Difficulty
    qtype: QuestionType | None = None


def build_difficulty_plan(
    total: int,
    mix: dict[str, float] | dict[Difficulty, float] | None = None,
) -> dict[Difficulty, int]:
    """Turn a target difficulty *mix* (fractions) into integer counts.

    The largest-remainder method is used so the counts always sum to *total*
    exactly, even when the fractions don't divide evenly.

    Parameters
    ----------
    total
        Total number of questions to distribute.
    mix
        Mapping difficulty → fraction (need not sum to exactly 1.0; it is
        normalised). Defaults to a 40 / 40 / 20 easy/medium/hard spread.
    """
    if mix is None:
        mix = {Difficulty.EASY: 0.4, Difficulty.MEDIUM: 0.4, Difficulty.HARD: 0.2}

    # Normalise keys to Difficulty enums and drop non-positive weights.
    norm: dict[Difficulty, float] = {}
    for key, frac in mix.items():
        diff = key if isinstance(key, Difficulty) else Difficulty(str(key))
        if frac > 0:
            norm[diff] = float(frac)

    weight_sum = sum(norm.values()) or 1.0
    return _largest_remainder({d: w / weight_sum for d, w in norm.items()}, total)


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


def build_balanced_plan(
    total: int,
    bloom_levels: list[BloomLevel] | None = None,
    difficulty_mix: dict[str, float] | None = None,
    qtypes: list[QuestionType] | None = None,
) -> list[QuestionSpec]:
    """Build an ordered list of :class:`QuestionSpec` for a chapter.

    Questions are spread as evenly as possible across *bloom_levels*, and
    within the whole set the difficulty distribution matches *difficulty_mix*
    (via :func:`build_difficulty_plan`).  ``qtype`` is cycled through
    *qtypes* when provided, otherwise left to the model.

    Example
    -------
    A 12-question set across all six Bloom levels with a 40/40/20 spread:

    >>> specs = build_balanced_plan(12)
    >>> len(specs)
    12
    """
    if bloom_levels is None:
        bloom_levels = list(BloomLevel)

    # 1. How many questions per Bloom level (largest-remainder, even split).
    per_bloom = _largest_remainder(
        {b: 1 / len(bloom_levels) for b in bloom_levels}, total
    )

    # 2. Global difficulty counts to draw from as we fill each Bloom slot.
    diff_pool = build_difficulty_plan(total, difficulty_mix)
    diff_sequence: list[Difficulty] = []
    for diff in (Difficulty.EASY, Difficulty.MEDIUM, Difficulty.HARD):
        diff_sequence.extend([diff] * diff_pool.get(diff, 0))

    # 3. Assemble specs, drawing difficulties round-robin from the pool.
    specs: list[QuestionSpec] = []
    di = 0
    qi = 0
    for bloom in bloom_levels:
        for _ in range(per_bloom.get(bloom, 0)):
            difficulty = diff_sequence[di] if di < len(diff_sequence) else Difficulty.MEDIUM
            di += 1
            qtype = None
            if qtypes:
                qtype = qtypes[qi % len(qtypes)]
                qi += 1
            specs.append(QuestionSpec(bloom_level=bloom, difficulty=difficulty, qtype=qtype))

    return specs


def render_fewshot(bloom_level: BloomLevel, max_examples: int = 2) -> str:
    """Render the few-shot example(s) for a Bloom level as a prompt fragment."""
    import json

    examples = BLOOM_FEWSHOT.get(bloom_level, [])[:max_examples]
    if not examples:
        return ""
    lines = [f"Example question(s) at the '{bloom_level.value}' level:"]
    for ex in examples:
        lines.append(json.dumps(ex, ensure_ascii=False))
    return "\n".join(lines)
