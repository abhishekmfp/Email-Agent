"""Gmail delivery adapter (M6 — delivery only).

Concrete Gmail provider adapter behind a narrow port used only by
``DeliveryService``. Per the locked architecture and the M6 design review it:

  * is invoked ONLY from ``DeliveryService``, which is ONLY called after a
    deterministic ``APPROVED`` state (approval_gate invariant);
  * translates the immutable ``EmailMessage`` into the Gmail API wire format
    (a base64url-encoded RFC822 message) and sends it once;
  * sets an explicit timeout on every outbound call (outbound_timeout invariant);
  * owns NO OAuth, NO approval policy, and NO business rules — it reads the
    ``EmailMessage`` read-only and is handed already-validated credentials;
  * does NOT retry; retry policy lives in ``DeliveryService`` (bounded,
    pre-dispatch only) — mirroring M3 ADR-5 (retry at the service, not adapter).

MIME construction lives HERE, not in a dedicated ``MimeMessageBuilder``.
Rationale (documented per the approved D-M6 decision): V1 has exactly one
email provider and one message shape. A separate builder would be a
speculative abstraction with no second caller, violating the project's
"extract abstractions only after multiple concrete implementations" rule.
The build is a small, pure static method (``_build_raw``); should a second
provider or HTML/multipart need arise, it is the obvious extraction point.

Secret hygiene: this adapter never logs recipient addresses, bodies, prompts,
or token material; the ``from_address`` is derived from config, not the draft.
"""

from __future__ import annotations

import base64
from email.mime.text import MIMEText
from typing import Any

from email_agent.domain.email_draft import EmailDraft
from email_agent.domain.email_message import EmailMessage
from email_agent.infrastructure.gmail_errors import (
    PreDispatchTransportError,
    UnknownDeliveryStateError,
)

# Read-only view of the message this adapter is allowed to deliver.
_MessageLike = EmailDraft | EmailMessage


def _format_recipient(recipient: Any) -> str:
    """Render a Recipient as an RFC822 address; name is optional display text.

    The address is taken verbatim from the value object (never inferred). The
    optional ``name`` is wrapped in quotes only when present and needed for
    display; it is never used for routing.
    """
    email = recipient.email
    name = getattr(recipient, "name", None)
    if name:
        # Quote display names containing separators/spaces per RFC 5322 §3.4.
        safe = name.replace('"', "")
        return f'"{safe}" <{email}>'
    return str(email)


