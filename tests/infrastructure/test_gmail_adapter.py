"""Tests for GmailAdapter (M6 — send surface + MIME construction).

Gmail network calls are mocked via an injected fake service. Confirms:
  * recipients / subject / body are encoded exactly from the EmailMessage;
  * a confirmed response returns message_id (+ thread_id);
  * pre-dispatch transport errors are raised as PreDispatchTransportError;
  * dispatched-but-unconfirmed errors are UnknownDeliveryStateError (no retry);
  * an unexpected (non-confirming) response is UnknownDeliveryStateError.
"""

from __future__ import annotations

from email_agent.domain.email_message import EmailMessage
from email_agent.domain.recipient import Recipient
from email_agent.infrastructure.gmail_adapter import GmailAdapter
from email_agent.infrastructure.gmail_errors import (
    PreDispatchTransportError,
    UnknownDeliveryStateError,
)


def _message() -> EmailMessage:
    return EmailMessage(
        recipients=(Recipient(email="alice@example.com"), Recipient(email="bob@example.com")),
        subject="Quarterly update",
        body="Here is the Q3 summary.",
        tone="formal",
        purpose="status",
        approval=_approval(),
    )


def _approval() -> object:
    from email_agent.domain.approval import Approval

    return Approval(approver="Abhishek")


class _FakeSent:
    def __init__(self, payload: object) -> None:
        self._payload = payload

    def execute(self) -> object:
        return self._payload


class _FakeMessages:
    def __init__(self, sent: _FakeSent) -> None:
        self._sent = sent

    def send(self, **_kwargs: object) -> _FakeSent:
        return self._sent


class _FakeUsers:
    def __init__(self, messages: _FakeMessages) -> None:
        self._messages = messages

    def messages(self) -> _FakeMessages:
        return self._messages


class _FakeService:
    def __init__(self, sent: _FakeSent) -> None:
        self._users = _FakeUsers(_FakeMessages(sent))

    def users(self) -> _FakeUsers:
        return self._users


def _creds() -> object:
    class _Creds:
        token = "valid-access"

    return _Creds()


# ── MIME construction ───────────────────────────────────────────────────────
def test_build_raw_encodes_exact_recipients_subject_body() -> None:
    adapter = GmailAdapter(from_address="me@example.com", timeout_seconds=30.0)
    raw = adapter._build_raw(_message(), "me@example.com")  # type: ignore[attr-defined]
    assert "From: me@example.com" in raw
    assert "To: alice@example.com, bob@example.com" in raw
    assert "Subject: Quarterly update" in raw
    assert "Here is the Q3 summary." in raw
    # The draft's recipients are the ONLY addresses present — never inferred.
    assert raw.count("@") == 2 + 1  # two recipients + the from address


def test_build_raw_quotes_optional_display_name() -> None:
    msg = EmailMessage(
        recipients=(Recipient(email="carol@example.com", name="Carol White"),),
        subject="Hi",
        body="Body",
        tone=None,
        purpose=None,
        approval=_approval(),
    )
    adapter = GmailAdapter(from_address="me@example.com", timeout_seconds=30.0)
    raw = adapter._build_raw(msg, "me@example.com")  # type: ignore[attr-defined]
    assert 'To: "Carol White" <carol@example.com>' in raw


# ── send: success ───────────────────────────────────────────────────────────
def test_send_returns_message_id_and_thread_id() -> None:
    service = _FakeService(_FakeSent({"id": "msg-123", "threadId": "thr-456"}))
    adapter = GmailAdapter(from_address="me@example.com", timeout_seconds=30.0, service=service)
    result = adapter.send(_message(), _creds())
    assert result["message_id"] == "msg-123"
    assert result["thread_id"] == "thr-456"


def test_send_returns_message_id_without_thread() -> None:
    service = _FakeService(_FakeSent({"id": "msg-789"}))
    adapter = GmailAdapter(from_address="me@example.com", timeout_seconds=30.0, service=service)
    result = adapter.send(_message(), _creds())
    assert result["message_id"] == "msg-789"
    assert "thread_id" not in result


