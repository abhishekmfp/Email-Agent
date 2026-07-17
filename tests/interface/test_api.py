"""API-level tests for the M7 FastAPI interface.

Exercises the five endpoints with the fake container. Confirms: a Draft returns
a serializable DraftResponseDTO; Edit round-trips the DTO and returns a new
AWAITING_APPROVAL draft; Send composes ApproveEmailUseCase + DeliveryService and
returns SENT with no domain/business logic in the interface; Reject returns
REJECTED; GET /health returns the single packaged version. Verifies AC-UI-1
(one endpoint -> one use case) and the Translation Boundary (no domain types in
responses).
"""

from __future__ import annotations

import dataclasses

from fastapi.testclient import TestClient

from email_agent import __version__
from email_agent.application.approval_request import ApprovalResult, ApprovalStatus
from email_agent.application.approve_email_use_case import ApproveEmailUseCase
from email_agent.application.draft_email_use_case import DraftEmailUseCase
from email_agent.application.draft_request import DraftStatus
from email_agent.application.send_email_use_case import SendEmailUseCase
from email_agent.interface.api import create_app


def _client(container):
    return TestClient(create_app(container))


def test_health_returns_single_version(fake_container):
    client = _client(fake_container)
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "healthy"
    assert body["version"] == __version__


def test_draft_returns_dto(fake_container):
    client = _client(fake_container)
    resp = client.post("/draft", json={"user_request": "Confirm the 3pm meeting with Alice"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "SUCCESS"
    d = body["draft"]
    # Transport contract: addresses only, state enum preserved, no Approval object.
    assert d["recipients"] == ["alice@example.com"]
    assert d["state"] == "AWAITING_APPROVAL"
    assert "approval" not in d


def test_edit_round_trips_dto(fake_container):
    client = _client(fake_container)
    drafted = client.post("/draft", json={"user_request": "Draft to Alice"}).json()
    edited = client.post(
        "/edit",
        json={
            "draft": drafted["draft"],
            "subject": "Updated subject",
            "body": "Revised body text",
        },
    )
    assert edited.status_code == 200
    body = edited.json()
    assert body["status"] == "AWAITING_APPROVAL"
    assert body["draft"]["subject"] == "Updated subject"


def test_send_composes_approval_and_delivery(fake_container):
    client = _client(fake_container)
    drafted = client.post("/draft", json={"user_request": "Send to Alice"}).json()
    resp = client.post("/send", json={"draft": drafted["draft"], "approver": "Abhishek"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "SENT"
    assert body["message_id"] == "<msg-123>"
    # artifact_identity: the exact EmailMessage the use case produced was delivered.
    assert fake_container.delivery_service.last_message is not None


def test_send_missing_approver_fails_validation(fake_container, monkeypatch):
    # Force config identity empty so B3 step 3 fires (no request approver, no config).
    fake_container.settings.user.name = ""
    client = _client(fake_container)
    drafted = client.post("/draft", json={"user_request": "Send to Alice"}).json()
    resp = client.post("/send", json={"draft": drafted["draft"]})
    assert resp.status_code == 422
    assert resp.json()["code"] == "validation_error"


def test_send_falls_back_to_config_approver(fake_container):
    fake_container.settings.user.name = "Config User"
    client = _client(fake_container)
    drafted = client.post("/draft", json={"user_request": "Send to Alice"}).json()
    resp = client.post("/send", json={"draft": drafted["draft"]})
    assert resp.status_code == 200
    assert resp.json()["status"] == "SENT"


def test_send_auth_failed_maps_to_auth_required(fake_container, monkeypatch):
    # Local fake delivery that reports auth_failed (no real Gmail).
    class _FakeDeliver:
        def send(self, message):
            return type(
                "R",
                (),
                {
                    "success": False,
                    "status": "auth_failed",
                    "error": "OAuth token refresh failed",
                    "message_id": None,
                    "thread_id": None,
                },
            )()

    import dataclasses

    send_uc = SendEmailUseCase(
        approve_use_case=fake_container.approve_email_use_case,
        delivery_service=_FakeDeliver(),
    )
    container = dataclasses.replace(fake_container, send_email_use_case=send_uc)
    client = _client(container)
    drafted = client.post("/draft", json={"user_request": "Send"}).json()
    resp = client.post("/send", json={"draft": drafted["draft"], "approver": "Abhishek"})
    assert resp.status_code == 401
    assert resp.json()["code"] == "auth_required"


def test_reject_returns_rejected(fake_container):
    client = _client(fake_container)
    drafted = client.post("/draft", json={"user_request": "Reject me"}).json()
    resp = client.post("/reject", json={"draft": drafted["draft"], "reason": "wrong tone"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "REJECTED"


def test_no_review_or_approve_endpoints(fake_container):
    client = _client(fake_container)
    # Per M7 decision #1: no /review, /approve, or /regenerate routes exist.
    for path in ("/review", "/approve", "/regenerate"):
        assert client.post(path, json={}).status_code == 404


# ── Branch coverage for the real error paths ──────────────────────────────────
class _ClarificationDrafting:
    def draft(self, request):
        return type(
            "R",
            (),
            {
                "status": DraftStatus.CLARIFICATION_REQUIRED,
                "draft": None,
                "preview": None,
                "error": "missing recipient email",
                "clarification_question": "Who should receive this email?",
                "missing_fields": ["recipients"],
            },
        )()


def test_draft_clarification_branch(fake_container, monkeypatch):
    container = dataclasses.replace(
        fake_container,
        draft_email_use_case=DraftEmailUseCase(drafting_service=_ClarificationDrafting()),
    )
    client = _client(container)
    resp = client.post("/draft", json={"user_request": "email someone"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "CLARIFICATION_REQUIRED"
    assert body["clarification_question"]
    assert body["missing_fields"] == ["recipients"]


class _ErrorApprover(ApproveEmailUseCase):
    def execute(self, draft, decision):
        return ApprovalResult(status=ApprovalStatus.ERROR, error="decision rejected by domain")


def test_send_approval_error_branch(fake_container, monkeypatch):
    import dataclasses

    send_uc = SendEmailUseCase(
        approve_use_case=_ErrorApprover(),
        delivery_service=fake_container.delivery_service,
    )
    container = dataclasses.replace(fake_container, send_email_use_case=send_uc)
    client = _client(container)
    drafted = client.post("/draft", json={"user_request": "Send"}).json()
    resp = client.post("/send", json={"draft": drafted["draft"], "approver": "Abhishek"})
    assert resp.status_code == 422
    assert resp.json()["code"] == "approval_error"
