"""Infrastructure adapters and boundary validators (M3+).

Concrete provider adapters live here, behind narrow ports used by the
application layer. Nothing in this package imports the domain layer or any
framework — the dependency direction is strictly inward (domain_inward).
"""

from __future__ import annotations

from .anthropic_adapter import AnthropicAdapter
from .draft_response import DraftResponse
from .draft_response_validator import DraftResponseValidator
from .errors import AnthropicProviderError, DraftResponseValidationError
from .prompt_builder import DraftPrompt, PromptBuilder

__all__ = [
    "AnthropicAdapter",
    "AnthropicProviderError",
    "DraftPrompt",
    "DraftResponse",
    "DraftResponseValidationError",
    "DraftResponseValidator",
    "PromptBuilder",
]
