"""Anthropic LLM adapter (M3).

Concrete provider adapter behind a narrow port used by the application layer.
Per the locked architecture and the M3 design decisions it:

  * returns only a typed ``DraftResponse`` (never raw dicts) — ADR 3;
  * performs exactly ONE request per call; retry belongs to DraftingService — ADR 5;
  * sets an explicit timeout (outbound_timeout invariant);
  * performs NO validation — that is DraftResponseValidator's job (llmops gate);
  * is constructed with the api_key and never logs it (secrets_hygiene invariant).
"""

from __future__ import annotations

import json
from typing import Any

from anthropic import Anthropic, APIError

from .draft_response import DraftResponse
from .errors import AnthropicProviderError
from .prompt_builder import DraftPrompt


def _extract_text(response: Any) -> str:
    """Concatenate text blocks from an Anthropic Messages response."""
    parts: list[str] = []
    for block in getattr(response, "content", []) or []:
        text = getattr(block, "text", None)
        if text:
            parts.append(text)
    return "".join(parts)


def _strip_code_fences(text: str) -> str:
    """Best-effort strip of markdown code fences around a JSON payload."""
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    without_open = stripped.split("\n", 1)[1] if "\n" in stripped else ""
    return without_open.rsplit("```", 1)[0].strip()


class AnthropicAdapter:
    """Talks to the Anthropic Messages API and returns a typed DraftResponse."""

    def __init__(
        self,
        api_key: str,
        model: str,
        timeout_seconds: float,
        *,
        client: Anthropic | None = None,
        max_tokens: int = 2048,
    ) -> None:
        self._model = model
        self._timeout = timeout_seconds
        self._max_tokens = max_tokens
        self._client = client or Anthropic(api_key=api_key, timeout=timeout_seconds)

    def generate_draft(self, prompt: DraftPrompt) -> DraftResponse:
        """Make exactly one request and return a typed DraftResponse.

        Transport/timeout/API failures and unparseable or schema-mismatched
        output are raised as ``AnthropicProviderError``; the retry policy and
        the boundary validator live elsewhere.
        """
        try:
            response = self._client.messages.create(
                model=self._model,
                max_tokens=self._max_tokens,
                system=prompt.system,
                messages=[{"role": "user", "content": prompt.user_request}],
                timeout=self._timeout,
            )
        except APIError as exc:
            raise AnthropicProviderError(f"Anthropic API call failed: {exc}") from exc

        text = _extract_text(response)
        try:
            data = json.loads(_strip_code_fences(text))
        except json.JSONDecodeError as exc:
            raise AnthropicProviderError(f"LLM output was not valid JSON: {exc}") from exc

        try:
            return DraftResponse.model_validate(data)
        except Exception as exc:  # pydantic ValidationError and friends
            raise AnthropicProviderError(
                f"LLM output did not match the draft schema: {exc}"
            ) from exc
