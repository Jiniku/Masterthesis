"""Application-wide configuration loaded from environment / ``.env``.

All LLM provider settings live here.  Switching from GLM-5.2 to a local
Ollama model (or OpenAI, etc.) is a matter of editing ``.env`` — no code
changes required.
"""

from __future__ import annotations

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Reads configuration from environment variables / ``.env`` file."""

    # ── LLM provider ────────────────────────────────────────────────
    llm_base_url: str = "http://localhost:11434/v1"
    llm_api_key: str = "ollama"
    llm_model: str = "qwen2.5:14b"

    # ── Embedding (Phase 2+) ────────────────────────────────────────
    embedding_model: str = "all-MiniLM-L6-v2"

    # ── Generation defaults ─────────────────────────────────────────
    default_per_chunk: int = 2
    default_temperature: float = 0.7

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }


# Singleton — import ``settings`` wherever needed.
settings = Settings()
