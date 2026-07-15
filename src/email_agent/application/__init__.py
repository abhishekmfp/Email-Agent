"""Application layer for the drafting workflow (M3+).

The application layer owns orchestration: it drives the LLM adapter, validates
the boundary output, and constructs domain objects. It contains no business
rules of its own — those live in the domain layer (e.g. ``DraftPolicy``).

The application layer depends inward on the domain and infrastructure layers;
it is depended on by the interface layer. It must never be imported by the
domain or infrastructure layers (domain_inward invariant).
"""

from __future__ import annotations

from .draft_email_use_case import DraftEmailUseCase
from .draft_request import DraftRequest, DraftResult, DraftStatus
from .drafting_service import DraftingService

__all__ = [
    "DraftEmailUseCase",
    "DraftRequest",
    "DraftResult",
    "DraftStatus",
    "DraftingService",
]
