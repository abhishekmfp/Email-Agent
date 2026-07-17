"""HTTP transport DTOs for the interface layer (M7).

These are the TRANSPORT contract — pydantic models that serialize to JSON for
the FastAPI API. They deliberately do NOT expose domain objects directly (M7
decision #4: Translation Boundary Principle). The application use cases
consume/produce the application-layer dataclasses (``DraftRequest``,
``DraftResult``, ``ApprovalDecision``, ``ApprovalResult``), and the interface
translates between those and these DTOs. The interface owns all translation.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field

from email_agent.config.settings import get_settings

# ── Response DTOs (defined first; request DTOs reference DraftResponseDTO) ─────


class DraftStateDTO(StrEnum):
    """Lifecycle states mirrored from the domain for the transport layer."""

    DRAFTED = "DRAFTED"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    APPROVED = "APPROVED"
    SENT = "SENT"


class DraftResponseDTO(BaseModel):
    """Opaque workflow state returned by Draft and round-tripped by the client.

    The client treats this as opaque: it submits it back on Edit/Send/Reject.
    The server reconstructs the domain ``EmailDraft`` from it (translation only;
    no business logic). Recipients are transported as plain addresses; the
    interface never exposes the ``Approval`` value object.
    """

    recipients: list[str] = Field(
        ...,
        description="Recipient addresses (explicit, never inferred).",
    )
    subject: str
    body: str
    tone: str | None = None
    purpose: str | None = None
    state: DraftStateDTO = DraftStateDTO.AWAITING_APPROVAL
    clarification_required: bool = False


class DraftResultDTO(BaseModel):
    """Result of a Draft or Edit request."""

    status: str
    draft: DraftResponseDTO | None = None
    preview: str | None = None
    clarification_question: str | None = None
    missing_fields: list[str] = Field(default_factory=list)
    error: str | None = None


class SendResultDTO(BaseModel):
    """Result of a Send (approve + deliver) request."""

    status: str
    message_id: str | None = None
    thread_id: str | None = None
    error: str | None = None


class RejectResultDTO(BaseModel):
    """Result of a Reject request."""

    status: str = "REJECTED"
    error: str | None = None


class HealthResponseDTO(BaseModel):
    """Liveness/version payload for GET /health. No sensitive config."""

    status: str = "healthy"
    version: str = get_settings().app_version


class ErrorResponseDTO(BaseModel):
    """Unified structured error envelope (M7 decision #7).

    The interface owns this contract; application/domain are unaware of it.
    """

    code: str
    message: str
    detail: dict[str, object] | None = None


# ── Request DTOs ──────────────────────────────────────────────────────────────


class DraftRequestDTO(BaseModel):
    """A natural-language draft request from the user."""

    user_request: str = Field(..., description="Free-text request to turn into an email draft.")
    user_name: str | None = Field(
        default=None,
        description="Optional one-time user profile name used by the LLM prompt.",
    )


class EditRequestDTO(BaseModel):
    """An edit to a pending draft (replaces the prior approval)."""

    draft: DraftResponseDTO = Field(..., description="The pending draft to edit (round-tripped).")
    recipients: list[str] | None = Field(default=None, description="New recipient addresses.")
    subject: str | None = Field(default=None, description="New subject.")
    body: str | None = Field(default=None, description="New body.")
    tone: str | None = Field(default=None, description="New tone.")
    purpose: str | None = Field(default=None, description="New purpose/intent.")


class SendRequestDTO(BaseModel):
    """Approval + send of a pending draft. Send IS the approval boundary."""

    draft: DraftResponseDTO = Field(..., description="The pending draft to approve and send.")
    approver: str | None = Field(
        default=None,
        description="Human approver identity. Falls back to settings.user.name, then fails.",
    )


class RejectRequestDTO(BaseModel):
    """Rejection of a pending draft. Nothing is sent."""

    draft: DraftResponseDTO = Field(..., description="The pending draft to reject.")
    reason: str | None = Field(default=None, description="Optional informational reject note.")
