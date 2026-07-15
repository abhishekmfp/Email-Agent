"""Unit tests for the Email-Agent domain layer (Milestone M2)."""

from __future__ import annotations

from datetime import datetime

import pytest

from email_agent.domain import (
    Approval,
    ApprovalInvalidError,
    ApprovalPolicy,
    ApprovalRequiredError,
    DraftPolicy,
    DraftState,
    DraftValidationError,
    EmailDraft,
    EmailMessage,
    InvalidRecipientError,
    InvalidStateTransitionError,
    Recipient,
)


# ── Recipient ───────────────────────────────────────────────────────────────
def test_recipient_valid_minimal() -> None:
    r = Recipient(email="a@example.com")
    assert r.email == "a@example.com"
    assert r.name is None


def test_recipient_valid_with_name() -> None:
    r = Recipient(email="a@example.com", name="Alice")
    assert r.name == "Alice"


def test_recipient_rejects_malformed() -> None:
    for bad in ["", "no-at-sign", "a@b", "@example.com", "a b@example.com", "a@b@c.com"]:
        with pytest.raises(InvalidRecipientError):
            Recipient(email=bad)


def test_recipient_rejects_non_string_name() -> None:
    with pytest.raises(InvalidRecipientError):
        Recipient(email="a@example.com", name=123)  # type: ignore[arg-type]


def test_recipient_is_hashable_and_frozen() -> None:
    r1 = Recipient(email="a@example.com")
    r2 = Recipient(email="a@example.com")
    assert r1 == r2
    assert hash(r1) == hash(r2)
    with pytest.raises(AttributeError):
        r1.email = "x@y.com"  # type: ignore[misc]


# ── Approval ──────────────────────────────────────────────────────────────
def test_approval_valid() -> None:
    a = Approval(approver="human", decided_at=datetime(2026, 1, 1))
    assert a.approver == "human"
    assert a.decided_at == datetime(2026, 1, 1)


def test_approval_requires_non_empty_approver() -> None:
    for bad in ["", "   "]:
        with pytest.raises(ApprovalInvalidError):
            Approval(approver=bad)  # type: ignore[arg-type]


# ── DraftState ─────────────────────────────────────────────────────────────
def test_draft_state_is_str_enum() -> None:
    assert DraftState.APPROVED.value == "APPROVED"
    assert DraftState.DRAFTED != DraftState.SENT


# ── EmailDraft.create ───────────────────────────────────────────────────────
def test_create_complete_draft_no_clarification() -> None:
    d = EmailDraft.create(
        recipients=[Recipient(email="a@example.com")],
        subject="Hi",
        body="Hello there.",
    )
    assert d.state is DraftState.DRAFTED
    assert d.clarification_required is False


def test_create_incomplete_draft_flags_clarification() -> None:
    d = EmailDraft.create(recipients=[], subject="", body="")
    assert d.clarification_required is True


# ── DraftPolicy ─────────────────────────────────────────────────────────────
def test_draftpolicy_is_complete_true() -> None:
    d = EmailDraft.create(
        recipients=[Recipient(email="a@example.com")],
        subject="S",
        body="B",
    )
    assert DraftPolicy.is_complete(d) is True


def test_draftpolicy_is_complete_false_when_empty_recipients() -> None:
    d = EmailDraft.create(recipients=[], subject="S", body="B")
    assert DraftPolicy.is_complete(d) is False


def test_draftpolicy_is_complete_false_when_empty_subject() -> None:
    d = EmailDraft.create(
        recipients=[Recipient(email="a@example.com")],
        subject="   ",
        body="B",
    )
    assert DraftPolicy.is_complete(d) is False


def test_draftpolicy_validate_required_raises_on_missing() -> None:
    d = EmailDraft.create(recipients=[], subject="", body="")
    with pytest.raises(DraftValidationError):
        DraftPolicy.validate_required(d)


def test_draftpolicy_subject_within_limit_passes() -> None:
    d = EmailDraft.create(
        recipients=[Recipient(email="a@example.com")],
        subject="x" * 998,  # exactly at the limit
        body="B",
    )
    # Should not raise — at the boundary, still valid.
    DraftPolicy.validate_required(d)


def test_draftpolicy_subject_too_long() -> None:
    d = EmailDraft.create(
        recipients=[Recipient(email="a@example.com")],
        subject="x" * 999,
        body="B",
    )
    with pytest.raises(DraftValidationError):
        DraftPolicy.validate_required(d)


