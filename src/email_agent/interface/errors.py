"""Interface-owned error envelope translation (M7 decision #7).

Maps application results and interface-layer failures into the unified
``ErrorResponseDTO`` contract ``{code, message, detail?}``. The application and
domain layers are unaware of this envelope — the interface owns the mapping.

Secret hygiene: messages never contain tokens, credentials, prompts, bodies, or
stack traces. Un-typed exceptions become a generic ``internal_error``; the full
exception is recorded only in structured logs (see ``interface.logging``).
"""

from __future__ import annotations

from email_agent.application.approval_request import ApprovalStatus
from email_agent.application.draft_request import DraftStatus
from email_agent.application.send_email_use_case import SendResult
from email_agent.interface.logging import safe_log
from email_agent.interface.models import ErrorResponseDTO


class InterfaceError(Exception):
    """Base for interface-layer failures that map to a specific error envelope.

    Attributes:
        code: machine-readable error code for the envelope.
        status_code: HTTP status to return.
        message: safe human-readable message (no secrets).
        detail: optional machine-readable detail dict.
    """

    code: str = "internal_error"
    status_code: int = 500

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        status_code: int | None = None,
        detail: dict[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        if code is not None:
            self.code = code
        if status_code is not None:
            self.status_code = status_code
        self.message = message
        self.detail = detail

    def to_dto(self) -> ErrorResponseDTO:
        """Render this error as the unified envelope contract."""
        return ErrorResponseDTO(code=self.code, message=self.message, detail=self.detail)


class ValidationError(InterfaceError):
    """Client input failed validation (e.g. approver missing)."""

    code = "validation_error"
    status_code = 422


class ApprovalError(InterfaceError):
    """The approval/edit decision was rejected by the domain guard."""

    code = "approval_error"
    status_code = 422


class AuthRequiredError(InterfaceError):
    """Delivery needs re-authentication (TokenRefreshError surfaced as auth_failed)."""

    code = "auth_required"
    status_code = 401


class DeliveryUnknownStateError(InterfaceError):
    """Send dispatched but outcome unconfirmed — verify before retry."""

    code = "delivery_unknown_state"
    status_code = 502


class DeliveryFailedError(InterfaceError):
    """Delivery failed (terminal / not approved)."""

    code = "delivery_failed"
    status_code = 502


def draft_result_error(result: object) -> ErrorResponseDTO:
    """Translate a non-success DraftResult into an error envelope."""
    assert isinstance(result, object)
    status = getattr(result, "status", None)
    error = getattr(result, "error", None) or "Draft request failed."
    if status == DraftStatus.CLARIFICATION_REQUIRED:
        # Clarification is a normal branch, not an error — handled by caller.
        return ErrorResponseDTO(code="clarification_required", message=str(error))
    return ErrorResponseDTO(code="draft_error", message=str(error))


def approval_result_error(result: object) -> ErrorResponseDTO:
    """Translate an ERROR ApprovalResult into an error envelope."""
    error = getattr(result, "error", None) or "Approval decision rejected."
    return ErrorResponseDTO(code="approval_error", message=str(error))


def translate_delivery(status: str, error: str | None) -> ErrorResponseDTO:
    """Map a DeliveryResult status to an error envelope (auth/unknown/failed)."""
    msg = error or "Delivery failed."
    if status == "auth_failed":
        # Fixed message: the infra error may echo token/account hints — never
        # forward it to the client (secrets_hygiene invariant).
        return ErrorResponseDTO(
            code="auth_required",
            message="Authentication required before delivery. Please re-authenticate.",
            detail={"delivery_status": status},
        )
    if status == "unknown_state":
        # Infra message is safe (no tokens/bodies); surface it so the operator
        # can verify before retry.
        return ErrorResponseDTO(
            code="delivery_unknown_state",
            message=f"Email dispatched but delivery unconfirmed: {msg}",
            detail={"delivery_status": status},
        )
    return ErrorResponseDTO(
        code="delivery_failed",
        message=f"Delivery failed: {msg}",
        detail={"delivery_status": status},
    )


def send_result_error(result: SendResult) -> InterfaceError:
    """Translate a non-SENT ``SendResult`` into the appropriate envelope error.

    Maps the unified application result to the interface error hierarchy so the
    HTTP status + code follow AC-UI-1 (one delegation, typed errors).

    Secret hygiene: the ``AUTH_FAILED`` branch uses a FIXED message and ignores
    ``result.error`` — the upstream delivery error may echo token/account hints,
    and the interface envelope must never forward them (secrets_hygiene
    invariant). Other branches surface ``result.error`` because the M6 delivery
    contract guarantees those messages carry no tokens or bodies.
    """
    detail = result.detail
    msg = result.error or "Send failed."
    if result.status == "AUTH_FAILED":
        return AuthRequiredError(
            "Authentication required before delivery. Please re-authenticate.",
            detail=detail,
        )
    if result.status == "UNKNOWN_STATE":
        return DeliveryUnknownStateError(msg, detail=detail)
    if result.status == "APPROVAL_REJECTED":
        return ApprovalError(msg, detail=detail)
    return DeliveryFailedError(msg, detail=detail)


def internal_error(exc: Exception) -> ErrorResponseDTO:
    """Generic envelope for un-typed exceptions; full detail to logs only."""
    safe_log("unhandled_error", error_type=type(exc).__name__)
    return ErrorResponseDTO(
        code="internal_error",
        message="An unexpected error occurred. See server logs for details.",
    )


__all__ = [
    "ApprovalError",
    "ApprovalStatus",
    "AuthRequiredError",
    "DeliveryFailedError",
    "DeliveryUnknownStateError",
    "InterfaceError",
    "ValidationError",
    "approval_result_error",
    "draft_result_error",
    "internal_error",
    "send_result_error",
    "translate_delivery",
]
