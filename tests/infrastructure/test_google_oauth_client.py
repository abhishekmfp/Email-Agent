"""Tests for GoogleOAuthClient (M5).

OAuth network calls are mocked; the interactive loopback is exercised with a real
local server. Confirms M5 ships NO delivery (send) surface and ends with valid
stored credentials when the full flow runs.
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest

from email_agent.config.settings import GmailSettings
from email_agent.infrastructure.gmail_errors import OAuthError, TokenRefreshError
from email_agent.infrastructure.google_oauth_client import GoogleOAuthClient
from email_agent.infrastructure.oauth_token_store import OAuthTokens, OAuthTokenStore


def _gmail(
    redirect_uri: str = "http://127.0.0.1:8099/",
    request_timeout_seconds: float = 30.0,
) -> GmailSettings:
    return GmailSettings(
        client_id="test-client-id",
        redirect_uri=redirect_uri,
        scopes="https://www.googleapis.com/auth/gmail.send",
        request_timeout_seconds=request_timeout_seconds,
    )


def _store(tmp_path) -> OAuthTokenStore:
    return OAuthTokenStore(tmp_path / "oauth_tokens.json")


class _FakeCreds:
    def __init__(self) -> None:
        self.token = "new-access"
        self.refresh_token = "new-refresh"
        self.token_uri = "https://oauth2.googleapis.com/token"
        self.scopes = ["https://www.googleapis.com/auth/gmail.send"]
        self.expiry = MagicMock()
        self.expiry.timestamp.return_value = time.time() + 3600.0


class _FakeFlow:
    def __init__(self) -> None:
        self.credentials = _FakeCreds()

    @classmethod
    def from_client_config(cls, *_: object, **__: object) -> _FakeFlow:
        return cls()

    def get_authorization_url(self, **_: object) -> tuple[str, str]:
        return "https://accounts.google.com/authorize?...", "state-abc"

    def fetch_token(self, **_: object) -> dict:
        return {"access_token": "new-access"}


# ── URL build (PKCE public client, no secret) ──────────────────────────────
def test_get_authorization_url_returns_url_and_state(tmp_path) -> None:
    client = GoogleOAuthClient(_gmail(), _store(tmp_path))
    with patch("google_auth_oauthlib.flow.Flow.from_client_config", return_value=_FakeFlow()):
        url, state = client.get_authorization_url()
    assert url.startswith("https://accounts.google.com")
    assert state == "state-abc"


# ── code exchange ──────────────────────────────────────────────────────────
def test_exchange_code_for_tokens_persists(tmp_path) -> None:
    store = _store(tmp_path)
    client = GoogleOAuthClient(_gmail(), store)
    with patch("google_auth_oauthlib.flow.Flow.from_client_config", return_value=_FakeFlow()):
        client.get_authorization_url()
        tokens = client.exchange_code_for_tokens("the-code")
    assert tokens.access_token == "new-access"
    assert store.has_valid_tokens() is True


def test_exchange_without_flow_raises(tmp_path) -> None:
    client = GoogleOAuthClient(_gmail(), _store(tmp_path))
    with pytest.raises(OAuthError):
        client.exchange_code_for_tokens("the-code")


# ── refresh ────────────────────────────────────────────────────────────────
def test_refresh_access_token_persists_new_access(tmp_path) -> None:
    store = _store(tmp_path)
    client = GoogleOAuthClient(_gmail(), store)

    class _Creds:
        token = "refreshed-access"
        refresh_token = "keeper-refresh"
        scopes = ["https://www.googleapis.com/auth/gmail.send"]  # noqa: RUF012

        def refresh(self, *args: object, **kwargs: object) -> None:  # google-auth API
            pass

    with (
        patch("google.oauth2.credentials.Credentials", return_value=_Creds()),
        patch("google.auth.transport.requests.Request") as req,
    ):
        req.return_value = None
        tokens = client.refresh_access_token("keeper-refresh")
    assert tokens.access_token == "refreshed-access"
    assert tokens.refresh_token == "keeper-refresh"
    assert store.has_valid_tokens() is True


def test_refresh_enforces_outbound_timeout(tmp_path) -> None:
    """The refresh token-endpoint POST must carry the configured timeout."""
    store = _store(tmp_path)
    client = GoogleOAuthClient(_gmail(request_timeout_seconds=12.5), store)
    seen: dict[str, object] = {}

    class _Creds:
        token = "refreshed-access"
        refresh_token = "keeper-refresh"
        scopes = ["https://www.googleapis.com/auth/gmail.send"]  # noqa: RUF012

        def refresh(self, request: object, *args: object, **kwargs: object) -> None:
            # google-auth invokes the transport callable without an explicit
            # timeout; our wrapper must inject the configured default.
            request("https://oauth2.googleapis.com/token", method="POST")  # type: ignore[operator]

    def _record(*args: object, **kwargs: object) -> object:
        seen["timeout"] = kwargs.get("timeout")
        return None

    with (
        patch("google.oauth2.credentials.Credentials", return_value=_Creds()),
        patch("google.auth.transport.requests.Request", return_value=_record),
    ):
        client.refresh_access_token("keeper-refresh")

    assert seen["timeout"] == 12.5


def test_refresh_failure_clears_store_and_raises(tmp_path) -> None:
    store = _store(tmp_path)
    store.save(OAuthTokens(access_token="x", refresh_token="r", expires_at=time.time() + 10))

    def _boom(*_: object, **__: object) -> None:
        raise RuntimeError("invalid_grant")

    with (
        patch("google.oauth2.credentials.Credentials", return_value=MagicMock()),
        patch("google.auth.transport.requests.Request", side_effect=_boom),
    ):
        with pytest.raises(TokenRefreshError):
            client = GoogleOAuthClient(_gmail(), store)
            client.refresh_access_token("r")
    # Store cleared so delivery cannot proceed with stale/revoked tokens.
    assert store.has_valid_tokens() is False


def test_refresh_if_needed_refreshes_expired(tmp_path) -> None:
    store = _store(tmp_path)
    store.save(OAuthTokens(access_token="old", refresh_token="r", expires_at=time.time() - 10))
    client = GoogleOAuthClient(_gmail(), store)

    class _Creds:
        token = "fresh"
        refresh_token = "r"
        scopes = ["https://www.googleapis.com/auth/gmail.send"]  # noqa: RUF012

        def refresh(self, *args: object, **kwargs: object) -> None:  # google-auth API
            pass

    with (
        patch("google.oauth2.credentials.Credentials", return_value=_Creds()),
        patch("google.auth.transport.requests.Request"),
    ):
        tokens = client.refresh_if_needed()
    assert tokens.access_token == "fresh"


def test_refresh_if_needed_returns_existing_when_valid(tmp_path) -> None:
    store = _store(tmp_path)
    store.save(OAuthTokens(access_token="still-good", expires_at=time.time() + 3600))
    client = GoogleOAuthClient(_gmail(), store)
    tokens = client.refresh_if_needed()
    assert tokens.access_token == "still-good"


def test_refresh_if_needed_raises_without_tokens(tmp_path) -> None:
    client = GoogleOAuthClient(_gmail(), _store(tmp_path))
    with pytest.raises(OAuthError):
        client.refresh_if_needed()


# ── full interactive flow (D5/D7) — browser bypassed via code_provider ─────
def test_authenticate_runs_full_flow_and_persists(tmp_path) -> None:
    store = _store(tmp_path)
    client = GoogleOAuthClient(_gmail(), store)

    def provider(url: str, state: str) -> str:
        assert url.startswith("https://accounts.google.com")
        assert state == "state-abc"
        return "captured-code"

    with patch("google_auth_oauthlib.flow.Flow.from_client_config", return_value=_FakeFlow()):
        tokens = client.authenticate(code_provider=provider)
    assert tokens.access_token == "new-access"
    assert store.has_valid_tokens() is True


def test_authenticate_reuses_existing_valid_tokens(tmp_path) -> None:
    store = _store(tmp_path)
    store.save(OAuthTokens(access_token="already", expires_at=time.time() + 3600))
    client = GoogleOAuthClient(_gmail(), store)
    tokens = client.authenticate(code_provider=lambda u, s: "should-not-run")
    assert tokens.access_token == "already"


# ── real loopback callback capture (state validation) ──────────────────────
def test_capture_callback_returns_code_on_valid_state(tmp_path) -> None:
    import threading
    import time
    import urllib.request

    client = GoogleOAuthClient(_gmail(), _store(tmp_path))

    def hit() -> None:
        time.sleep(0.2)  # let the loopback server start listening
        urllib.request.urlopen("http://127.0.0.1:8099/?code=abc123&state=state-xyz", timeout=5)

    t = threading.Thread(target=hit)
    t.start()
    code = client._capture_authorization_code("http://127.0.0.1:8099/", "state-xyz", timeout=5)
    t.join(timeout=5)
    assert code == "abc123"


def test_capture_callback_rejects_state_mismatch(tmp_path) -> None:
    import threading
    import time
    import urllib.request

    client = GoogleOAuthClient(_gmail(), _store(tmp_path))

    def hit() -> None:
        time.sleep(0.2)  # let the loopback server start listening
        try:
            urllib.request.urlopen("http://127.0.0.1:8099/?code=abc123&state=WRONG", timeout=5)
        except Exception:
            pass

    t = threading.Thread(target=hit)
    t.start()
    with pytest.raises(OAuthError):
        client._capture_authorization_code("http://127.0.0.1:8099/", "state-xyz", timeout=5)
    t.join(timeout=5)


# ── scope guard: M5 ships NO delivery surface ──────────────────────────────
def test_no_delivery_surface_in_m5(tmp_path) -> None:
    client = GoogleOAuthClient(_gmail(), _store(tmp_path))
    assert not hasattr(client, "send")
    assert not hasattr(client, "send_email")
    # The client must not expose any Gmail send path; delivery is M6's concern.
    assert "send" not in dir(client) or not callable(getattr(client, "send", None))
