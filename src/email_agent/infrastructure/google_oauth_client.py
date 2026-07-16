"""Google OAuth client — owns all Gmail OAuth operations (M5).

This is the single OAuth boundary. It builds the consent URL (PKCE public
client), exchanges the authorization code for tokens, refreshes access tokens,
and — per the M5 design decision D5/D7 — runs the COMPLETE interactive flow
(browser launch + local loopback callback + code capture) so that M5 ends with
valid stored credentials. Gmail *delivery* is a separate concern introduced in
M6 and is deliberately absent here.

Security/invariant mapping:
- secrets_hygiene: client secret is absent (PKCE public client); token material
  is handled only by ``OAuthTokenStore`` and never logged here.
- outbound_timeout: every token-endpoint call passes an explicit timeout
  (mirrors the M3 AnthropicAdapter).
- approval_gate / artifact_identity: untouched — no send path exists in M5.
"""

from __future__ import annotations

import logging
import secrets
import threading
import time
import webbrowser
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

from email_agent.config.settings import GmailSettings
from email_agent.infrastructure.gmail_errors import OAuthError, TokenRefreshError
from email_agent.infrastructure.oauth_token_store import OAuthTokens, OAuthTokenStore

logger = logging.getLogger(__name__)


def _client_config(gmail: GmailSettings) -> dict[str, object]:
    """Build the google-auth-oauthlib client_config dict (no secret — PKCE)."""
    return {
        "web": {
            "client_id": gmail.client_id,
            "auth_uri": gmail.auth_uri,
            "token_uri": gmail.token_uri,
            "redirect_uris": [gmail.redirect_uri],
        }
    }


