"""LLM-as-judge evaluation pass (Phase 5, optional).

A *separate* model call rates each generated question on four criteria —
answerability, correctness of the keyed answer, clarity, and how well it
matches its intended Bloom level — on a 1–5 scale, and flags any item scoring
below a threshold for human review.

This is deliberately isolated from generation (:mod:`quizgen.generate`): it
consumes finished questions and never writes them, so the "generate" and
"judge" responsibilities stay cleanly separable in the thesis pipeline.  It is
opt-in; nothing else in the pipeline depends on it.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass

from quizgen.llm_client import LLMClient
from quizgen.schema import Question

logger = logging.getLogger(__name__)

CRITERIA = ("answerability", "correctness", "clarity", "bloom_match")

JUDGE_SYSTEM = """\
You are a meticulous exam-quality reviewer. You rate existing exam questions;
you do NOT rewrite them. For each question you are given its intended Bloom
level and keyed answer. Rate strictly and honestly.
"""

JUDGE_USER_TEMPLATE = """\
## JUDGE RUBRIC
Rate each question from 1 (poor) to 5 (excellent) on:
- answerability: can a student actually answer it as written?
- correctness: is the keyed answer correct and unambiguous?
- clarity: is the wording clear and unambiguous?
- bloom_match: does it genuinely exercise its intended Bloom level?

Questions to review:
{items}

Respond with JSON only:
{{"ratings": [
  {{"id": "<id>", "answerability": n, "correctness": n, "clarity": n,
    "bloom_match": n, "comment": "<short note>"}}
]}}
"""


@dataclass
class Judgement:
    """One question's quality ratings."""

    question_id: str
    answerability: int
    correctness: int
    clarity: int
    bloom_match: int
    comment: str = ""
    flagged: bool = False

    @property
    def min_score(self) -> int:
        return min(self.answerability, self.correctness, self.clarity, self.bloom_match)

    @property
    def mean_score(self) -> float:
        return (
            self.answerability + self.correctness + self.clarity + self.bloom_match
        ) / 4.0

    def to_dict(self) -> dict:
        return asdict(self)


def _format_items(batch: list[Question]) -> str:
    lines = []
    for q in batch:
        opts = f" options={q.options}" if q.options else ""
        lines.append(
            f"#JUDGE {q.id} | bloom={q.bloom_level.value} | qtype={q.qtype.value}\n"
            f"  stem: {q.stem}{opts}\n"
            f"  keyed answer: {q.answer}"
        )
    return "\n".join(lines)


def judge_questions(
    questions: list[Question],
    client: LLMClient | None = None,
    *,
    threshold: float = 3.0,
    batch_size: int = 8,
) -> list[Judgement]:
    """Rate every question and flag those scoring below *threshold*.

    A question is flagged when its *minimum* criterion score is below
    *threshold* (any single weak dimension warrants human review).
    """
    if client is None:
        client = LLMClient()

    by_id = {q.id: q for q in questions}
    judgements: list[Judgement] = []

    for start in range(0, len(questions), batch_size):
        batch = questions[start : start + batch_size]
        messages = [
            {"role": "system", "content": JUDGE_SYSTEM},
            {"role": "user", "content": JUDGE_USER_TEMPLATE.format(items=_format_items(batch))},
        ]
        try:
            data = client.chat_json(messages, temperature=0.0, max_tokens=2048)
            ratings = data.get("ratings", []) if isinstance(data, dict) else data
        except Exception as e:  # pragma: no cover - network/parse failure
            logger.warning("Judge call failed for batch at %d: %s", start, e)
            ratings = []

        seen: set[str] = set()
        for r in ratings:
            if not isinstance(r, dict) or r.get("id") not in by_id:
                continue
            j = _to_judgement(r, threshold)
            judgements.append(j)
            seen.add(j.question_id)

        # Any unrated question in the batch is flagged for review.
        for q in batch:
            if q.id not in seen:
                judgements.append(
                    Judgement(q.id, 0, 0, 0, 0, comment="not rated by judge", flagged=True)
                )

    return judgements


def _to_judgement(r: dict, threshold: float) -> Judgement:
    def score(key: str) -> int:
        try:
            return max(1, min(5, int(r.get(key, 0))))
        except (TypeError, ValueError):
            return 0

    j = Judgement(
        question_id=r["id"],
        answerability=score("answerability"),
        correctness=score("correctness"),
        clarity=score("clarity"),
        bloom_match=score("bloom_match"),
        comment=str(r.get("comment", "")),
    )
    j.flagged = j.min_score < threshold
    return j


def judge_summary(judgements: list[Judgement]) -> dict:
    """Aggregate judgements into a small summary dict."""
    n = len(judgements)
    if not n:
        return {"n": 0, "flagged": 0, "flagged_ids": [], "mean": {}}
    flagged = [j for j in judgements if j.flagged]
    mean = {
        c: round(sum(getattr(j, c) for j in judgements) / n, 2) for c in CRITERIA
    }
    return {
        "n": n,
        "flagged": len(flagged),
        "flagged_ids": [j.question_id for j in flagged],
        "mean": mean,
        "mean_overall": round(sum(j.mean_score for j in judgements) / n, 2),
    }
