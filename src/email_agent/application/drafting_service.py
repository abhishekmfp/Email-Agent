"""Application layer for the drafting workflow (M3+).

The application layer owns orchestration: it drives the LLM adapter, validates
the boundary output, and constructs domain objects. It contains no business
rules of its own — those live in the domain layer (e.g. ``DraftPolicy``).

The application layer depends inward on the domain and infrastructure layers;
it is depended on by the interface layer. It must never be imported by the
domain or infrastructure layers (domain_inward invariant).
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

from email_agent.domain.email_draft import EmailDraft
from email_agent.domain.recipient import Recipient
from email_agent.infrastructure.errors import (
    AnthropicProviderError,
    DraftResponseValidationError,
)

from .draft_request import DraftRequest, DraftResult, DraftStatus

if TYPE_CHECKING:  # dependencies are injected; only their types are referenced here.
    from email_agent.infrastructure.anthropic_adapter import AnthropicAdapter
    from email_agent.infrastructure.draft_response import DraftResponse
    from email_agent.infrastructure.draft_response_validator import DraftResponseValidator
    from email_agent.infrastructure.prompt_builder import PromptBuilder


@dataclass(frozen=True)
class _RetryPolicy:
    """Conservative exponential backoff for transient provider failures (ADR 5).

    Retry lives here in the application service, not in the adapter. M3 retries
    only transient ``AnthropicProviderError``s (transport/timeout); schema or
    validation failures are surfaced immediately.
    """

    max_attempts: int = 3
    backoff_seconds: float = 0.5


class DraftingService:
    """Coordinates request -> LLM -> validate -> EmailDraft in AWAIT_APPROVAL."""

    def __init__(
        self,
        adapter: AnthropicAdapter,
        validator: DraftResponseValidator,
        prompt_builder: PromptBuilder,
        *,
        max_attempts: int = 3,
        backoff_seconds: float = 0.5,
    ) -> None:
        self._adapter = adapter
        self._validator = validator
        self._prompt_builder = prompt_builder
        self._retry = _RetryPolicy(max_attempts=max_attempts, backoff_seconds=backoff_seconds)

    def draft(self, request: DraftRequest) -> DraftResult:
        """Produce a validated draft and return a preview result.

        No send occurs. On success the returned ``EmailDraft`` is in the
        AWAITING_APPROVAL state. Repeated transient provider failures surface a
        structured error rather than looping forever.
        """
        prompt = self._prompt_builder.build(request.user_request, user_name=request.user_name)

        last_error: AnthropicProviderError | None = None
        for attempt in range(1, self._retry.max_attempts + 1):
            try:
                response = self._adapter.generate_draft(prompt)
                break
            except AnthropicProviderError as exc:
                last_error = exc
                if attempt >= self._retry.max_attempts:
                    break
                time.sleep(self._retry.backoff_seconds * attempt)  # conservative backoff

        if last_error is not None:
            return DraftResult(
                status=DraftStatus.ERROR,
                error=(
                    f"Draft generation failed after "
                    f"{self._retry.max_attempts} attempts: {last_error}"
                ),
            )

        try:
            self._validator.validate(response)
        except DraftResponseValidationError as exc:
            # Boundary validation failure (malformed LLM output past schema
            # coercion) → surface as an app error, never crash the workflow.
            return DraftResult(
                status=DraftStatus.ERROR,
                error=f"LLM output failed validation: {exc}",
            )

        if response.clarification_required:
            return DraftResult(
                status=DraftStatus.CLARIFICATION_REQUIRED,
                draft=None,
                clarification_question=_build_clarification_prompt(response),
                missing_fields=list(response.missing_fields),
            )

        recipients = [Recipient(email=email) for email in response.recipients]
        draft = EmailDraft.create(
            recipients=recipients,
            subject=response.subject,
            body=response.body,
            tone=response.tone,
            purpose=response.purpose,
        ).submit_for_approval()
        return DraftResult(status=DraftStatus.SUCCESS, draft=draft)


def _build_clarification_prompt(response: DraftResponse) -> str:
    missing = ", ".join(response.missing_fields) or "recipient details"
    return f"I need a bit more information before I can draft this email: {missing}."
