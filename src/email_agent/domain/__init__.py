"""Email-Agent domain layer.

Pure business logic. Standard library only. Imports nothing from infrastructure,
framework, configuration, or provider code. See context-graph.json invariants
(``domain_inward``): this package is the innermost layer.
"""

from __future__ import annotations

from .approval import Approval
from .draft_state import DraftState
from .email_draft import EmailDraft
from .email_message import EmailMessage
from .exceptions import (
    ApprovalInvalidError,
    ApprovalRequiredError,
    DomainError,
    DraftValidationError,
    InvalidRecipientError,
    InvalidStateTransitionError,
)
from .policies import ApprovalPolicy, DraftPolicy
from .recipient import Recipient

__all__ = [
    "Approval",
    "ApprovalInvalidError",
    "ApprovalPolicy",
    "ApprovalRequiredError",
    "DomainError",
    "DraftPolicy",
    "DraftState",
    "DraftValidationError",
    "EmailDraft",
    "EmailMessage",
    "InvalidRecipientError",
    "InvalidStateTransitionError",
    "Recipient",
]
