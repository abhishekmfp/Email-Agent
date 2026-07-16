"""Thin application use case for approval (M4).

``ApproveEmailUseCase`` turns a human's ``ApprovalDecision`` on an
AWAITING_APPROVAL ``EmailDraft`` into a deterministic outcome:

- ``approve``  → domain ``approve`` + ``to_message`` → frozen ``EmailMessage``
                 (Gmail is NOT invoked here; delivery is M6).
- ``edit``     → domain ``edit`` → draft back to AWAITING_APPROVAL, prior
                 approval wiped; human must re-approve.
- ``reject``   → no ``EmailMessage``; workflow terminates.

The use case holds no business rules — the domain owns approval validity,
lifecycle and the immutable conversion. This use case is LLM-free: regenerate
is handled by re-invoking ``DraftEmailUseCase`` in the interface layer, so the
LLM boundary stays in exactly one place (per M4 design decision D1).

Engineering invariant (M4): **only this use case may create ``Approval``
objects.** No other application or interface code constructs ``Approval``.
"""

from __future__ import annotations

from email_agent.domain.approval import Approval
from email_agent.domain.email_draft import EmailDraft
from email_agent.domain.exceptions import (
    ApprovalInvalidError,
    ApprovalRequiredError,
    InvalidStateTransitionError,
)

from .approval_request import ApprovalDecision, ApprovalResult, ApprovalStatus


class ApproveEmailUseCase:
    """Exposes the approve/edit/reject capability to the interface layer."""

    def execute(self, draft: EmailDraft, decision: ApprovalDecision) -> ApprovalResult:
        """Apply the human's decision to the draft and return the outcome."""
        handler = {
            "approve": self._approve,
            "edit": self._edit,
            "reject": self._reject,
        }.get(decision.decision)
        if handler is None:
            return ApprovalResult(
                status=ApprovalStatus.ERROR,
                error=f"Unknown approval decision: {decision.decision!r}",
            )
        try:
            return handler(draft, decision)
        except (ApprovalInvalidError, ApprovalRequiredError, InvalidStateTransitionError) as exc:
            # Domain guards are the source of truth; surface them, never bypass.
            return ApprovalResult(status=ApprovalStatus.ERROR, error=str(exc))

    def _approve(self, draft: EmailDraft, decision: ApprovalDecision) -> ApprovalResult:
        if not decision.approver or not decision.approver.strip():
            return ApprovalResult(
                status=ApprovalStatus.ERROR,
                error="Approval requires a non-empty approver identity",
            )
        # Only this use case constructs Approval (M4 engineering decision).
        approval = Approval(approver=decision.approver)
        approved = draft.approve(approval)
        message = approved.to_message()
        return ApprovalResult(status=ApprovalStatus.APPROVED, message=message)

    def _edit(self, draft: EmailDraft, decision: ApprovalDecision) -> ApprovalResult:
        edited = draft.edit(
            recipients=decision.recipients,
            subject=decision.subject,
            body=decision.body,
            tone=decision.tone,
            purpose=decision.purpose,
        )
        return ApprovalResult(status=ApprovalStatus.AWAITING_APPROVAL, draft=edited)

    def _reject(self, draft: EmailDraft, decision: ApprovalDecision) -> ApprovalResult:
        # No EmailMessage is produced; the workflow terminates.
        return ApprovalResult(status=ApprovalStatus.REJECTED, draft=None)
