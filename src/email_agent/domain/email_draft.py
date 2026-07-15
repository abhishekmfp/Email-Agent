"""EmailDraft aggregate.

The aggregate owns the draft lifecycle and all transition guards. It is a
pure in-memory value (no persistence, no provider, no I/O) per the G0.5
decision. An approved draft can be converted to an immutable
:class:`~email_agent.domain.email_message.EmailMessage`.

Lifecycle (strict, guarded):

    DRAFTED --submit--> AWAITING_APPROVAL --approve--> APPROVED --send--> SENT
                  ^                                         |
                  |           edit() invalidates approval    |
                  +-----------------------------------------+

Business rules:
  * submit_for_approval requires a *complete* draft (DraftPolicy).
  * approve requires an *explicit* valid Approval (ApprovalPolicy).
  * any edit after approval drops the draft back to AWAITING_APPROVAL and
    wipes the stored approval (so the human must re-approve the changed draft).
  * mark_sent requires an approved, deliverable draft.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from .approval import Approval
from .draft_state import DraftState
from .email_message import EmailMessage
from .exceptions import (
    ApprovalRequiredError,
    InvalidStateTransitionError,
)
from .policies import ApprovalPolicy, DraftPolicy
from .recipient import Recipient


@dataclass(frozen=True)
class EmailDraft:
    """A single email draft and its lifecycle state."""

    recipients: tuple[Recipient, ...] = field(default_factory=tuple)
    subject: str = ""
    body: str = ""
    tone: str | None = None
    purpose: str | None = None
    clarification_required: bool = False
    state: DraftState = DraftState.DRAFTED
    approval: Approval | None = None

    # ── Construction helpers ───────────────────────────────────────────────
    @classmethod
    def create(
        cls,
        recipients: list[Recipient] | tuple[Recipient, ...],
        subject: str,
        body: str,
        *,
        tone: str | None = None,
        purpose: str | None = None,
    ) -> EmailDraft:
        """Create a draft and compute whether it needs clarification."""
        draft = cls(
            recipients=tuple(recipients),
            subject=subject,
            body=body,
            tone=tone,
            purpose=purpose,
        )
        needs_clarification = DraftPolicy.requires_clarification(draft)
        return replace(draft, clarification_required=needs_clarification)

    # ── Lifecycle transitions ──────────────────────────────────────────────
    def submit_for_approval(self) -> EmailDraft:
        """Move DRAFTED -> AWAITING_APPROVAL once the draft is complete."""
        if self.state is not DraftState.DRAFTED:
            raise InvalidStateTransitionError(f"Cannot submit from state {self.state.value}")
        if not DraftPolicy.can_submit_for_approval(self):
            raise InvalidStateTransitionError(
                "Draft must be complete before submitting for approval"
            )
        return replace(self, state=DraftState.AWAITING_APPROVAL)

    def approve(self, approval: Approval) -> EmailDraft:
        """Move AWAITING_APPROVAL -> APPROVED with an explicit approval."""
        if self.state is not DraftState.AWAITING_APPROVAL:
            raise InvalidStateTransitionError(f"Cannot approve from state {self.state.value}")
        if not ApprovalPolicy.is_valid(approval):
            raise ApprovalRequiredError("A valid explicit approval is required")
        return replace(self, state=DraftState.APPROVED, approval=approval)

    def edit(
        self,
        *,
        recipients: list[Recipient] | tuple[Recipient, ...] | None = None,
        subject: str | None = None,
        body: str | None = None,
        tone: str | None = None,
        purpose: str | None = None,
    ) -> EmailDraft:
        """Return a mutated copy, invalidating any prior approval.

        Editing always drops the draft back to AWAITING_APPROVAL and clears the
        stored approval: the human must re-approve the changed content before it
        can be delivered (artifact-identity invariant).
        """
        updated = replace(
            self,
            recipients=tuple(recipients) if recipients is not None else self.recipients,
            subject=subject if subject is not None else self.subject,
            body=body if body is not None else self.body,
            tone=tone if tone is not None else self.tone,
            purpose=purpose if purpose is not None else self.purpose,
        )
        # Reset lifecycle: any change voids prior approval.
        updated = replace(
            updated,
            state=DraftState.AWAITING_APPROVAL,
            approval=None,
            clarification_required=DraftPolicy.requires_clarification(updated),
        )
        return updated

    def mark_sent(self) -> EmailDraft:
        """Move APPROVED -> SENT once delivery has occurred."""
        if not ApprovalPolicy.can_deliver(self, self.approval):
            raise ApprovalRequiredError(
                "Cannot mark sent without a valid explicit approval in APPROVED state"
            )
        return replace(self, state=DraftState.SENT)

    # ── Conversion ─────────────────────────────────────────────────────────
    def to_message(self) -> EmailMessage:
        """Convert an approved draft into the immutable delivery artifact.

        Raises if the draft is not in a deliverable (APPROVED) state, so an
        EmailMessage can only ever represent an explicitly approved draft.
        """
        if not ApprovalPolicy.can_deliver(self, self.approval):
            raise ApprovalRequiredError(
                "Only an approved draft can be converted to an EmailMessage"
            )
        return EmailMessage(
            recipients=self.recipients,
            subject=self.subject,
            body=self.body,
            tone=self.tone,
            purpose=self.purpose,
            approval=self.approval,  # type: ignore[arg-type]  # guaranteed non-None here
        )

    # ── Introspection ──────────────────────────────────────────────────────
    @property
    def is_deliverable(self) -> bool:
        """True when the draft is approved and carries a valid approval."""
        return ApprovalPolicy.can_deliver(self, self.approval)