class GoogleOAuthClient:
    """OAuth operations for Gmail authentication (M5: auth only, no delivery)."""

    def __init__(
        self,
        gmail: GmailSettings,
        store: OAuthTokenStore,
        refresh_slack_seconds: float = 60.0,
    ) -> None:
        self._gmail = gmail
        self._store = store
        self._refresh_slack = refresh_slack_seconds
        self._scopes = gmail.scopes.split()
        # The in-progress Flow is retained between URL build and code exchange so
        # the PKCE verifier stays consistent. It is a per-instance, non-secret value.
        # Typed loosely because the google-auth Flow class is untyped; we only
        # touch it through this module.
        self._flow: Any | None = None

    # ── primitives (fully unit-testable) ───────────────────────────────────
    def get_authorization_url(self) -> tuple[str, str]:
        """Return ``(authorization_url, state)`` for the consent screen.

        Uses the PKCE "Desktop app" flow: no client secret is sent or stored.
        """
        from google_auth_oauthlib.flow import Flow  # type: ignore[import-untyped]

        code_verifier = secrets.token_urlsafe(64)
        flow = Flow.from_client_config(
            _client_config(self._gmail),
            scopes=self._scopes,
            redirect_uri=self._gmail.redirect_uri,
            code_verifier=code_verifier,
        )
        authorization_url, state = flow.get_authorization_url(
            prompt="consent", access_type="offline"
        )
        self._flow = flow
        return authorization_url, state

    def exchange_code_for_tokens(self, code: str) -> OAuthTokens:
        """Exchange an authorization code for tokens and persist them."""
        if self._flow is None:
            raise OAuthError("No active OAuth flow; call get_authorization_url() first.")
        try:
            self._flow.fetch_token(code=code, timeout=self._gmail.request_timeout_seconds)
        except Exception as exc:  # google lib raises various; wrap uniformly
            raise OAuthError(f"Token exchange failed: {exc}") from exc
        tokens = OAuthTokens(
            access_token=self._flow.credentials.token or "",
            refresh_token=self._flow.credentials.refresh_token,
            token_type="Bearer",
            expires_at=time.time() + float(self._flow.credentials.expiry.timestamp())
            if self._flow.credentials.expiry
            else 0.0,
            scopes=list(self._flow.credentials.scopes or self._scopes),
        )
        self._store.save(tokens)
        return tokens

    def refresh_access_token(self, refresh_token: str) -> OAuthTokens:
        """Refresh the access token from a refresh token and persist it."""
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials

        creds = Credentials(  # type: ignore[no-untyped-call]
            token=None,
            refresh_token=refresh_token,
            client_id=self._gmail.client_id,
            token_uri=self._gmail.token_uri,
            scopes=self._scopes,
        )
        # google-auth's Credentials.refresh() does not forward a timeout to the
        # token-endpoint POST, so we wrap the transport callable to inject an
        # explicit deadline. This satisfies the outbound_timeout invariant on the
        # refresh path (mirrors the timeout passed to fetch_token on exchange).
        default_timeout = self._gmail.request_timeout_seconds

        try:
            transport = Request()

            def _timed_request(*args: Any, **kwargs: Any) -> Any:
                if kwargs.get("timeout") is None:
                    kwargs["timeout"] = default_timeout
                return transport(*args, **kwargs)

            creds.refresh(_timed_request)  # type: ignore[no-untyped-call]
        except Exception as exc:  # google lib raises various; wrap uniformly
            self._store.clear()
            raise TokenRefreshError(f"Token refresh failed: {exc}") from exc
        tokens = OAuthTokens(
            access_token=creds.token or "",
            refresh_token=refresh_token,  # refresh token is reused
            token_type="Bearer",
            expires_at=time.time() + 3600.0,  # default 1h grant
            scopes=list(creds.scopes or self._scopes),
        )
        self._store.save(tokens)
        return tokens

    def refresh_if_needed(self) -> OAuthTokens:
        """Return valid tokens, refreshing first if the stored ones are expired.

        M6 calls this before delivery; it is an OAuth operation, not delivery.
        """
        tokens = self._store.load()
        if tokens is None:
            raise OAuthError("No stored tokens; run authenticate() first.")
        if not tokens.is_expired(self._refresh_slack):
            return tokens
        if tokens.refresh_token is None:
            self._store.clear()
            raise TokenRefreshError("Access token expired and no refresh token available.")
        return self.refresh_access_token(tokens.refresh_token)

    # ── complete interactive flow (D5/D7) ──────────────────────────────────
    def authenticate(self, code_provider: Callable[[str, str], str] | None = None) -> OAuthTokens:
        """Run the full interactive OAuth flow and return valid stored tokens.

        If valid tokens already exist, they are returned immediately (no browser).
        Otherwise the consent URL is opened in the browser and the authorization
        code is captured via the local loopback callback. A ``code_provider``
        callable ``(url, state) -> code`` may be injected to bypass the browser
        (used by tests); when None, the real browser + loopback is used.

        M5 ends here with valid credentials persisted to ``OAuthTokenStore``.
        """
        existing = self._store.load()
        if existing is not None and not existing.is_expired(self._refresh_slack):
            return existing
        url, state = self.get_authorization_url()
        if code_provider is not None:
            code = code_provider(url, state)
        else:
            webbrowser.open(url)
            code = self._capture_authorization_code(self._gmail.redirect_uri, state)
        return self.exchange_code_for_tokens(code)

    def _capture_authorization_code(
        self, redirect_uri: str, expected_state: str, timeout: float = 120.0
    ) -> str:
        """Run a one-shot local loopback server and return the ``code`` query param.

        Validates the ``state`` CSRF token (must match the one from
        ``get_authorization_url``). Raises ``OAuthError`` on mismatch or missing code.
        """
        parsed = urlparse(redirect_uri)
        host = parsed.hostname or "localhost"
        port = parsed.port or 8080
        captured: dict[str, str] = {}

        class _Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                qs = parse_qs(urlparse(self.path).query)
                if qs.get("state", [None])[0] != expected_state:
                    captured["error"] = "state_mismatch"
                    self.send_response(400)
                    self.end_headers()
                    return
                code = qs.get("code", [None])[0]
                if code is None:
                    captured["error"] = "missing_code"
                    self.send_response(400)
                    self.end_headers()
                    return
                captured["code"] = code
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"Authentication complete. You may close this window.")

            def log_message(self, *args: object) -> None:  # silence default stderr logging
                pass

        server = HTTPServer((host, port), _Handler)
        server.timeout = timeout
        server_thread = threading.Thread(target=server.handle_request, daemon=True)
        server_thread.start()
        server_thread.join(timeout=timeout)
        if "error" in captured:
            raise OAuthError(f"OAuth callback error: {captured['error']}")
        if "code" not in captured:
            raise OAuthError("OAuth callback timed out before returning a code")
        return captured["code"]
