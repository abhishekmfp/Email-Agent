"""Application use case: approve + deliver an email (M7 — Option gamma).

``SendEmailUseCase`` is the single application-layer owner of the
"approve-then-deliver" composition. It orchestrates two VERIFIED components:

  * ``ApproveEmailUseCase``   (M4) — builds the domain ``Approval`` and returns
    the frozen, immutable ``EmailMessage``.
  * ``DeliveryService``       (M6) — delivers that exact ``EmailMessage``.

The interface delegates ``POST /send`` to exactly this use case (AC-UI-1), so the
transport layer stays thin and business orchestration lives in the application
layer where it belongs.

This use case does NOT:
  * construct a domain ``Approval`` — only ``ApproveEmailUseCase`` may (M4-E1).
  * recreate or derive an ``EmailMessage`` — it forwards the exact instance
    ``ApproveEmailUseCase`` produced (M4-E4 / M6-X1 artifact_identity).
  * call ``GmailAdapter`` directly — delivery goes only through ``DeliveryService``
    (M6-X1).
  * import the LLM / Anthropic SDK (M4-E2).

The interface receives a single unified ``SendResult`` and owns translation into
its response/error envelope (Translation Boundary Principle).
"""

from __future__ import annotations

from dataclasses import dataclass

from email_agent.application.approval_request import ApprovalDecision, ApprovalStatus
from email_agent.application.approve_email_use_case import ApproveEmailUseCase
from email_agent.application.delivery_service import DeliveryService
from email_agent.domain.email_draft import EmailDraft
from email_agent.domain.email_message import EmailMessage


@dataclass(frozen=True)
class SendResult:
    """Unified outcome of the send action (approval + delivery).

    ``status`` is one of:
      SENT | APPROVAL_REJECTED | AUTH_FAILED | UNKNOWN_STATE |
      DELIVERY_FAILED | ERROR
    The interface maps these to its response/error envelope.
    """

    status: str
    message_id: str | None = None
    thread_id: str | None = None
    error: str | None = None
    detail: dict[str, object] | None = None


class SendEmailUseCase:
    """Approve a reconstructed draft, then deliver it via ``DeliveryService``.

    The only application-layer composition point for the send action. The
    interface passes the reconstructed ``EmailDraft`` and the human's
    ``ApprovalDecision``; this use case returns a single ``SendResult``.
    """

    def __init__(
        self,
        approve_use_case: ApproveEmailUseCase,
        delivery_service: DeliveryService,
    ) -> None:
        self._approve = approve_use_case
        self._deliver = delivery_service

    def execute(self, draft: EmailDraft, decision: ApprovalDecision) -> SendResult:
        # 1. Approve (VERIFIED M4): builds Approval, returns frozen EmailMessage.
        approval = self._approve.execute(draft, decision)

        if approval.status != ApprovalStatus.APPROVED or approval.message is None:
            # Domain guard rejected the approval (e.g. not in AWAITING_APPROVAL,
            # or missing approver). No delivery is attempted.
            return SendResult(
                status="APPROVAL_REJECTED",
                error=approval.error or "Approval rejected.",
            )

        # 2. Deliver the EXACT EmailMessage instance (M4-E4 / M6-X1
        #    artifact_identity). DeliveryService reads it read-only; never rebuilt.
        message: EmailMessage = approval.message
        delivery = self._deliver.send(message)

        if delivery.success:
            return SendResult(
                status="SENT",
                message_id=delivery.message_id,
                thread_id=delivery.thread_id,
            )

        # 3. Translate the delivery outcome into a unified result.
        return _translate_delivery(delivery.status, delivery.error)


def _translate_delivery(status: str, error: str | None) -> SendResult:
    """Map a ``DeliveryResult`` status into a ``SendResult`` (no secret leakage)."""
    msg = error or "Delivery failed."
    if status == "auth_failed":
        # Fixed message: the infra error may echo token/account hints — never
        # forward it (secrets_hygiene invariant).
        return SendResult(
            status="AUTH_FAILED",
            error="Authentication required before delivery. Please re-authenticate.",
            detail={"delivery_status": status},
        )
    if status == "unknown_state":
        # Infra message is safe (no tokens/bodies); surface so the operator can
        # verify before retry.
        return SendResult(
            status="UNKNOWN_STATE",
            error=f"Email dispatched but delivery unconfirmed: {msg}",
            detail={"delivery_status": status},
        )
    if status == "not_approved":
        # Defense-in-depth: DeliveryService refused (no valid Approval on message).
        return SendResult(
            status="APPROVAL_REJECTED",
            error=error or "Refusing to deliver: no explicit approval.",
            detail={"delivery_status": status},
        )
    return SendResult(
        status="DELIVERY_FAILED",
        error=f"Delivery failed: {msg}",
        detail={"delivery_status": status},
    )
