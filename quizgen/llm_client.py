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

    def chat_schema(
        self,
        messages: list[dict[str, str]],
        json_schema: dict[str, Any],
        *,
        schema_name: str = "response",
        temperature: float | None = None,
        max_tokens: int = 4096,
        **kwargs: Any,
    ) -> dict | list:
        """Force the model to emit JSON conforming to *json_schema*.

        This is the Phase 3 "guaranteed-valid JSON" entry point.  The
        ``structured_output_mode`` setting selects the strategy, so the rest
        of the codebase never branches on provider:

        ``json_schema``
            OpenAI/GLM strict structured-output mode — the provider enforces
            the schema during decoding (``response_format`` with a
            ``json_schema`` block).
        ``outlines``
            Local constrained decoding via the Outlines library, which masks
            logits so only schema-valid tokens can be sampled.  Used for
            self-hosted models that lack a strict API mode.
        ``json_object`` / fall-back
            Loose JSON mode; validity of the *container* is still enforced by
            the caller's Pydantic pass.

        Schema validity guarantees the JSON *shape*, never the *facts* — the
        grounding/validation steps remain mandatory regardless of mode.
        """
        mode = settings.structured_output_mode

        if mode == "outlines":
            return self._chat_outlines(
                messages, json_schema, temperature=temperature,
                max_tokens=max_tokens, **kwargs,
            )

        if mode in ("auto", "json_schema"):
            try:
                raw = self.chat(
                    messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    response_format={
                        "type": "json_schema",
                        "json_schema": {
                            "name": schema_name,
                            "schema": json_schema,
                            "strict": True,
                        },
                    },
                    **kwargs,
                )
                return json.loads(self._strip_markdown_fences(raw))
            except Exception as exc:
                if mode == "json_schema":
                    raise
                logger.warning(
                    "Strict json_schema mode unavailable (%s); "
                    "falling back to json_object mode.", exc,
                )

        # json_object mode (explicit, or fall-through from auto)
        return self.chat_json(
            messages, temperature=temperature, max_tokens=max_tokens, **kwargs,
        )

    def _chat_outlines(
        self,
        messages: list[dict[str, str]],
        json_schema: dict[str, Any],
        *,
        temperature: float | None,
        max_tokens: int,
        **kwargs: Any,
    ) -> dict | list:
        """Constrained decoding via Outlines against a self-hosted model.

        Outlines is an optional dependency; importing it lazily keeps it out
        of the critical path for API users.  Outlines drives the *local* model
        directly, so the OpenAI-compatible endpoint is bypassed here.
        """
        try:
            import outlines  # noqa: F401
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise RuntimeError(
                "structured_output_mode='outlines' requires the 'outlines' "
                "package and a local model. Install with: pip install outlines"
            ) from exc

        # Outlines integration is model-specific (it loads weights locally
        # rather than calling an HTTP endpoint). The hook is intentionally
        # explicit so a self-hoster can wire in their transformers/vLLM model.
        raise NotImplementedError(  # pragma: no cover
            "Wire a local Outlines model here for constrained decoding. The "
            "JSON schema is available as `json_schema`."
        )

    def chat_structured(
        self,
        messages: list[dict[str, str]],
        response_model: type,
        *,
        temperature: float | None = None,
        max_tokens: int = 4096,
        **kwargs: Any,
    ) -> Any:
        """Request schema-constrained JSON and validate it against *response_model*.

        Combines :meth:`chat_schema` (forces the JSON shape) with a Pydantic
        validation pass (enforces the model's own constraints), returning the
        validated Pydantic instance.
        """
        data = self.chat_schema(
            messages,
            response_model.model_json_schema(),
            schema_name=response_model.__name__,
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs,
        )
        return response_model.model_validate(data)

    def __repr__(self) -> str:
        return f"LLMClient(model={self.model!r}, base_url={self.base_url!r})"
