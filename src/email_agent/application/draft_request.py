"""Application-layer request/result types for the drafting workflow (M3).

Plain dataclasses (no provider or domain coupling) describing what the user
asked for and what the use case produced. The domain ``EmailDraft`` only appears
inside ``DraftResult`` once it has been constructed by ``DraftingService``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from email_agent.domain.draft_state import DraftState
from email_agent.domain.email_draft import EmailDraft


class DraftStatus(StrEnum):
    """Outcome of a draft request."""

    SUCCESS = "SUCCESS"
    CLARIFICATION_REQUIRED = "CLARIFICATION_REQUIRED"
    ERROR = "ERROR"


@dataclass(frozen=True)
class DraftRequest:
    """A user's natural-language draft request."""

    user_request: str
    user_name: str | None = None


@dataclass
class DraftResult:
    """The outcome of a draft request, ready for the interface layer."""

    status: DraftStatus
    draft: EmailDraft | None = None
    clarification_question: str | None = None
    missing_fields: list[str] = field(default_factory=list)
    error: str | None = None

    @property
    def preview(self) -> str | None:
        """A human-readable preview string, or None when nothing is approvable."""
        if self.draft is None or self.draft.state is not DraftState.AWAITING_APPROVAL:
            return None
        lines = [f"To: {', '.join(r.email for r in self.draft.recipients)}"]
        if self.draft.tone:
            lines.append(f"Tone: {self.draft.tone}")
        lines.append(f"Subject: {self.draft.subject}")
        lines.append("")
        lines.append(self.draft.body)
        return "\n".join(lines)
