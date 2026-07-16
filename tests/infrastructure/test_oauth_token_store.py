"""Tests for OAuthTokenStore (M5).

Focus: persistence round-trip, expiry logic, has_valid_tokens() convenience gate,
file perms, and the hard rule that token bytes never reach logs.
"""

from __future__ import annotations

import os
import sys
import time

import pytest

from email_agent.infrastructure.oauth_token_store import OAuthTokens, OAuthTokenStore


def _tokens(expires_in: float = 3600.0) -> OAuthTokens:
    return OAuthTokens(
        access_token="access-secret",
        refresh_token="refresh-secret",
        token_type="Bearer",
        expires_at=time.time() + expires_in,
        scopes=["https://www.googleapis.com/auth/gmail.send"],
    )


def test_save_then_load_roundtrip(tmp_path) -> None:
    store = OAuthTokenStore(tmp_path / "oauth_tokens.json")
    store.save(_tokens())
    loaded = store.load()
    assert loaded is not None
    assert loaded.access_token == "access-secret"
    assert loaded.refresh_token == "refresh-secret"
    assert loaded.scopes == ["https://www.googleapis.com/auth/gmail.send"]


def test_load_returns_none_when_absent(tmp_path) -> None:
    store = OAuthTokenStore(tmp_path / "missing.json")
    assert store.load() is None


def test_has_valid_tokens_true_when_fresh(tmp_path) -> None:
    store = OAuthTokenStore(tmp_path / "oauth_tokens.json")
    store.save(_tokens(expires_in=3600))
    assert store.has_valid_tokens() is True


def test_has_valid_tokens_false_when_expired(tmp_path) -> None:
    store = OAuthTokenStore(tmp_path / "oauth_tokens.json")
    store.save(_tokens(expires_in=-10))  # already expired
    assert store.has_valid_tokens() is False


def test_has_valid_tokens_false_when_absent(tmp_path) -> None:
    store = OAuthTokenStore(tmp_path / "missing.json")
    assert store.has_valid_tokens() is False


def test_is_expired_within_slack(tmp_path) -> None:
    store = OAuthTokenStore(tmp_path / "oauth_tokens.json", refresh_slack_seconds=60)
    store.save(_tokens(expires_in=30))  # 30s left < 60s slack
    assert store.is_expired() is True


def test_clear_removes_file(tmp_path) -> None:
    store = OAuthTokenStore(tmp_path / "oauth_tokens.json")
    store.save(_tokens())
    assert store.path.exists()
    store.clear()
    assert store.load() is None


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX file perms only")
def test_token_file_is_0600(tmp_path) -> None:
    store = OAuthTokenStore(tmp_path / "oauth_tokens.json")
    store.save(_tokens())
    mode = os.stat(store.path).st_mode & 0o777
    assert mode == 0o600


def test_token_bytes_never_logged(tmp_path, caplog) -> None:
    import logging

    store = OAuthTokenStore(tmp_path / "oauth_tokens.json")
    with caplog.at_level(logging.INFO):
        store.save(_tokens())
        store.load()
    blob = caplog.text
    assert "access-secret" not in blob
    assert "refresh-secret" not in blob
