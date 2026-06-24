"""Application configuration loaded from environment / ``.env``.

The selection-only pipeline has a single optional knob: the embedding model
used for *semantic* near-duplicate detection (``quizgen.dedup``). Everything
else works with no configuration. If sentence-transformers isn't installed,
dedup transparently falls back to a lexical (token-Jaccard) measure and this
setting is never read.
"""

from __future__ import annotations

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Reads configuration from environment variables / ``.env`` file."""

    # Embedding model for optional semantic deduplication.
    embedding_model: str = "all-MiniLM-L6-v2"

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }


# Singleton — import ``settings`` wherever needed.
settings = Settings()