def test_draftpolicy_requires_clarification_reflects_incomplete() -> None:
    good = EmailDraft.create(recipients=[Recipient(email="a@example.com")], subject="S", body="B")
    bad = EmailDraft.create(recipients=[], subject="", body="")
    assert DraftPolicy.requires_clarification(good) is False
    assert DraftPolicy.requires_clarification(bad) is True


def test_draftpolicy_can_submit_only_when_complete() -> None:
    good = EmailDraft.create(recipients=[Recipient(email="a@example.com")], subject="S", body="B")
    bad = EmailDraft.create(recipients=[], subject="", body="")
    assert DraftPolicy.can_submit_for_approval(good) is True
    assert DraftPolicy.can_submit_for_approval(bad) is False


# ── ApprovalPolicy ──────────────────────────────────────────────────────────
def test_approvalpolicy_is_valid_true() -> None:
    assert ApprovalPolicy.is_valid(Approval(approver="h")) is True


def test_approvalpolicy_is_valid_false_when_none() -> None:
    assert ApprovalPolicy.is_valid(None) is False


def test_approvalpolicy_is_valid_none_false() -> None:
    assert ApprovalPolicy.is_valid(None) is False


def test_approval_rejects_blank_approver_at_construction() -> None:
    # Value objects are always valid on construction; a blank approver is refused.
    with pytest.raises(ApprovalInvalidError):
        Approval(approver="  ")


def test_approvalpolicy_can_deliver_true() -> None:
    ap = Approval(approver="h")
    d = (
        EmailDraft.create(recipients=[Recipient(email="a@example.com")], subject="S", body="B")
        .submit_for_approval()
        .approve(ap)
    )
    assert ApprovalPolicy.can_deliver(d, ap) is True


def test_approvalpolicy_can_deliver_false_approved_but_wrong_approval_ref() -> None:
    # Draft approved with `ap`, but delivery presented a different approval object.
    ap = Approval(approver="h")
    d = (
        EmailDraft.create(recipients=[Recipient(email="a@example.com")], subject="S", body="B")
        .submit_for_approval()
        .approve(ap)
    )
    other = Approval(approver="h")
    assert other is not d.approval
    assert ApprovalPolicy.can_deliver(d, other) is False
    # The stored approval must be the *same* object that authorizes delivery.
    assert ApprovalPolicy.can_deliver(d, other) is False


def test_approvalpolicy_can_deliver_false_not_approved() -> None:
    ap = Approval(approver="h")
    d = EmailDraft.create(recipients=[Recipient(email="a@example.com")], subject="S", body="B")
    assert ApprovalPolicy.can_deliver(d, ap) is False


# ── Lifecycle: submit_for_approval ───────────────────────────────────────────
def test_submit_from_drafted_ok() -> None:
    d = EmailDraft.create(recipients=[Recipient(email="a@example.com")], subject="S", body="B")
    assert d.submit_for_approval().state is DraftState.AWAITING_APPROVAL


def test_submit_rejects_incomplete() -> None:
    d = EmailDraft.create(recipients=[], subject="", body="")
    with pytest.raises(InvalidStateTransitionError):
        d.submit_for_approval()


def test_submit_rejects_non_drafted() -> None:
    d = EmailDraft.create(
        recipients=[Recipient(email="a@example.com")], subject="S", body="B"
    ).submit_for_approval()
    with pytest.raises(InvalidStateTransitionError):
        d.submit_for_approval()


# ── Lifecycle: approve ───────────────────────────────────────────────────────
def test_approve_from_awaiting_ok() -> None:
    ap = Approval(approver="h")
    d = (
        EmailDraft.create(recipients=[Recipient(email="a@example.com")], subject="S", body="B")
        .submit_for_approval()
        .approve(ap)
    )
    assert d.state is DraftState.APPROVED
    assert d.approval is ap


def test_approve_rejects_wrong_state() -> None:
    d = EmailDraft.create(recipients=[Recipient(email="a@example.com")], subject="S", body="B")
    with pytest.raises(InvalidStateTransitionError):
        d.approve(Approval(approver="h"))


def test_approve_rejects_none_approval() -> None:
    d = EmailDraft.create(
        recipients=[Recipient(email="a@example.com")], subject="S", body="B"
    ).submit_for_approval()
    with pytest.raises(ApprovalRequiredError):
        d.approve(None)  # type: ignore[arg-type]