class GmailAdapter:
    """Sends an immutable EmailMessage through the Gmail API (send surface only)."""

    def __init__(
        self,
        from_address: str,
        timeout_seconds: float,
        *,
        service: Any | None = None,
    ) -> None:
        """Construct the adapter.

        Args:
            from_address: the authenticated account's send address. Sourced from
                config/credentials, never from the draft (trust boundary).
            timeout_seconds: explicit per-request timeout for the Gmail send call
                (outbound_timeout invariant).
            service: an injected ``googleapiclient.discovery.Resource`` (the
                ``gmail.users().messages()`` service). When None, a real service
                is built from the credentials at send time. Tests inject a fake.
        """
        self._from_address = from_address
        self._timeout = timeout_seconds
        self._service = service

    @staticmethod
    def _build_raw(message: _MessageLike, from_address: str) -> str:
        """Build the RFC822 raw message string from the immutable EmailMessage.

        Pure, side-effect-free, and provider-agnostic as far as the domain is
        concerned: the domain stays MIME-unaware (domain_inward invariant). All
        recipients come ONLY from the message (never inferred). Encoding errors
        are raised as ``UnicodeError`` so the caller can surface a structured
        error without a partial send.
        """
        body_subtype = "html" if (getattr(message, "purpose", None) == "html") else "plain"
        # Plain text (no _charset) keeps the body human-readable in the wire
        # format; the app's standard is text/plain. HTML is only chosen if the
        # draft explicitly flags purpose="html".
        mime = MIMEText(message.body, body_subtype)
        mime["From"] = from_address
        mime["To"] = ", ".join(_format_recipient(r) for r in message.recipients)
        mime["Subject"] = message.subject
        return mime.as_string()

    def send(
        self,
        message: EmailMessage,
        credentials: Any,
    ) -> dict[str, str]:
        """Send the approved EmailMessage via Gmail. Exactly one request.

        Args:
            message: the immutable, approved EmailMessage to deliver
                (artifact_identity — the exact instance, never rebuilt).
            credentials: a google-auth ``Credentials`` object with a valid access
                token (``DeliveryService`` ensures this via refresh_if_needed).
                The adapter uses it read-only for the duration of the call.

        Returns:
            A dict with at least ``message_id`` (and ``thread_id`` when present),
            extracted from the Gmail API response.

        Raises:
            PreDispatchTransportError: the request failed BEFORE Gmail confirmed
                receipt (connection/timeout/no response). Safe to retry.
            UnknownDeliveryStateError: the request was dispatched but the outcome
                is unconfirmed (e.g. response dropped after dispatch, no message
                id). NEVER auto-resend — reported to the human.
            DeliveryError: any other (terminal) delivery failure.
        """
        raw = self._build_raw(message, self._from_address)
        encoded = base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii")
        body = {"raw": encoded}

        service = self._service or _build_service(credentials, timeout_seconds=self._timeout)
        try:
            sent = service.users().messages().send(userId="me", body=body).execute()
        except Exception as exc:  # google lib raises HttpError(timeout/conn)/socket/timeout
            if _looks_dispatched(exc):
                # The request reached Gmail but the result is unconfirmed.
                raise UnknownDeliveryStateError(
                    f"Send dispatched but delivery outcome unconfirmed: {exc}"
                ) from exc
            # Pre-dispatch: connection refused / timeout before ack — safe to retry.
            raise PreDispatchTransportError(f"Gmail send failed pre-dispatch: {exc}") from exc

        if not isinstance(sent, dict) or "id" not in sent:  # pragma: no cover - defensive
            # We got a response, but it is not the expected confirmed success.
            raise UnknownDeliveryStateError(
                f"Gmail send returned an unexpected/non-confirming response: {sent!r}"
            )
        return {
            "message_id": str(sent["id"]),
            **({"thread_id": str(sent["threadId"])} if sent.get("threadId") else {}),
        }


def _looks_dispatched(exc: Exception) -> bool:
    """Best-effort heuristic: did the request reach Gmail before failing?

    A timeout/connection-reset *after* bytes were written is indistinguishable
    from a clean pre-dispatch failure at the socket layer, so we conservatively
    treat mid-flight transport errors as dispatched (→ UnknownDeliveryState,
    never auto-resend). Pure pre-dispatch errors (name resolution, refused
    connection, explicit socket timeout before any write) are NOT dispatched.
    """
    text = str(exc).lower()
    dispatched_signals = ("reset by peer", "connection aborted", "remote end")
    return any(sig in text for sig in dispatched_signals)


def _build_service(credentials: Any, *, timeout_seconds: float) -> Any:
    """Build a real Gmail API service from validated credentials.

    Imported lazily so the adapter can be unit-tested with an injected fake and
    so google-api-python-client is only required at delivery time.

    The per-request timeout (outbound_timeout invariant) is configured on the
    HTTP transport — googleapiclient's ``execute()``/generated ``send()`` do NOT
    accept a ``timeout`` kwarg (passing one raises ``TypeError``). The socket
    timeout must live on the ``httplib2.Http`` object passed to ``build(http=)``.
    """
    import httplib2  # type: ignore[import-untyped]
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build  # type: ignore[import-untyped]

    if not isinstance(credentials, Credentials):
        credentials = Credentials(token=credentials.token)  # type: ignore[no-untyped-call]
    http = httplib2.Http(timeout=timeout_seconds)
    return build("gmail", "v1", credentials=credentials, http=http)
