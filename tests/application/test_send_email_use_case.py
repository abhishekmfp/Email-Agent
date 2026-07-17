"""Unit tests for the SendEmailUseCase (M7 — Option gamma).

Confirms the application-layer orchestration: it approves via the VERIFIED
ApproveEmailUseCase, then delivers the EXACT EmailMessage instance via the
VERIFIED DeliveryService, and returns a single unified SendResult. No domain
object is rebuilt; Approval is never constructed here.
"""

from __future__ import annotations

from email_agent.application.approval_request import (
    ApprovalDecision,
    ApprovalResult,
    ApprovalStatus,
)
from email_agent.application.send_email_use_case import SendEmailUseCase, SendResult
from email_agent.domain.draft_state import DraftState
from email_agent.domain.email_draft import EmailDraft
from email_agent.domain.email_message import EmailMessage
from email_agent.domain.recipient import Recipient


def _draft() -> EmailDraft:
    return EmailDraft(
        recipients=(Recipient(email="alice@example.com"),),
        subject="Confirm meeting",
        body="Hi Alice.",
        tone="professional",
        purpose="confirmation",
        clarification_required=False,
        state=DraftState.AWAITING_APPROVAL,
    )


def _message() -> EmailMessage:
    return EmailMessage(
        recipients=(Recipient(email="alice@example.com"),),
        subject="Confirm meeting",
        body="Hi Alice.",
        tone="professional",
        purpose="confirmation",
        approval=None,  # type: ignore[arg-type]
    )


class _ApproveOK:
    """Stand-in for ApproveEmailUseCase returning a valid APPROVED message."""

    def __init__(self) -> None:
        self.last_message: EmailMessage | None = None

    def execute(self, draft, decision):
        msg = _message()
        self.last_message = msg
        return ApprovalResult(status=ApprovalStatus.APPROVED, message=msg)


class _ApproveRejected:
    def execute(self, draft, decision):
        return ApprovalResult(status=ApprovalStatus.ERROR, error="not approvable")


class _DeliverOK:
    def __init__(self) -> None:
        self.last_message: EmailMessage | None = None

    def send(self, message):
        self.last_message = message
        return type("R", (), {"success": True, "status": "delivered",
                              "error": None, "message_id": "msg-1", "thread_id": "th-1"})()


class _DeliverAuthFailed:
    def send(self, message):
        return type("R", (), {"success": False, "status": "auth_failed",
                              "error": "refresh failed", "message_id": None, "thread_id": None})()


class _DeliverUnknown:
    def send(self, message):
        return type("R", (), {"success": False, "status": "unknown_state",
                              "error": "200/UNKNOWN", "message_id": None, "thread_id": None})()


class _DeliverNotApproved:
    def send(self, message):
        return type("R", (), {"success": False, "status": "not_approved",
                              "error": "no approval", "message_id": None, "thread_id": None})()


def _decision() -> ApprovalDecision:
    return ApprovalDecision(decision="approve", approver="Abhishek")


def test_send_succeeds_and_forwards_exact_message():
    deliver = _DeliverOK()
    approve = _ApproveOK()
    uc = SendEmailUseCase(approve_use_case=approve, delivery_service=deliver)
    result = uc.execute(_draft(), _decision())

    assert isinstance(result, SendResult)
    assert result.status == "SENT"
    assert result.message_id == "msg-1"
    # artifact_identity: the EXACT message instance approved (approve.last_message)
    # is the one delivered — SendEmailUseCase forwards it without rebuilding.
    assert deliver.last_message is approve.last_message


def test_send_forwards_approved_message_instance():
    deliver = _DeliverOK()
    approve = _ApproveOK()
    uc = SendEmailUseCase(approve_use_case=approve, delivery_service=deliver)
    result = uc.execute(_draft(), _decision())
    # The message DeliveryService received must be the same object Approve returned.
    assert deliver.last_message is approve.last_message
    assert result.status == "SENT"


def test_send_approval_rejected_short_circuits_delivery():
    deliver = _DeliverOK()
    uc = SendEmailUseCase(approve_use_case=_ApproveRejected(), delivery_service=deliver)
    result = uc.execute(_draft(), _decision())
    assert result.status == "APPROVAL_REJECTED"
    assert deliver.last_message is None  # delivery never attempted
    assert result.error == "not approvable"


def test_send_auth_failed_maps_to_auth_failed():
    uc = SendEmailUseCase(approve_use_case=_ApproveOK(), delivery_service=_DeliverAuthFailed())
    result = uc.execute(_draft(), _decision())
    assert result.status == "AUTH_FAILED"
    assert result.detail == {"delivery_status": "auth_failed"}


def test_send_unknown_state_maps_to_unknown_state():
    uc = SendEmailUseCase(approve_use_case=_ApproveOK(), delivery_service=_DeliverUnknown())
    result = uc.execute(_draft(), _decision())
    assert result.status == "UNKNOWN_STATE"
    assert "unconfirmed" in result.error


def test_send_not_approved_maps_to_approval_rejected():
    uc = SendEmailUseCase(approve_use_case=_ApproveOK(), delivery_service=_DeliverNotApproved())
    result = uc.execute(_draft(), _decision())
    assert result.status == "APPROVAL_REJECTED"
    assert result.detail == {"delivery_status": "not_approved"}
