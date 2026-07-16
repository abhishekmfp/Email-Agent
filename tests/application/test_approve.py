"""Tests for the M4 approval workflow (ApproveEmailUseCase + ApprovalDecision).

M4 does not invoke Gmail — approve produces a frozen EmailMessage and stops.
The interface layer re-invokes DraftEmailUseCase for regenerate (decision D1),
so ApproveEmailUseCase is exercised here without any LLM.

Covers the artifact-identity invariant end to end: a delivered EmailMessage is
byte-identical to the approved draft, and remains so even if the *original* draft
is later edited.
"""

from __future__ import annotations

from email_agent.application.approval_request import (
    ApprovalDecision,
    ApprovalStatus,
)
from email_agent.application.approve_email_use_case import ApproveEmailUseCase
from email_agent.domain.approval import Approval
from email_agent.domain.draft_state import DraftState
from email_agent.domain.email_draft import EmailDraft
from email_agent.domain.recipient import Recipient


def _awaiting_draft() -> EmailDraft:
    return EmailDraft.create(
        recipients=[Recipient(email="a@b.com")],
        subject="Quarterly update",
        body="Here is the Q3 summary.",
        tone="formal",
        purpose="status",
    ).submit_for_approval()


def _uc() -> ApproveEmailUseCase:
    return ApproveEmailUseCase()


# ── approve ────────────────────────────────────────────────────────────────
def test_approve_creates_frozen_email_message() -> None:
    draft = _awaiting_draft()
    result = _uc().execute(draft, ApprovalDecision(decision="approve", approver="Abhishek"))
    assert result.status is ApprovalStatus.APPROVED
    assert result.message is not None
    # Approve returns the immutable EmailMessage; the input draft is not echoed.
    assert result.draft is None
    # The UC never mutates its input: the caller's draft stays AWAITING_APPROVAL.
    assert draft.state is DraftState.AWAITING_APPROVAL


def test_approve_message_equals_draft_content() -> None:
    draft = _awaiting_draft()
    result = _uc().execute(draft, ApprovalDecision(decision="approve", approver="Abhishek"))
    msg = result.message
    assert msg is not None
    assert msg.subject == draft.subject
    assert msg.body == draft.body
    assert tuple(r.email for r in msg.recipients) == tuple(r.email for r in draft.recipients)
    assert msg.tone == draft.tone
    assert msg.purpose == draft.purpose


def test_approve_embeds_the_exact_approval_object() -> None:
    draft = _awaiting_draft()
    result = _uc().execute(draft, ApprovalDecision(decision="approve", approver="Abhishek"))
    assert result.message is not None
    assert isinstance(result.message.approval, Approval)
    assert result.message.approval.approver == "Abhishek"


def test_approve_from_wrong_state_is_error() -> None:
    # A freshly created draft is DRAFTED, not AWAITING_APPROVAL.
    draft = EmailDraft.create(
        recipients=[Recipient(email="a@b.com")],
        subject="S",
        body="B",
    )
    assert draft.state is DraftState.DRAFTED
    result = _uc().execute(draft, ApprovalDecision(decision="approve", approver="X"))
    assert result.status is ApprovalStatus.ERROR
    assert result.message is None


def test_approve_with_blank_approver_is_error() -> None:
    draft = _awaiting_draft()
    result = _uc().execute(draft, ApprovalDecision(decision="approve", approver="  "))
    assert result.status is ApprovalStatus.ERROR
    assert result.message is None


def test_approve_unknown_decision_is_error() -> None:
    draft = _awaiting_draft()
    # Force an unknown decision to exercise the handler lookup miss.
    bad = ApprovalDecision(decision="approve", approver="X")  # type: ignore[arg-type]
    object.__setattr__(bad, "decision", "frobnicate")  # type: ignore[arg-type]
    res = _uc().execute(draft, bad)
    assert res.status is ApprovalStatus.ERROR


# ── edit ───────────────────────────────────────────────────────────────────
def test_edit_resets_state_and_wipes_approval() -> None:
    draft = _awaiting_draft()
    # Approve first to produce a deliverable, then edit the original draft again.
    approved = _uc().execute(draft, ApprovalDecision(decision="approve", approver="Abhishek"))
    assert approved.status is ApprovalStatus.APPROVED
    edited = _uc().execute(
        draft,
        ApprovalDecision(decision="edit", subject="Corrected subject"),
    )
    assert edited.status is ApprovalStatus.AWAITING_APPROVAL
    assert edited.draft is not None
    assert edited.draft.subject == "Corrected subject"
    assert edited.draft.state is DraftState.AWAITING_APPROVAL
    assert edited.draft.approval is None
    assert edited.message is None  # no deliverable after an edit


def test_edit_does_not_create_email_message() -> None:
    draft = _awaiting_draft()
    result = _uc().execute(draft, ApprovalDecision(decision="edit", body="new body text"))
    assert result.status is ApprovalStatus.AWAITING_APPROVAL
    assert result.message is None


# ── reject ─────────────────────────────────────────────────────────────────
def test_reject_terminates_with_no_message() -> None:
    draft = _awaiting_draft()
    result = _uc().execute(draft, ApprovalDecision(decision="reject", reason="wrong tone"))
    assert result.status is ApprovalStatus.REJECTED
    assert result.message is None
    assert result.draft is None


# ── artifact-identity acceptance (the requested invariant test) ────────────
def test_email_message_immutable_after_later_draft_edit() -> None:
    """The approved EmailMessage must remain byte-identical even if the
    originally drafted is subsequently edited — proving ApproveEmailUseCase
    froze a snapshot, not a live reference."""
    draft = _awaiting_draft()
    result = _uc().execute(draft, ApprovalDecision(decision="approve", approver="Abhishek"))
    assert result.status is ApprovalStatus.APPROVED
    message = result.message
    assert message is not None

    # Later, the original draft object is edited (simulating a post-approval change).
    edited_draft = draft.edit(subject="Totally different subject", body="Changed.")

    # The previously produced EmailMessage is unchanged.
    assert message.subject == "Quarterly update"
    assert message.body == "Here is the Q3 summary."
    assert edited_draft.subject != message.subject  # the draft changed; message did not
    assert message.recipients == (Recipient(email="a@b.com"),)
    # EmailMessage is frozen (dataclass(frozen=True)): the value snapshot is
    # independent of the draft's later mutation, so delivery would be identical
    # to what the human approved.
