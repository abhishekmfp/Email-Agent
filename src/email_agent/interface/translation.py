"""Translation boundary for the interface layer (M7).

Owns ALL translation between transport DTOs and application/domain objects
(M7 decision #4 / Translation Boundary Principle). The interface never exposes
domain types directly and never introduces business rules — these helpers are
pure mechanical mapping + reconstruction.

Per the approved stateless design (design review Q2), the server reconstructs
the ``EmailDraft`` from the client-supplied ``DraftResponseDTO`` on every
Edit/Send/Reject call, then invokes exactly one application use case.
"""

from __future__ import annotations

from email_agent.application.approval_request import ApprovalDecision
from email_agent.application.draft_request import DraftRequest
from email_agent.config.settings import Settings
from email_agent.domain.draft_state import DraftState
from email_agent.domain.email_draft import EmailDraft
from email_agent.domain.recipient import Recipient
from email_agent.interface.models import DraftRequestDTO, DraftResponseDTO, DraftStateDTO


def dto_to_draft(dto: DraftResponseDTO) -> EmailDraft:
    """Reconstruct a domain ``EmailDraft`` from a round-tripped ``DraftResponseDTO``.

    Pure translation — no business rules, no validation beyond building value
    objects. Recipients are reconstructed as explicit ``Recipient`` addresses.
    The reconstructed draft carries the round-tripped lifecycle ``state`` so the
    downstream use case's own guards (approval_gate, state_ownership) remain the
    single source of truth.
    """
    return EmailDraft(
        recipients=tuple(Recipient(email=e) for e in dto.recipients),
        subject=dto.subject,
        body=dto.body,
        tone=dto.tone,
        purpose=dto.purpose,
        clarification_required=dto.clarification_required,
        state=DraftState(dto.state.value),
    )


def draft_to_dto(draft: EmailDraft) -> DraftResponseDTO:
    """Project a domain ``EmailDraft`` into a transport ``DraftResponseDTO``."""
    return DraftResponseDTO(
        recipients=[r.email for r in draft.recipients],
        subject=draft.subject,
        body=draft.body,
        tone=draft.tone,
        purpose=draft.purpose,
        state=DraftStateDTO(draft.state.value),
        clarification_required=draft.clarification_required,
    )


def resolve_approver(request_approver: str | None, settings: Settings) -> str:
    """Resolve the human approver identity (B3 strict precedence, interface-owned).

    1. Request-supplied ``approver`` (if present and non-empty).
    2. Configured local identity ``settings.user.name``.
    3. Neither available -> raise ``ValueError`` so the interface fails validation
       BEFORE invoking ``ApproveEmailUseCase`` (application stays agnostic).

    The application layer always receives a fully-populated ``ApprovalDecision``
    and never inspects config or request context.
    """
    if request_approver and request_approver.strip():
        return request_approver.strip()
    config_name = settings.user.name
    if config_name and config_name.strip():
        return config_name.strip()
    raise ValueError(
        "No approver identity available: provide 'approver' or set APP_USER_NAME."
    )


def build_draft_request(dto: object) -> DraftRequest:
    """Translate an incoming DraftRequestDTO into an application DraftRequest."""
    assert isinstance(dto, DraftRequestDTO)  # type narrowing for callers
    return DraftRequest(user_request=dto.user_request, user_name=dto.user_name)


def build_approval_decision(
    decision: str,
    dto: DraftResponseDTO,
    *,
    approver: str | None = None,
    recipients: list[str] | None = None,
    subject: str | None = None,
    body: str | None = None,
    tone: str | None = None,
    purpose: str | None = None,
    reason: str | None = None,
) -> ApprovalDecision:
    """Build an application ``ApprovalDecision`` for an Edit/Send/Reject call.

    ``dto`` is accepted for API symmetry/forward-compat but the decision payload
    is taken from the explicit edit fields; no business rule is applied here.
    """
    return ApprovalDecision(
        decision=decision,  # type: ignore[arg-type]
        approver=approver,
        recipients=(
            tuple(Recipient(email=e) for e in recipients) if recipients is not None else None
        ),
        subject=subject,
        body=body,
        tone=tone,
        purpose=purpose,
        reason=reason,
    )
