"""Tests for the interface logging/masking utility and the error envelope.

Confirms (M7 decision #5 + #7):
- recipients are masked in structured logs (never plaintext addresses).
- secrets (tokens/credentials/api_key/secret/password) are redacted.
- email bodies / prompts are NOT logged (callers must not pass them).
- the error envelope is {code, message, detail?} and never leaks secrets.
- un-typed exceptions map to a generic internal_error with no secret leakage.
"""

from __future__ import annotations

import logging

from email_agent.application.send_email_use_case import SendResult
from email_agent.interface.errors import (
    AuthRequiredError,
    InterfaceError,
    ValidationError,
    draft_result_error,
    internal_error,
    send_result_error,
    translate_delivery,
)
from email_agent.interface.logging import mask_email, mask_recipients, safe_log


class _CaptureHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


def test_mask_recipients_redacts_partially():
    masked = mask_recipients(["alice@example.com", "bob@work.org"])
    assert all("***" in m for m in masked)
    assert "alice@example.com" not in masked[0]
    assert "bob@work.org" not in masked[1]


def test_safe_log_masks_secrets_and_recipients():
    handler = _CaptureHandler()
    root = logging.getLogger()
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    try:
        safe_log(
            "draft_received",
            recipients=["alice@example.com"],
            access_token="ya29.secret",
            subject="Hello",
            api_key="sk-123",
        )
        rec = handler.records[0]
        extra = rec.__dict__
        # Sensitive values are redacted/masked in the record's extra fields.
        assert "alice@example.com" not in str(extra)
        assert "ya29.secret" not in str(extra)
        assert "sk-123" not in str(extra)
        assert "***REDACTED***" in str(extra)
    finally:
        root.removeHandler(handler)


def test_safe_log_does_not_emit_plaintext_recipients():
    handler = _CaptureHandler()
    root = logging.getLogger()
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    try:
        safe_log("draft_received", recipients=["alice@example.com"], prompt="secret prompt")
        rec = handler.records[0]
        extra = rec.__dict__
        assert "alice@example.com" not in str(extra)
        assert "secret prompt" not in str(extra)  # prompt must not appear
    finally:
        root.removeHandler(handler)


def test_mask_email_partial():
    assert mask_email("alice@example.com") == "a***@example.com"


def test_error_envelope_shape():
    err = ValidationError("bad input")
    assert isinstance(err, InterfaceError)
    body = err.to_dto()
    assert set(body.model_dump().keys()) == {"code", "message", "detail"}
    assert body.code == "validation_error"
    assert body.message == "bad input"
    assert body.detail is None


def test_auth_required_envelope():
    err = AuthRequiredError("re-auth", detail={"provider": "google"})
    body = err.to_dto()
    assert body.code == "auth_required"
    assert body.detail == {"provider": "google"}


def test_internal_error_generic_message():
    exc = RuntimeError("OAuth client secret=xyz exposed in traceback")
    body = internal_error(exc)
    assert body.code == "internal_error"
    # Message is generic — must not leak the exception text / secrets.
    assert "secret=xyz" not in body.message
    assert "OAuth client" not in body.message


def test_send_result_error_auth_failed_does_not_leak_upstream_error():
    # Defense-in-depth: even if a SendResult carries a raw infra error that may
    # echo token/account hints, the auth_failed envelope uses a FIXED message.
    result = SendResult(
        status="AUTH_FAILED",
        error="token=ya29.secret account=suspended",
        detail={"delivery_status": "auth_failed"},
    )
    body = send_result_error(result).to_dto()
    assert body.code == "auth_required"
    assert "ya29.secret" not in body.message
    assert "account=suspended" not in body.message
    assert body.detail == {"delivery_status": "auth_failed"}


def test_send_result_error_other_branches_surfaced():
    ok = send_result_error(SendResult(status="UNKNOWN_STATE", error="200/DRAFT")).to_dto()
    assert ok.code == "delivery_unknown_state"
    assert "200/DRAFT" in ok.message


def test_translate_delivery_unknown_state():
    body = translate_delivery("unknown_state", "gmail said 200/DRAFT")
    assert body.code == "delivery_unknown_state"
    # Safe infra message is surfaced so the operator can verify before retry.
    assert "gmail said 200/DRAFT" in body.message


def test_draft_result_error_envelope():
    result = type("R", (), {"status": "ERROR", "error": "missing recipients"})()
    body = draft_result_error(result)
    assert body.code == "draft_error"
    assert body.message == "missing recipients"
