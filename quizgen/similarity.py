"""Question similarity helpers shared by assembly (Phase 4) and dedup (Phase 5).

Two backends are provided behind one API:

* a dependency-free **token-Jaccard** similarity over the stem (+answer),
  always available and used as the default/fallback, and
* an optional **embedding cosine** similarity using the sentence-transformers
  encoder already loaded for RAG, which catches paraphrases the lexical
  measure misses.

:func:`find_near_duplicate_pairs` returns index pairs above a threshold so the
assembler can forbid them across parallel exam versions and the dedup pass can
drop them from the pool.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from quizgen.schema import Question

_TOKEN_RE = re.compile(r"\b[a-z0-9]{2,}\b")


def _tokens(text: str) -> set[str]:
    return set(_TOKEN_RE.findall(text.lower()))


def question_text(q: "Question") -> str:
    """Canonical text used for similarity: stem + answer (+ options for MCQ)."""
    parts = [q.stem, q.answer]
    if q.options:
        parts.extend(q.options)
    return " ".join(parts)


def jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


def text_similarity(q1: "Question", q2: "Question") -> float:
    """Token-Jaccard similarity between two questions (0–1)."""
    return jaccard(_tokens(question_text(q1)), _tokens(question_text(q2)))


def _embedding_pairs(
    questions: list["Question"], threshold: float, encoder
) -> list[tuple[int, int]]:
    """Cosine-similarity duplicate pairs using a sentence-transformers encoder."""
    import numpy as np

    texts = [question_text(q) for q in questions]
    vecs = np.asarray(encoder.encode(texts, show_progress_bar=False), dtype="float32")
    norms = np.linalg.norm(vecs, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    unit = vecs / norms
    sim = unit @ unit.T

    pairs: list[tuple[int, int]] = []
    n = len(questions)
    for i in range(n):
        for j in range(i + 1, n):
            if sim[i, j] >= threshold:
                pairs.append((i, j))
    return pairs


def find_near_duplicate_pairs(
    questions: list["Question"],
    threshold: float = 0.85,
    encoder=None,
) -> list[tuple[int, int]]:
    """Return index pairs ``(i, j)`` whose similarity is ``>= threshold``.

    Uses embedding cosine similarity when *encoder* is given, otherwise falls
    back to token-Jaccard.  Pairs are over the list indices, ``i < j``.
    """
    if encoder is not None:
        try:
            return _embedding_pairs(questions, threshold, encoder)
        except Exception:  # pragma: no cover - fall back if embeddings fail
            pass

    pairs: list[tuple[int, int]] = []
    toks = [_tokens(question_text(q)) for q in questions]
    n = len(questions)
    for i in range(n):
        for j in range(i + 1, n):
            if jaccard(toks[i], toks[j]) >= threshold:
                pairs.append((i, j))
    return pairs
