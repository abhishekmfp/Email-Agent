"""Infrastructure-layer errors for the Anthropic drafting path (M3).

These are raised by adapter/validator code and carry no domain semantics. The
application layer catches them to decide how to respond (retry, surface error).
"""

from __future__ import annotations


class AnthropicProviderError(Exception):
    """The Anthropic API call failed (transport, timeout, or unparseable output)."""


class DraftResponseValidationError(Exception):
    """The LLM output failed structural/boundary validation before EmailDraft creation."""
