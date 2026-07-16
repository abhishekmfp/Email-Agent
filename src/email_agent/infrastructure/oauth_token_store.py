"""Secure local storage for Gmail OAuth tokens (M5).

``OAuthTokenStore`` isolates credential persistence behind a dedicated module so
that token material is never scattered across the codebase. It is the single
place that reads/writes the token file.

Security invariants enforced here:
- Token bytes are NEVER logged (no ``log`` calls touch token fields).
- The token file is written with owner-only (0600) permissions and lives OUTSIDE
  the repo tree (caller supplies an absolute path, e.g. ``~/.email-agent/``).
- ``has_valid_tokens()`` is the convenience gate M5 exposes so the rest of the
  app can ask "are we authenticated?" without leaking token internals.
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class OAuthTokens(BaseModel):
    """Typed OAuth token set (mirrors the project's pydantic-typed-data contract)."""

    access_token: str
    refresh_token: str | None = None
    token_type: str = "Bearer"
    # Absolute Unix timestamp (seconds) at which the access token expires.
    expires_at: float = 0.0
    scopes: list[str] = Field(default_factory=list)

    def is_expired(self, slack_seconds: float = 60.0) -> bool:
        """True if the access token is within ``slack_seconds`` of expiry."""
        return time.time() >= (self.expires_at - slack_seconds)


class OAuthTokenStore:
    """Owner of the Gmail OAuth token file.

    Only this class touches the persisted token bytes. Write uses 0600 perms;
    reads never emit token material to logs (only non-secret metadata).
    """

    def __init__(self, path: str | Path, refresh_slack_seconds: float = 60.0) -> None:
        self._path = Path(path)
        self._refresh_slack = refresh_slack_seconds

    @property
    def path(self) -> Path:
        return self._path

    def save(self, tokens: OAuthTokens) -> None:
        """Persist tokens with owner-only permissions. Token bytes never logged."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        data = tokens.model_dump()
        self._path.write_text(json.dumps(data), encoding="utf-8")
        # Owner-only on POSIX; harmless no-op on Windows (ACLs apply there).
        try:
            os.chmod(self._path, 0o600)
        except OSError:
            logger.warning("Could not set 0600 permissions on token file %s", self._path)
        logger.info("OAuth tokens saved (scopes=%s)", sorted(tokens.scopes))

    def load(self) -> OAuthTokens | None:
        """Return stored tokens, or None if absent/corrupt. Never logs token bytes."""
        if not self._path.exists():
            return None
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            logger.warning("OAuth token file unreadable: %s", self._path)
            return None
        return OAuthTokens(**data)

    def has_valid_tokens(self) -> bool:
        """Convenience gate: True iff stored tokens exist and are not expired."""
        tokens = self.load()
        return tokens is not None and not tokens.is_expired(self._refresh_slack)

    def is_expired(self, slack_seconds: float | None = None) -> bool:
        """True if stored tokens exist and are expired (within slack)."""
        tokens = self.load()
        if tokens is None:
            return True
        slack = slack_seconds if slack_seconds is not None else self._refresh_slack
        return tokens.is_expired(slack)

    def clear(self) -> None:
        """Remove stored tokens (e.g. after revocation / refresh failure)."""
        if self._path.exists():
            try:
                self._path.unlink()
                logger.info("OAuth tokens cleared")
            except OSError:
                logger.warning("Could not remove token file %s", self._path)
