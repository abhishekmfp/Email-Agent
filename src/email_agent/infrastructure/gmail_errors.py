"""Errors raised by the Gmail infrastructure (M5 OAuth + M6 delivery).

Kept separate from the domain exceptions so the infrastructure boundary has its
own error vocabulary. Per the secrets_hygiene invariant, none of these carry
token material, recipient addresses, email bodies, or prompts in their message.
"""

from __future__ import annotations


class OAuthError(Exception):
    """Base class for all OAuth/token failures in the Gmail auth path."""


class TokenRefreshError(OAuthError):
    """Raised when an access token cannot be refreshed.

    Typically triggered by a revoked/expired refresh token (Google returns
    ``invalid_grant``). Callers should treat this as "re-authentication required".
    """


class DeliveryError(OAuthError):
    """Base class for Gmail delivery (send) failures (M6).

    A DeliveryError means the send attempt did not result in a confirmed
    successful delivery. Subtypes distinguish *pre-dispatch* failures (safe to
    retry) from *post-dispatch* uncertainty (never retry).
    """


class PreDispatchTransportError(DeliveryError):
    """Send failed BEFORE the request was dispatched / acknowledged.

    Covers connection errors, DNS failures, and timeouts that occur before the
    Gmail API confirms it received the message. Because nothing was sent, this
    failure is safe for the bounded pre-dispatch retry policy.
    """


class UnknownDeliveryStateError(DeliveryError):
    """The send request was dispatched but its outcome is unconfirmed.

    Examples: the connection dropped after dispatch with no response, or a 5xx
    arrived without a message id. By the decisions-manifest partial-failure
    rule, this is REPORTED and NEVER auto-resent — the human verifies delivery.
    """
