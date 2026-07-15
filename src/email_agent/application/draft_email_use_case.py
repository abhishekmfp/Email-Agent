"""Thin application use case for drafting (M3).

``DraftEmailUseCase`` orchestrates ``DraftingService`` and returns a
``DraftResult``. It deliberately holds no business rules — the domain owns
those; the service owns orchestration. The interface layer will call this use
case and render the result.
"""

from __future__ import annotations

from .draft_request import DraftRequest, DraftResult
from .drafting_service import DraftingService


class DraftEmailUseCase:
    """Exposes the draft-email capability to the interface layer."""

    def __init__(self, drafting_service: DraftingService) -> None:
        self._drafting_service = drafting_service

    def execute(self, request: DraftRequest) -> DraftResult:
        """Run the drafting workflow and return its result (no send)."""
        return self._drafting_service.draft(request)
