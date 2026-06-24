"""Swappable LLM client wrapping any OpenAI-compatible chat-completions API.

The rest of the codebase calls ``LLMClient.chat()`` and never worries about
which provider is behind it.  Switching providers means editing ``.env``,
nothing else.

Design notes
------------
* The client uses the official ``openai`` Python SDK in "custom base_url" mode,
  which works with GLM-5.2 (Z.ai), Ollama, vLLM, and any other provider that
  exposes the ``/v1/chat/completions`` endpoint.
* ``chat()`` returns the raw assistant message content (str).
* ``chat_json()`` adds ``response_format={"type": "json_object"}`` and parses
  the response into a Python dict — used by the generator to get structured
  output.
* Temperature, max_tokens, and any extra kwargs are forwarded so callers
  retain full control when needed.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from openai import OpenAI

from quizgen.config import settings

logger = logging.getLogger(__name__)


class LLMClient:
    """Thin wrapper around an OpenAI-compatible chat-completions endpoint.

    Parameters
    ----------
    base_url, api_key, model
        Override the values from ``.env`` / ``Settings`` for testing or
        multi-model evaluation.
    """

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
    ) -> None:
        self.base_url = base_url or settings.llm_base_url
        self.api_key = api_key or settings.llm_api_key
        self.model = model or settings.llm_model

        self._client = OpenAI(
            base_url=self.base_url,
            api_key=self.api_key,
        )
        logger.info("LLMClient initialised — model=%s base_url=%s", self.model, self.base_url)

    # ── public API ──────────────────────────────────────────────────

    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float | None = None,
        max_tokens: int = 2048,
        **kwargs: Any,
    ) -> str:
        """Send a chat-completion request and return the assistant's reply.

        Parameters
        ----------
        messages
            OpenAI-style message list, e.g.
            ``[{"role": "system", "content": "…"}, {"role": "user", "content": "…"}]``
        temperature
            Sampling temperature.  ``None`` → use provider default.
        max_tokens
            Maximum tokens in the response.
        **kwargs
            Forwarded to the API (e.g. ``top_p``, ``stop``).
        """
        if temperature is None:
            temperature = settings.default_temperature

        response = self._client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs,
        )
        content = response.choices[0].message.content or ""
        logger.debug("LLM response (%d chars): %.200s…", len(content), content)
        return content

    @staticmethod
    def _strip_markdown_fences(raw: str) -> str:
        """Remove markdown code fences that some models wrap around JSON."""
        text = raw.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
            text = text.rsplit("```", 1)[0]
        return text.strip()

    def chat_json(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float | None = None,
        max_tokens: int = 4096,
        **kwargs: Any,
    ) -> dict | list:
        """Like :meth:`chat` but forces JSON output and parses the result.

        Raises
        ------
        json.JSONDecodeError
            If the model returns text that isn't valid JSON despite the
            ``response_format`` hint.
        """
        try:
            raw = self.chat(
                messages,
                temperature=temperature,
                max_tokens=max_tokens,
                response_format={"type": "json_object"},
                **kwargs,
            )
        except Exception:
            logger.warning("JSON mode not supported by endpoint, falling back to raw text.")
            raw = self.chat(
                messages,
                temperature=temperature,
                max_tokens=max_tokens,
                **kwargs,
            )
        return json.loads(self._strip_markdown_fences(raw))

    def chat_structured(
        self,
        messages: list[dict[str, str]],
        response_model: type,
        *,
        temperature: float | None = None,
        max_tokens: int = 4096,
        **kwargs: Any,
    ) -> Any:
        """Request JSON and validate it against a Pydantic model.

        Returns the validated Pydantic model instance.  In Phase 3 this
        will integrate constrained decoding for local models; for now it
        wraps ``chat_json`` + Pydantic validation.
        """
        data = self.chat_json(
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs,
        )
        return response_model.model_validate(data)

    def __repr__(self) -> str:
        return f"LLMClient(model={self.model!r}, base_url={self.base_url!r})"
