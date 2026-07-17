"""FastAPI interface for Email-Agent (M7).

Application factory ``create_app`` builds the dependency graph ONCE at startup
(M7 decision #6) and wires five REST endpoints:

    POST /draft    -> DraftEmailUseCase
    POST /edit     -> ApproveEmailUseCase (decision="edit")
    POST /send     -> SendEmailUseCase (orchestrates ApproveEmailUseCase + DeliveryService)
    POST /reject   -> ApproveEmailUseCase (decision="reject")
    GET  /health   -> version + status

No Review / Approve / Regenerate endpoints. Each mutating endpoint delegates to
exactly one application use case (AC-UI-1); the interface only translates
between transport DTOs and application/domain objects. The interface owns all
translation and the error envelope (Translation Boundary Principle).
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from email_agent.application.approval_request import ApprovalStatus
from email_agent.application.draft_request import DraftStatus
from email_agent.config.settings import get_settings
from email_agent.domain.draft_state import DraftState
from email_agent.interface.container import Container, build_container
from email_agent.interface.errors import (
    ApprovalError,
    InterfaceError,
    ValidationError,
    approval_result_error,
    draft_result_error,
    internal_error,
    send_result_error,
)
from email_agent.interface.logging import safe_log
from email_agent.interface.models import (
    DraftRequestDTO,
    DraftResultDTO,
    EditRequestDTO,
    ErrorResponseDTO,
    HealthResponseDTO,
    RejectRequestDTO,
    RejectResultDTO,
    SendRequestDTO,
    SendResultDTO,
)
from email_agent.interface.translation import (
    build_approval_decision,
    build_draft_request,
    draft_to_dto,
    dto_to_draft,
    resolve_approver,
)


def create_app(container: Container | None = None) -> FastAPI:
    """Build the FastAPI app with the dependency graph constructed once at startup."""
    container = container or build_container(get_settings())

    app = FastAPI(title="Email-Agent", version=container.settings.app_version)
    app.state.container = container

    @app.exception_handler(InterfaceError)
    async def _interface_error_handler(_: Request, exc: InterfaceError) -> JSONResponse:
        safe_log("interface_error", code=exc.code, status_code=exc.status_code)
        body = ErrorResponseDTO(code=exc.code, message=exc.message, detail=exc.detail)
        return JSONResponse(status_code=exc.status_code, content=body.model_dump())

    @app.exception_handler(Exception)
    async def _unhandled_error_handler(_: Request, exc: Exception) -> JSONResponse:
        body = internal_error(exc)
        return JSONResponse(status_code=500, content=body.model_dump())

    @app.get("/health", response_model=HealthResponseDTO, summary="Liveness + version")
    def health() -> HealthResponseDTO:
        return HealthResponseDTO(version=container.settings.app_version)

    @app.post("/draft", response_model=DraftResultDTO, summary="Draft an email")
    def draft(request: DraftRequestDTO) -> DraftResultDTO:
        safe_log("draft_received", request_len=len(request.user_request))
        result = container.draft_email_use_case.execute(build_draft_request(request))
        if result.status == DraftStatus.SUCCESS and result.draft is not None:
            dto = draft_to_dto(result.draft)
            return DraftResultDTO(
                status=result.status.value,
                draft=dto,
                preview=result.preview,
            )
        if result.status == DraftStatus.CLARIFICATION_REQUIRED:
            return DraftResultDTO(
                status=result.status.value,
                clarification_question=result.clarification_question,
                missing_fields=result.missing_fields,
            )
        # ERROR
        env = draft_result_error(result)
        raise ValidationError(env.message)

    @app.post("/edit", response_model=DraftResultDTO, summary="Edit a pending draft")
    def edit(request: EditRequestDTO) -> DraftResultDTO:
        draft = dto_to_draft(request.draft)
        decision = build_approval_decision(
            "edit",
            request.draft,
            recipients=request.recipients,
            subject=request.subject,
            body=request.body,
            tone=request.tone,
            purpose=request.purpose,
        )
        result = container.approve_email_use_case.execute(draft, decision)
        if result.status == ApprovalStatus.AWAITING_APPROVAL and result.draft is not None:
            edited = result.draft
            return DraftResultDTO(
                status=result.status.value,
                draft=draft_to_dto(edited),
                preview=_preview_draft(edited),
            )
        if result.status == ApprovalStatus.ERROR:
            env = approval_result_error(result)
            raise ApprovalError(env.message)
        # Reject path is not valid for edit; surface as approval error if reached.
        raise ApprovalError("Edit produced an unexpected outcome.")

    @app.post("/send", response_model=SendResultDTO, summary="Approve and send")
    def send(request: SendRequestDTO) -> SendResultDTO:
        # B3 approver resolution — interface-owned, before any use case call.
        try:
            approver = resolve_approver(request.approver, container.settings)
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc

        draft = dto_to_draft(request.draft)
        decision = build_approval_decision("approve", request.draft, approver=approver)

        # AC-UI-1: delegate to exactly ONE application use case. SendEmailUseCase
        # orchestrates ApproveEmailUseCase (M4) + DeliveryService (M6) internally;
        # the interface only translates the unified SendResult. M4/M6 stay frozen.
        result = container.send_email_use_case.execute(draft, decision)

        if result.status == "SENT":
            safe_log("email_sent", message_id_masked=result.message_id)
            return SendResultDTO(
                status=result.status,
                message_id=result.message_id,
                thread_id=result.thread_id,
            )
        raise send_result_error(result)

    @app.post("/reject", response_model=RejectResultDTO, summary="Reject a pending draft")
    def reject(request: RejectRequestDTO) -> RejectResultDTO:
        draft = dto_to_draft(request.draft)
        decision = build_approval_decision("reject", request.draft, reason=request.reason)
        result = container.approve_email_use_case.execute(draft, decision)
        if result.status == ApprovalStatus.REJECTED:
            safe_log("draft_rejected")
            return RejectResultDTO(status=result.status.value)
        env = approval_result_error(result)
        raise ApprovalError(env.message)

    return app


def _preview_draft(draft: Any) -> str | None:
    """Render a human-readable preview from a domain draft (interface-owned)."""
    if draft.state is not DraftState.AWAITING_APPROVAL:
        return None
    lines = [f"To: {', '.join(r.email for r in draft.recipients)}"]
    if draft.tone:
        lines.append(f"Tone: {draft.tone}")
    lines.append(f"Subject: {draft.subject}")
    lines.append("")
    lines.append(draft.body)
    return "\n".join(lines)
