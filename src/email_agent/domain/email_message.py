"""EmailMessage immutable artifact.

Produced only from an approved :class:`~email_agent.domain.email_draft.EmailDraft`
via ``EmailDraft.to_message()``. This is the exact artifact the delivery service
hands to the Gmail adapter, so it must be byte-identical to what the human
approved (artifact-identity invariant).
"""

from __future__ import annotations

from dataclasses import dataclass

from .approval import Approval
from .recipient import Recipient


@dataclass(frozen=True)
class EmailMessage:
    """The immutable, approved email ready for delivery."""

    recipients: tuple[Recipient, ...]
    subject: str
    body: str
    tone: str | None
    purpose: str | None
    approval: Approval
