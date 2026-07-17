"""Pytest fixtures for the M7 interface-layer tests.

Provides a ``Container`` whose inner dependencies are fakes so the interface can
be exercised end-to-end without a real Anthropic LLM or Gmail transport. The
fakes honor the VERIFIED application/domain contracts — they never change the
inner layers, only substitute the adapter/transport seams (M7 rule: inner
layers frozen; the interface is the only new code).
"""

from __future__ import annotations

import pytest

from email_agent.application.approve_email_use_case import ApproveEmailUseCase
from email_agent.application.draft_email_use_case import DraftEmailUseCase
from email_agent.application.draft_request import DraftRequest, DraftStatus
from email_agent.application.send_email_use_case import SendEmailUseCase
from email_agent.config.settings import Settings
from email_agent.domain.draft_state import DraftState
from email_agent.domain.email_draft import EmailDraft
from email_agent.domain.email_message import EmailMessage
from email_agent.domain.recipient import Recipient
from email_agent.interface.container import Container


class FakeDraftingService:
    """Fake DraftingService: returns a valid AWAITING_APPROVAL draft."""

    def draft(self, request: DraftRequest):
        draft = EmailDraft(
            recipients=(Recipient(email="alice@example.com"),),
            subject="Confirm meeting",
            body="Hi Alice, confirming our 3pm meeting. Best, Abhishek",
            tone="professional",
            purpose="confirmation",
            clarification_required=False,
            state=DraftState.AWAITING_APPROVAL,
        )
        return type(
            "DraftResult",
            (),
            {
                "status": DraftStatus.SUCCESS,
                "draft": draft,
                "preview": "Subject: Confirm meeting\n\nHi Alice, confirming our 3pm meeting.",
                "error": None,
                "clarification_question": None,
                "missing_fields": None,
            },
        )()


class FakeDeliveryService:
    """Fake DeliveryService: always reports success (no real Gmail call)."""

    def __init__(self, *, fail_status: str | None = None) -> None:
        self.fail_status = fail_status
        self.last_message: EmailMessage | None = None

    def send(self, message: EmailMessage):
        self.last_message = message
        if self.fail_status == "auth_failed":
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
        if self.fail_status == "unknown_state":
            return type(
                "R",
                (),
                {
                    "success": False,
                    "status": "unknown_state",
                    "error": "Gmail returned 200 with unknown label",
                    "message_id": None,
                    "thread_id": None,
                },
            )()
        return type(
            "R",
            (),
            {
                "success": True,
                "status": "delivered",
                "error": None,
                "message_id": "<msg-123>",
                "thread_id": "<th-9>",
            },
        )()


@pytest.fixture
def fake_container(monkeypatch):
    """Build a Container wired with fakes; verifies interface composes use cases."""

    settings = Settings()
    drafting = FakeDraftingService()
    draft_uc = DraftEmailUseCase(drafting_service=drafting)
    approve_uc = ApproveEmailUseCase()
    delivery = FakeDeliveryService()
    send_uc = SendEmailUseCase(approve_use_case=approve_uc, delivery_service=delivery)

    return Container(
        settings=settings,
        draft_email_use_case=draft_uc,
        approve_email_use_case=approve_uc,
        send_email_use_case=send_uc,
        delivery_service=delivery,
        oauth_client=object(),  # not exercised by interface tests
    )
