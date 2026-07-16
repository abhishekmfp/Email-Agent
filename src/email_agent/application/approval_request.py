"""Application-layer command/result types for the approval workflow (M4).

Parallel to ``draft_request.py`` in M3: plain frozen dataclasses with no domain
or provider coupling.

Distinction (important):
- ``Approval`` (domain value object) = the *fact* that a human approved, carrying
  ``approver`` + ``decided_at``.
- ``ApprovalDecision`` (application command) = the human's *choice* plus any edit
  payload. It is what ``ApproveEmailUseCase.execute`` consumes.

Per the M4 design decision D4, V1 keeps a single ``ApprovalDecision`` dataclass
with optional fields rather than a discriminated union of command objects.
Evolution toward explicit command classes is a candidate future ADR if command
complexity grows.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

from email_agent.domain.email_draft import EmailDraft
from email_agent.domain.email_message import EmailMessage
from email_agent.domain.recipient import Recipient


class ApprovalStatus(StrEnum):
    """Outcome of an approval decision."""

    APPROVED = "APPROVED"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    REJECTED = "REJECTED"
    ERROR = "ERROR"


@dataclass(frozen=True)
class ApprovalDecision:
    """A human's decision about an AWAITING_APPROVAL draft.

    ``decision`` selects the action. ``approver`` is required iff
    ``decision == "approve"``. The remaining fields are the optional edit
    payload — only the fields provided are applied by the domain ``edit``
    method; ``None`` means "leave unchanged".
    """

    decision: Literal["approve", "edit", "reject"]
    approver: str | None = None
    # Edit payload (all optional; only provided fields are changed by the domain).
    recipients: list[Recipient] | tuple[Recipient, ...] | None = None
    subject: str | None = None
    body: str | None = None
    tone: str | None = None
    purpose: str | None = None
    reason: str | None = None  # informational reject note; never affects workflow


@dataclass
class ApprovalResult:
    """The outcome of an approval decision, ready for the interface layer."""

    status: ApprovalStatus
    draft: EmailDraft | None = None
    message: EmailMessage | None = None
    error: str | None = None
