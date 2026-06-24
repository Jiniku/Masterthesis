"""Phase 5 tests — LLM-as-judge evaluation."""

from __future__ import annotations

from quizgen.judge import Judgement, judge_questions, judge_summary
from quizgen.mock_client import MockLLMClient
from quizgen.schema import BloomLevel, Difficulty, Question, QuestionType


def _q(qid: str) -> Question:
    return Question(
        id=qid, chapter=1, section="1.1", qtype=QuestionType.MCQ,
        bloom_level=BloomLevel.APPLY, difficulty=Difficulty.MEDIUM,
        stem=f"Apply the rule to case {qid} and choose the result.",
        options=["A) one", "B) two", "C) three", "D) four"],
        answer="A", explanation="Explanation long enough for validation.",
        source_ref="ch1_chunk_001",
    )


def test_judge_rates_all_questions():
    questions = [_q("a"), _q("b"), _q("c")]
    judgements = judge_questions(questions, client=MockLLMClient())
    assert len(judgements) == 3
    assert {j.question_id for j in judgements} == {"a", "b", "c"}
    for j in judgements:
        assert 1 <= j.answerability <= 5


def test_summary_aggregates():
    questions = [_q("a"), _q("b")]
    judgements = judge_questions(questions, client=MockLLMClient())
    summary = judge_summary(judgements)
    assert summary["n"] == 2
    assert set(summary["mean"]) == {"answerability", "correctness", "clarity", "bloom_match"}
    assert 0 <= summary["mean_overall"] <= 5


def test_flagging_threshold_logic():
    # min_score below threshold -> flagged.
    j = Judgement("x", answerability=2, correctness=5, clarity=5, bloom_match=5)
    j.flagged = j.min_score < 3.0
    assert j.flagged is True

    good = Judgement("y", answerability=4, correctness=4, clarity=5, bloom_match=4)
    good.flagged = good.min_score < 3.0
    assert good.flagged is False


def test_unrated_questions_are_flagged():
    # Empty messages won't match the judge regex -> a bare client returns nothing.
    class _Empty(MockLLMClient):
        def chat_json(self, messages, **kw):
            return {"ratings": []}

    judgements = judge_questions([_q("a")], client=_Empty())
    assert len(judgements) == 1
    assert judgements[0].flagged
    assert "not rated" in judgements[0].comment