# ── Lifecycle: edit invalidates approval ────────────────────────────────────
def test_edit_resets_to_awaiting_and_clears_approval() -> None:
    ap = Approval(approver="h")
    d = (
        EmailDraft.create(recipients=[Recipient(email="a@example.com")], subject="S", body="B")
        .submit_for_approval()
        .approve(ap)
    )
    edited = d.edit(body="Changed body")
    assert edited.state is DraftState.AWAITING_APPROVAL
    assert edited.approval is None
    assert edited.body == "Changed body"


def test_edit_recomputes_clarification() -> None:
    d = (
        EmailDraft.create(recipients=[Recipient(email="a@example.com")], subject="S", body="B")
        .submit_for_approval()
        .approve(Approval(approver="h"))
    )
    edited = d.edit(recipients=[])
    assert edited.clarification_required is True


# ── Lifecycle: mark_sent ─────────────────────────────────────────────────────
def test_mark_sent_from_approved_ok() -> None:
    ap = Approval(approver="h")
    d = (
        EmailDraft.create(recipients=[Recipient(email="a@example.com")], subject="S", body="B")
        .submit_for_approval()
        .approve(ap)
        .mark_sent()
    )
    assert d.state is DraftState.SENT


def test_mark_sent_rejects_unapproved() -> None:
    d = EmailDraft.create(recipients=[Recipient(email="a@example.com")], subject="S", body="B")
    with pytest.raises(ApprovalRequiredError):
        d.mark_sent()


def test_mark_sent_rejects_awaiting() -> None:
    d = EmailDraft.create(
        recipients=[Recipient(email="a@example.com")], subject="S", body="B"
    ).submit_for_approval()
    with pytest.raises(ApprovalRequiredError):
        d.mark_sent()


# ── to_message / EmailMessage ───────────────────────────────────────────────
def test_to_message_requires_approval() -> None:
    d = EmailDraft.create(recipients=[Recipient(email="a@example.com")], subject="S", body="B")
    with pytest.raises(ApprovalRequiredError):
        d.to_message()


def test_to_message_produces_immutable_artifact() -> None:
    ap = Approval(approver="h", decided_at=datetime(2026, 1, 1))
    d = (
        EmailDraft.create(
            recipients=[Recipient(email="a@example.com")],
            subject="Subject",
            body="Body text",
            tone="formal",
            purpose="follow-up",
        )
        .submit_for_approval()
        .approve(ap)
    )
    msg = d.to_message()
    assert isinstance(msg, EmailMessage)
    assert msg.subject == "Subject"
    assert msg.body == "Body text"
    assert msg.tone == "formal"
    assert msg.purpose == "follow-up"
    assert msg.approval is ap
    assert msg.recipients == d.recipients


def test_emailmessage_is_frozen() -> None:
    ap = Approval(approver="h")
    msg = EmailMessage(
        recipients=(Recipient(email="a@example.com"),),
        subject="S",
        body="B",
        tone=None,
        purpose=None,
        approval=ap,
    )
    with pytest.raises(AttributeError):
        msg.subject = "X"  # type: ignore[misc]


# ── is_deliverable ───────────────────────────────────────────────────────────
def test_is_deliverable_false_initially() -> None:
    d = EmailDraft.create(recipients=[Recipient(email="a@example.com")], subject="S", body="B")
    assert d.is_deliverable is False


def test_is_deliverable_true_when_approved() -> None:
    ap = Approval(approver="h")
    d = (
        EmailDraft.create(recipients=[Recipient(email="a@example.com")], subject="S", body="B")
        .submit_for_approval()
        .approve(ap)
    )
    assert d.is_deliverable is True


# ── Cross-cutting: domain never raises non-domain errors ─────────────────────
def test_all_domain_exceptions_subclass_domain_error() -> None:
    from email_agent.domain import DomainError as DE

    for exc in (
        InvalidRecipientError,
        DraftValidationError,
        InvalidStateTransitionError,
        ApprovalRequiredError,
        ApprovalInvalidError,
    ):
        assert issubclass(exc, DE)


def test_full_happy_path_lifecycle() -> None:
    ap = Approval(approver="human", decided_at=datetime(2026, 6, 1))
    d = (
        EmailDraft.create(
            recipients=[Recipient(email="alice@example.com")],
            subject="Meeting",
            body="Shall we meet?",
        )
        .submit_for_approval()
        .approve(ap)
    )
    assert d.is_deliverable
    msg = d.to_message()
    sent = d.mark_sent()
    assert sent.state is DraftState.SENT
    assert msg.subject == "Meeting"
