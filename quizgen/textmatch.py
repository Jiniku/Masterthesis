"""Lightweight lexical helpers shared across the pipeline.

Kept dependency-free (stdlib only) so modules like :mod:`quizgen.validate` can
use content-word overlap without pulling in the optional embeddings stack
(sentence-transformers).
"""

from __future__ import annotations

import re

_STOPWORDS = {
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "can", "shall", "not", "and", "but", "or",
    "if", "then", "else", "when", "where", "how", "what", "which", "who",
    "that", "this", "these", "those", "with", "from", "for", "in", "on",
    "at", "to", "of", "by", "as", "it", "its", "they", "them", "their",
    "we", "our", "you", "your", "he", "she", "his", "her",
}


def extract_content_words(text: str) -> set[str]:
    """Lowercased words of 3+ chars with stopwords removed."""
    words = set(re.findall(r"\b[a-z]{3,}\b", text.lower()))
    return words - _STOPWORDS
