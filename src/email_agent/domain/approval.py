"""Approval value object.

Represents an explicit, deliberate human decision to approve a draft for
delivery. The domain never auto-approves; an ``Approval`` only exists because
a human created one.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .exceptions import ApprovalInvalidError


@dataclass(frozen=True)
class Approval:
    """An explicit human approval of a draft.

    ``approver`` identifies who approved (must be non-empty). ``decided_at``
    records when; a finalized approval always carries a timestamp.
    """

    approver: str
    decided_at: datetime | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.approver, str) or not self.approver.strip():
            raise ApprovalInvalidError("Approval requires a non-empty approver identity")
