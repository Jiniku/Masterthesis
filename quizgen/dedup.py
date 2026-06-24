"""Pool deduplication (Phase 5).

Near-duplicate questions waste blueprint slots and make parallel exam versions
predictable.  This module removes them from a pool *before* assembly using the
shared :mod:`quizgen.similarity` backend: embedding cosine similarity when a
sentence-transformers encoder is available, falling back to token-Jaccard
offline.  It keeps the first occurrence of each near-duplicate group and
reports how many were dropped.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from quizgen.schema import Question
from quizgen.similarity import find_near_duplicate_pairs

logger = logging.getLogger(__name__)


@dataclass
class DedupResult:
    """Outcome of a deduplication pass."""

    kept: list[Question]
    removed: list[Question]
    threshold: float
    method: str
    duplicate_pairs: list[tuple[str, str]] = field(default_factory=list)

    @property
    def n_removed(self) -> int:
        return len(self.removed)

    @property
    def n_kept(self) -> int:
        return len(self.kept)


def load_encoder(model_name: str | None = None):
    """Return a sentence-transformers encoder, or ``None`` if unavailable.

    The encoder download/load can fail on an offline machine; callers then
    transparently fall back to the lexical similarity backend.
    """
    try:
        from sentence_transformers import SentenceTransformer

        from quizgen.config import settings

        return SentenceTransformer(model_name or settings.embedding_model)
    except Exception as exc:  # offline, missing dep, etc.
        logger.warning("Embedding encoder unavailable (%s); using token similarity.", exc)
        return None


def deduplicate(
    questions: list[Question],
    threshold: float = 0.9,
    encoder=None,
    use_embeddings: bool = True,
) -> DedupResult:
    """Drop near-duplicate questions, keeping the first of each group.

    Parameters
    ----------
    questions
        The candidate pool.
    threshold
        Similarity at/above which two questions are deemed duplicates.
    encoder
        A pre-loaded sentence-transformers encoder. If ``None`` and
        *use_embeddings* is True, one is loaded lazily (may fall back).
    use_embeddings
        Set False to force the offline token-Jaccard backend.
    """
    if use_embeddings and encoder is None:
        encoder = load_encoder()
    method = "embedding" if encoder is not None else "token"

    pairs = find_near_duplicate_pairs(questions, threshold, encoder)

    # Greedily drop the later index of every duplicate pair.
    drop: set[int] = set()
    duplicate_pairs: list[tuple[str, str]] = []
    for i, j in pairs:
        if i in drop:
            continue
        drop.add(j)
        duplicate_pairs.append((questions[i].id, questions[j].id))

    kept = [q for idx, q in enumerate(questions) if idx not in drop]
    removed = [q for idx, q in enumerate(questions) if idx in drop]

    logger.info(
        "Deduplication (%s, t=%.2f): removed %d of %d, %d remain",
        method, threshold, len(removed), len(questions), len(kept),
    )
    return DedupResult(
        kept=kept, removed=removed, threshold=threshold,
        method=method, duplicate_pairs=duplicate_pairs,
    )
