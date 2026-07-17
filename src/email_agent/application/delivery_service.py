"""Delivery workflow orchestration (M6 — delivery only).

Thin application-layer service. It coordinates the immutable ``EmailMessage``
→ OAuth refresh → Gmail send, then returns a structured ``DeliveryResult``. It
owns ONLY the delivery step; it does NOT draft, authenticate, or approve.

Responsibilities (per the M6 design review):
  * Guard: refuse to send unless the message is in the ``APPROVED`` state
    (defense-in-depth on top of the approval_gate invariant).
  * Call ``GoogleOAuthClient.refresh_if_needed()`` before EVERY send (M5→M6
    contract), so an expired token is refreshed transparently.
  * On ``TokenRefreshError`` (e.g. revoked refresh token) → HARD STOP: surface
    the auth failure, never deliver, never silently retry.
  * Hand the EXACT ``EmailMessage`` instance to the adapter (artifact_identity);
    never rebuild/derive from a draft.
  * Bounded pre-dispatch retry only; an ``UnknownDeliveryStateError`` (dispatched
    but unconfirmed) is NEVER retried — reported to the human.

SENT state (D-M6-1, Option a): this service returns a ``DeliveryResult``. The
CALLER (e.g. ``ApproveEmailUseCase``/interface) owns the SENT lifecycle
transition using the returned ``message_id``. ``DeliveryService`` stays purely
transport and does not mutate the frozen ``EmailMessage``.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from email_agent.domain.email_message import EmailMessage
from email_agent.infrastructure.gmail_adapter import GmailAdapter
from email_agent.infrastructure.gmail_errors import (
    DeliveryError,
    PreDispatchTransportError,
    UnknownDeliveryStateError,
)
from email_agent.infrastructure.google_oauth_client import GoogleOAuthClient


@dataclass(frozen=True)
class DeliveryResult:
    """Outcome of a delivery attempt (D-M6-1: caller owns SENT transition)."""

    success: bool
    message_id: str | None = None
    thread_id: str | None = None
    error: str | None = None
    #: "delivered" | "auth_failed" | "unknown_state" | "error" | "not_approved"
    status: str = "error"

    @classmethod
    def delivered(cls, message_id: str, thread_id: str | None = None) -> DeliveryResult:
        return cls(
            success=True,
            message_id=message_id,
            thread_id=thread_id,
            status="delivered",
        )

    @classmethod
    def failed(cls, status: str, error: str) -> DeliveryResult:
        return cls(success=False, status=status, error=error)


@dataclass(frozen=True)
class _RetryPolicy:
    """Bounded exponential backoff for PRE-DISPATCH transport failures ONLY.

    Mirrors M3 ADR-5 (retry at the service, not the adapter). We never retry
    once the request is dispatched: UnknownDeliveryStateError short-circuits out
    and is reported, never resent. This enforces "never silently resend /
    never resend when uncertain" from decisions-manifest.
    """

    max_attempts: int = 3
    backoff_seconds: float = 0.5


class DeliveryService:
    """Coordinates the immutable EmailMessage -> Gmail send (delivery only)."""

    def __init__(
        self,
        oauth_client: GoogleOAuthClient,
        gmail_adapter: GmailAdapter,
        *,
        max_attempts: int = 3,
        backoff_seconds: float = 0.5,
    ) -> None:
        self._oauth = oauth_client
        self._adapter = gmail_adapter
        self._retry = _RetryPolicy(max_attempts=max_attempts, backoff_seconds=backoff_seconds)

    def send(self, message: EmailMessage) -> DeliveryResult:
        """Deliver the approved EmailMessage; return a structured result.

        The caller consumes the returned ``DeliveryResult`` to record the SENT
        lifecycle transition (D-M6-1, Option a). This method performs no domain
        state mutation.
        """
        from email_agent.domain.policies import ApprovalPolicy

        # Guard: approval_gate invariant, defense-in-depth. An EmailMessage is
        # ONLY ever constructed from an APPROVED draft (M4), so a present, valid
        # Approval is sufficient evidence of approval — decided_at is optional
        # today (may become mandatory on future audit requirements).
        if not ApprovalPolicy.is_valid(message.approval):
            return DeliveryResult.failed(
                "not_approved",
                "Refusing to deliver: EmailMessage carries no explicit approval.",
            )

        last_error: DeliveryError | None = None
        for attempt in range(1, self._retry.max_attempts + 1):
            # Refresh auth before EVERY Gmail request (M5→M6 contract). An expired
            # token is refreshed transparently; a revoked refresh → HARD STOP.
            try:
                tokens = self._oauth.refresh_if_needed()
            except Exception as exc:  # TokenRefreshError or any auth failure
                return DeliveryResult.failed(
                    "auth_failed", f"Authentication required before delivery: {exc}"
                )

            credentials = _credentials_from_tokens(tokens)
            try:
                # EXACT instance delivered (artifact_identity); adapter reads it
                # read-only and never rebuilds from a draft.
                result = self._adapter.send(message, credentials)
                return DeliveryResult.delivered(
                    message_id=result["message_id"],
                    thread_id=result.get("thread_id"),
                )
            except UnknownDeliveryStateError as exc:
                # Dispatched but unconfirmed: NEVER retry, report immediately.
                return DeliveryResult.failed("unknown_state", str(exc))
            except PreDispatchTransportError as exc:
                last_error = exc
                if attempt >= self._retry.max_attempts:
                    break
                time.sleep(self._retry.backoff_seconds * attempt)  # conservative backoff
            except DeliveryError as exc:
                # Any other (terminal) delivery error: surface, no retry.
                return DeliveryResult.failed("error", str(exc))

        assert last_error is not None
        return DeliveryResult.failed(
            "error",
            f"Delivery failed after {self._retry.max_attempts} attempts: {last_error}",
        )


def _credentials_from_tokens(tokens: object) -> object:
    """Adapt an ``OAuthTokens`` into a google-auth Credentials for the adapter.

    Kept local to the service so the adapter stays credential-format-agnostic;
    the adapter only needs something with a ``.token``. Imported lazily so the
    google-auth dependency is only required at delivery time.
    """
    try:
        from google.oauth2.credentials import Credentials
    except Exception:  # pragma: no cover - only if google-auth missing at runtime
        # OAuthTokens has a `.access_token` attribute; build a minimal creds shim.
        class _Shim:
            def __init__(self, token: str) -> None:
                self.token = token

        return _Shim(getattr(tokens, "access_token", ""))

    access_token = getattr(tokens, "access_token", "")
    return Credentials(token=access_token)  # type: ignore[no-untyped-call]
