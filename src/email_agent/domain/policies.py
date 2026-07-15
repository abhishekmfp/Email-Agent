"""Domain policies for drafts and approvals.

Policies encode business rules without depending on any framework, provider, or
I/O. They are pure functions over domain value objects and raise domain
exceptions when a rule is violated.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .approval import Approval
from .draft_state import DraftState
from .exceptions import DraftValidationError

if TYPE_CHECKING:  # EmailDraft is only referenced in type hints below.
    from .email_draft import EmailDraft


class DraftPolicy:
    """Business rules governing a draft's required content and lifecycle."""

    MAX_SUBJECT_LENGTH = 998  # SMTP-safe upper bound
    REQUIRED_FIELDS = ("recipients", "subject", "body")

    @classmethod
    def is_complete(cls, draft: EmailDraft) -> bool:
        """True when every required field is populated and valid."""
        try:
            cls.validate_required(draft)
        except DraftValidationError:
            return False
        return True

    @classmethod
    def validate_required(cls, draft: EmailDraft) -> None:
        """Raise :class:`DraftValidationError` if a required field is missing."""
        if not draft.recipients:
            raise DraftValidationError("Draft must have at least one recipient")
        if not draft.subject or not draft.subject.strip():
            raise DraftValidationError("Draft must have a non-empty subject")
        if len(draft.subject) > cls.MAX_SUBJECT_LENGTH:
            raise DraftValidationError(f"Subject exceeds {cls.MAX_SUBJECT_LENGTH} characters")
        if not draft.body.strip():
            raise DraftValidationError("Draft must have a non-empty body")

    @classmethod
    def requires_clarification(cls, draft: EmailDraft) -> bool:
        """True when the draft is missing information the human must supply.

        Clarification is required whenever the draft is incomplete. The
        application layer uses this to decide whether to ask the human before
        presenting a preview for approval.
        """
        return not cls.is_complete(draft)

    @classmethod
    def can_submit_for_approval(cls, draft: EmailDraft) -> bool:
        """A draft may be submitted for approval only once it is complete."""
        return cls.is_complete(draft)


class ApprovalPolicy:
    """Business rules governing approval validity and delivery eligibility."""

    #: Transitions that are legally deliverable.
    DELIVERABLE_STATES = (DraftState.APPROVED,)

    @classmethod
    def is_valid(cls, approval: Approval | None) -> bool:
        """True when an approval value object exists and is well-formed.

        An ``Approval`` is always valid on construction (its ``__post_init__``
        refuses blank approvers), so this checks presence and the value-object
        invariant rather than re-raising.
        """
        if approval is None:
            return False
        return isinstance(approval.approver, str) and bool(approval.approver.strip())

    @classmethod
    def can_deliver(cls, draft: EmailDraft, approval: Approval | None) -> bool:
        """Delivery is allowed only from APPROVED with a valid approval."""
        return (
            draft.state is DraftState.APPROVED
            and cls.is_valid(approval)
            and draft.approval is not None
            and draft.approval is approval
        )