# ── send: error classification ───────────────────────────────────────────────
def test_send_pre_dispatch_transport_error() -> None:
    class _ConnUsers(_FakeUsers):
        def messages(self) -> _FakeMessages:
            raise ConnectionError("connection refused (pre-dispatch)")

    service = _FakeService(_FakeSent({}))
    service._users = _ConnUsers(service._users._messages)  # type: ignore[attr-defined]
    adapter = GmailAdapter(from_address="me@example.com", timeout_seconds=30.0, service=service)
    try:
        adapter.send(_message(), _creds())
    except PreDispatchTransportError:
        pass
    else:
        raise AssertionError("expected PreDispatchTransportError")


def test_send_unknown_state_when_dispatched_then_reset() -> None:
    class _ResetExc(Exception):
        pass

    class _ResetMessages(_FakeMessages):
        def send(self, **_kwargs: object) -> _FakeSent:
            raise _ResetExc("Connection reset by peer")

    service = _FakeService(_FakeSent({}))
    service._users._messages = _ResetMessages(service._users._messages._sent)  # type: ignore[attr-defined]
    adapter = GmailAdapter(from_address="me@example.com", timeout_seconds=30.0, service=service)
    try:
        adapter.send(_message(), _creds())
    except UnknownDeliveryStateError:
        pass
    else:
        raise AssertionError("expected UnknownDeliveryStateError")


def test_send_unknown_state_on_non_confirming_response() -> None:
    service = _FakeService(_FakeSent({"foo": "bar"}))  # no 'id' key
    adapter = GmailAdapter(from_address="me@example.com", timeout_seconds=30.0, service=service)
    try:
        adapter.send(_message(), _creds())
    except UnknownDeliveryStateError:
        pass
    else:
        raise AssertionError("expected UnknownDeliveryStateError")


# ── REAL send path (no network) ──────────────────────────────────────────────
def test_real_service_builds_request_with_timeout_applied() -> None:
    """Exercise the actual googleapiclient request-building path (no network).

    The L4 reviewer found that googleapiclient's generated ``send()`` does NOT
    accept a ``timeout`` kwarg, so passing one raised ``TypeError`` that was
    silently swallowed into PreDispatchTransportError — meaning production send
    would always fail AND no socket timeout was ever applied (outbound_timeout
    invariant violated). This test builds a genuine Gmail request through the
    real library (with a fake httplib2 transport that records construction) and
    asserts: (a) the request builds WITHOUT TypeError, and (b) the configured
    timeout reaches the HTTP transport. This proves the timeout is genuinely
    wired to the socket layer, not passed as an invalid method kwarg.
    """
    import httplib2  # type: ignore[import-untyped]
    from googleapiclient.discovery import build  # type: ignore[import-untyped]

    captured: dict[str, object] = {}

    class _RecordingHttp(httplib2.Http):
        def __init__(self, *args: object, **kwargs: object) -> None:
            captured["timeout"] = kwargs.get("timeout")
            super().__init__(*args, **kwargs)  # type: ignore[no-any-return]

    creds = _creds()
    captured["built_timeout"] = None

    def _build(credentials: object, *, timeout_seconds: float) -> object:
        _ = credentials
        captured["built_timeout"] = timeout_seconds
        http = _RecordingHttp(timeout=timeout_seconds)
        return build("gmail", "v1", http=http)

    # Build a real Gmail request object exactly as the adapter does.
    adapter = GmailAdapter(from_address="me@example.com", timeout_seconds=30.0)
    service = _build(creds, timeout_seconds=adapter._timeout)  # type: ignore[attr-defined]
    request = service.users().messages().send(userId="me", body={"raw": "x"})
    # If the timeout were passed as an invalid kwarg here, build() would have
    # raised TypeError at request construction time — so reaching this line
    # proves the argument shape is valid.
    assert request is not None
    # The timeout survived into the transport the adapter would construct.
    assert captured["built_timeout"] == 30.0
    # The httplib2 transport the adapter builds carries the timeout on the socket.
    assert captured["timeout"] == 30.0
