"""Structural/boundary validation of LLM output (M3, ADR 4).

Earlier named ``DraftValidator``; renamed to ``DraftResponseValidator`` to make
clear it validates the typed ``DraftResponse`` at the application/infrastructure
boundary, distinct from domain business rules (``DraftPolicy``). It runs BEFORE
any ``EmailDraft`` is created (llm_output_validated invariant).

Field *types* are guaranteed by the ``DraftResponse`` pydantic model at
construction, so this validator concerns itself only with semantic/presence
rules: a final (non-clarification) draft must carry recipients + subject + body,
and recipient entries must be non-empty. Strict email-shape validation belongs
to the domain ``Recipient`` value object, not here.
"""

from __future__ import annotations

from .draft_response import DraftResponse
from .errors import DraftResponseValidationError


class DraftResponseValidator:
    """Validates a DraftResponse before it becomes an EmailDraft."""

    def validate(self, response: DraftResponse) -> None:
        """Raise ``DraftResponseValidationError`` if the response is unusable."""
        for recipient in response.recipients:
            if not recipient.strip():
                raise DraftResponseValidationError("each recipient must be a non-empty string")
        if not response.clarification_required and (
            not response.recipients or not response.subject.strip() or not response.body.strip()
        ):
            raise DraftResponseValidationError(
                "a final draft must contain recipients, subject, and body; "
                "set clarification_required=true when information is missing"
            )
