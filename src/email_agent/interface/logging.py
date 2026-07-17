"""Structured logging for the interface layer (M7).

Uses only the standard-library :mod:`logging` module — no JSON-logging or
tracing frameworks (M7 decision #5). Logs are emitted as structured key/value
``extra`` dict passed through a custom ``LogRecord`` attribute so handlers can
render them consistently.

Secret hygiene (secrets_hygiene invariant): a single masking helper redacts
recipients, prompts, email bodies, OAuth tokens, and credentials. It is applied
to every log message and every error envelope so those values never reach logs,
the wire, or error responses. Recipient addresses are partially masked
(``a***@company.com``); token/credential material is fully redacted.
"""

from __future__ import annotations

import logging
import re

logger = logging.getLogger("email_agent.interface")

# Full redaction for anything that looks like a token / credential / secret.
_REDDACT = "***REDACTED***"

# Recipient / email masking: keep first char + domain, mask the middle.
_EMAIL_RE = re.compile(r"([A-Za-z0-9._%+\-])[A-Za-z0-9._%+\-]*@([A-Za-z0-9.\-]+\.[A-Za-z]+)")


def mask_email(email: str) -> str:
    """Partially mask an email address: ``alice@example.com`` -> ``a***@example.com``."""
    if not email:
        return email

    def _sub(match: re.Match[str]) -> str:
        local = match.group(1)
        domain = match.group(2)
        return f"{local}***@{domain}"

    return _EMAIL_RE.sub(_sub, email)


def mask_text(value: str | None) -> str | None:
    """Mask any embedded email addresses within a free-text value (prompt/body/subject)."""
    if not value:
        return value
    return _EMAIL_RE.sub(
        lambda m: f"{m.group(1)}***@{m.group(2)}", value
    )


def mask_recipients(recipients: list[str] | tuple[str, ...]) -> list[str]:
    """Return safely-masked copies of recipient addresses for logs/responses."""
    return [mask_email(r) for r in recipients]


def redact_secret(value: str | None) -> str | None:
    """Fully redact a token / credential / secret — never emit it."""
    if value is None or value == "":
        return value
    return _REDDACT


def log_event(event: str, **fields: object) -> None:
    """Emit a structured interface-layer log event.

    Sensitive fields should be passed through :func:`mask_email` /
    :func:`mask_text` / :func:`redact_secret` by the caller before logging. This
    helper does NOT itself know which field is sensitive — the caller owns
    masking (defense-in-depth: see :func:`safe_log` for auto-masking of known
    keys).
    """
    logger.info(event, extra={"event": event, **fields})


_SENSITIVE_KEYS = {
    "token",
    "access_token",
    "refresh_token",
    "credentials",
    "api_key",
    "secret",
    "password",
    "prompt",
    "body",
    "recipients",
}

# Subset whose value is a token/credential/secret → fully redacted.
_SECRET_KEYS = {
    "token",
    "access_token",
    "refresh_token",
    "credentials",
    "api_key",
    "secret",
    "password",
}


def safe_log(event: str, **fields: object) -> None:
    """Emit a structured log event, auto-masking values whose key is sensitive.

    Keys in ``_SENSITIVE_KEYS`` are redacted (tokens/credentials) or masked
    (recipients) or fully redacted (prompts/bodies — never logged at all, per the
    secrets_hygiene invariant). This is a safety net so a handler that forgets to
    pre-mask still never leaks secret material.
    """
    cleaned: dict[str, object] = {}
    for key, value in fields.items():
        lk = key.lower()
        if lk in _SECRET_KEYS:
            cleaned[key] = _REDDACT
        elif lk == "recipients" and isinstance(value, (list, tuple)):
            cleaned[key] = mask_recipients([str(v) for v in value])
        elif lk in {"prompt", "body"}:
            # Prompts and email bodies must NEVER reach logs (secrets_hygiene).
            cleaned[key] = _REDDACT
        elif lk == "subject" and isinstance(value, str):
            cleaned[key] = mask_text(value)
        else:
            cleaned[key] = value
    log_event(event, **cleaned)
