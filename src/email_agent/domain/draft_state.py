"""Draft lifecycle states for the Email-Agent domain.

The lifecycle is a strict, single-direction state machine. Transitions are
guarded by :class:`email_agent.domain.policies.DraftPolicy` and the aggregate
methods on :class:`email_agent.domain.email_draft.EmailDraft`.
"""

from __future__ import annotations

from enum import StrEnum


class DraftState(StrEnum):
    """Lifecycle states of an email draft.

    DRAFTED          — initial/incomplete; may require clarification.
    AWAITING_APPROVAL — submitted for human review; not yet approved.
    APPROVED         — explicitly approved by a human; deliverable.
    SENT             — delivered to the email provider; terminal.
    """

    DRAFTED = "DRAFTED"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    APPROVED = "APPROVED"
    SENT = "SENT"
