"""Domain-specific exceptions for the Email-Agent domain layer.

These are raised by pure domain logic and carry no infrastructure, framework,
or provider context. They are the contract the application layer catches to
decide how to respond (clarify, surface an error, or refuse an action).
"""

from __future__ import annotations


class DomainError(Exception):
    """Base class for every error raised inside the domain layer."""


class InvalidRecipientError(DomainError):
    """A recipient address failed domain validation (e.g. malformed email)."""


class DraftValidationError(DomainError):
    """A draft is missing required fields or otherwise fails domain policy."""


class InvalidStateTransitionError(DomainError):
    """A lifecycle transition was attempted from an illegal state."""


class ApprovalRequiredError(DomainError):
    """An action needed an explicit approval that was absent."""


class ApprovalInvalidError(DomainError):
    """An approval value object was present but not valid for the action."""
