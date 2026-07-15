"""Recipient value object.

A recipient is identified by an explicit email address. Per the locked trust
model, recipients are *never inferred* by the system — they are only ever
constructed from addresses the human explicitly provides.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .exceptions import InvalidRecipientError

# Minimal, deliberately conservative email shape check. The domain does not
# need a fully RFC-compliant parser; it needs to reject obvious garbage before
# any address reaches the Gmail adapter.
_EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@dataclass(frozen=True)
class Recipient:
    """An explicitly-provided email recipient.

    ``email`` must be a syntactically valid address. ``name`` is optional
    display text and is never used for delivery routing.
    """

    email: str
    name: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.email, str) or not _EMAIL_PATTERN.match(self.email):
            raise InvalidRecipientError(f"Invalid recipient email: {self.email!r}")
        if self.name is not None and not isinstance(self.name, str):
            raise InvalidRecipientError("Recipient name must be a string or None")
