"""Errors raised by the Gmail OAuth infrastructure (M5).

Kept separate from the domain exceptions so the infrastructure boundary has its
own error vocabulary. None of these carry token material in their message.
"""

from __future__ import annotations


class OAuthError(Exception):
    """Base class for all OAuth/token failures in the Gmail auth path."""


class TokenRefreshError(OAuthError):
    """Raised when an access token cannot be refreshed.

    Typically triggered by a revoked/expired refresh token (Google returns
    ``invalid_grant``). Callers should treat this as "re-authentication required".
    """
