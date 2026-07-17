"""Tests for DeliveryService (M6 — delivery orchestration).

Exercise the full accepted path with mocked OAuth + mocked GmailAdapter:
  * approved EmailMessage -> DeliveryResult.success with message_id;
  * ABSENCE of APPROVED -> assert GmailAdapter.send NOT invoked (approval_gate);
  * TokenRefreshError from refresh_if_needed -> hard stop, adapter.send NOT called;
  * UnknownDeliveryStateError (dispatched) -> reported, NO retry;
  * PreDispatchTransportError -> bounded pre-dispatch retry, no silent success;
  * artifact_identity: the EXACT EmailMessage instance is passed to the adapter.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from email_agent.application.delivery_service import DeliveryResult, DeliveryService
from email_agent.domain.email_draft import EmailDraft
from email_agent.domain.recipient import Recipient
from email_agent.infrastructure.gmail_adapter import GmailAdapter
from email_agent.infrastructure.gmail_errors import (
    PreDispatchTransportError,
    TokenRefreshError,
    UnknownDeliveryStateError,
)


def _awaiting_draft() -> EmailDraft:
    return EmailDraft.create(
        recipients=[Recipient(email="a@b.com")],
        subject="Quarterly update",
        body="Here is the Q3 summary.",
        tone="formal",
        purpose="status",
    ).submit_for_approval()


def _approve_uc() -> object:
    from email_agent.application.approval_request import ApprovalDecision
    from email_agent.application.approve_email_use_case import ApproveEmailUseCase

    draft = _awaiting_draft()
    res = ApproveEmailUseCase().execute(
        draft, ApprovalDecision(decision="approve", approver="Abhishek")
    )
    assert res.message is not None
    return res.message


def _oauth(tokens: object | None = None, *, raise_on_refresh: Exception | None = None) -> MagicMock:
    oauth = MagicMock()
    if raise_on_refresh is not None:
        oauth.refresh_if_needed.side_effect = raise_on_refresh
    else:
        oauth.refresh_if_needed.return_value = tokens if tokens is not None else _tokens()
    return oauth


def _tokens() -> object:
    from email_agent.infrastructure.oauth_token_store import OAuthTokens

    return OAuthTokens(access_token="valid-access", refresh_token="r", scopes=["gmail.send"])


def _adapter(send_return: dict[str, str] | Exception) -> MagicMock:
    adapter = MagicMock(spec=GmailAdapter)
    if isinstance(send_return, Exception):
        adapter.send.side_effect = send_return
    else:
        adapter.send.return_value = send_return
    return adapter


# ── happy path ──────────────────────────────────────────────────────────────
def test_send_approved_message_delivers() -> None:
    message = _approve_uc()
    oauth = _oauth()
    adapter = _adapter({"message_id": "msg-1", "thread_id": "thr-1"})
    service = DeliveryService(oauth, adapter)

    result = service.send(message)

    assert isinstance(result, DeliveryResult)
    assert result.success is True
    assert result.message_id == "msg-1"
    assert result.thread_id == "thr-1"
    oauth.refresh_if_needed.assert_called()
    assert oauth.refresh_if_needed.call_count >= 1
    # The EXACT EmailMessage instance was handed to the adapter (artifact_identity).
    assert adapter.send.call_args.args[0] is message


# ── approval_gate: no send without APPROVED ──────────────────────────────────
def test_no_send_without_approval() -> None:
    # Build an EmailMessage-shaped object WITHOUT an approval to simulate a
    # tampered / non-approved artifact. (A real EmailMessage can only be built
    # from an APPROVED draft, so we construct the dataclass directly.)
    from email_agent.domain.email_message import EmailMessage

    bad_message = EmailMessage(
        recipients=(Recipient(email="a@b.com"),),
        subject="S",
        body="B",
        tone=None,
        purpose=None,
        approval=None,
    )
    oauth = _oauth()
    adapter = _adapter({"message_id": "x"})
    service = DeliveryService(oauth, adapter)

    result = service.send(bad_message)

    assert result.success is False
    assert result.status == "not_approved"
    adapter.send.assert_not_called()
    oauth.refresh_if_needed.assert_not_called()


# ── auth failure: hard stop ─────────────────────────────────────────────────
def test_token_refresh_error_is_hard_stop() -> None:
    message = _approve_uc()
    oauth = _oauth(raise_on_refresh=TokenRefreshError("revoked refresh token"))
    adapter = _adapter({"message_id": "x"})
    service = DeliveryService(oauth, adapter)

    result = service.send(message)

    assert result.success is False
    assert result.status == "auth_failed"
    # Must NOT deliver on (or after) an auth failure.
    adapter.send.assert_not_called()


# ── unknown delivery state: never retry ──────────────────────────────────────
def test_unknown_state_reported_not_retried() -> None:
    message = _approve_uc()
    oauth = _oauth()
    adapter = _adapter(UnknownDeliveryStateError("dispatched, unconfirmed"))
    service = DeliveryService(oauth, adapter, max_attempts=3)

    result = service.send(message)

    assert result.success is False
    assert result.status == "unknown_state"
    # Exactly one attempt — UnknownDeliveryStateError must not be retried.
    assert adapter.send.call_count == 1


# ── pre-dispatch transport: bounded retry, no silent success ───────────────────
def test_predispatch_transport_retries_then_fails() -> None:
    message = _approve_uc()
    oauth = _oauth()
    adapter = _adapter(PreDispatchTransportError("connection refused"))
    service = DeliveryService(oauth, adapter, max_attempts=3, backoff_seconds=0)

    result = service.send(message)

    assert result.success is False
    assert result.status == "error"
    # Bounded: exactly max_attempts pre-dispatch tries, then surface.
    assert adapter.send.call_count == 3


def test_predispatch_transport_retries_then_succeeds() -> None:
    message = _approve_uc()
    oauth = _oauth()
    adapter = MagicMock(spec=GmailAdapter)
    # First two attempts fail pre-dispatch; third succeeds.
    adapter.send.side_effect = [
        PreDispatchTransportError("timeout 1"),
        PreDispatchTransportError("timeout 2"),
        {"message_id": "ok-1"},
    ]
    service = DeliveryService(oauth, adapter, max_attempts=3, backoff_seconds=0)

    result = service.send(message)

    assert result.success is True
    assert result.message_id == "ok-1"
    assert adapter.send.call_count == 3


def test_other_delivery_error_not_retried() -> None:
    from email_agent.infrastructure.gmail_errors import DeliveryError

    message = _approve_uc()
    oauth = _oauth()
    adapter = _adapter(DeliveryError("4xx invalid grant on send"))
    service = DeliveryService(oauth, adapter, max_attempts=3)

    result = service.send(message)

    assert result.success is False
    assert result.status == "error"
    assert adapter.send.call_count == 1
