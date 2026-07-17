"""CLI interface for Email-Agent (M7, decision #3 — argparse, stdlib).

Drives the SAME application use cases as the FastAPI interface. The CLI is a
thin translation shell over the container built at startup: it reads stdin/args,
constructs DTOs, calls the use cases via the shared translation helpers, and
prints the result. It follows the same interface rules — one action per command,
no business logic, approver resolution via B3, structured errors.

Stateless model: a Draft prints the DraftResponseDTO as JSON; the user pipes it
back into edit/send/reject via --draft-file (the client holds the opaque state).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from email_agent.config.settings import get_settings
from email_agent.interface.container import build_container
from email_agent.interface.errors import (
    ApprovalError,
    InterfaceError,
    ValidationError,
    send_result_error,
)
from email_agent.interface.logging import safe_log
from email_agent.interface.models import (
    DraftRequestDTO,
    DraftResponseDTO,
)
from email_agent.interface.translation import (
    build_approval_decision,
    build_draft_request,
    draft_to_dto,
    dto_to_draft,
    resolve_approver,
)


def _read_draft(path: str) -> DraftResponseDTO:
    return DraftResponseDTO.model_validate_json(Path(path).read_text(encoding="utf-8"))


def _print_error(exc: InterfaceError) -> int:
    payload: dict[str, object] = {"code": exc.code, "message": exc.message}
    if exc.detail:
        payload["detail"] = exc.detail
    print(json.dumps(payload), file=sys.stderr)
    return 2


def cmd_draft(args: argparse.Namespace) -> int:
    container = build_container(get_settings())
    dto = DraftRequestDTO(user_request=args.request, user_name=args.user_name)
    result = container.draft_email_use_case.execute(build_draft_request(dto))
    if result.status.value == "SUCCESS" and result.draft is not None:
        # Emit the round-trippable DraftResponseDTO so it can be piped to
        # edit/send/reject (stateless model: client holds the opaque state).
        print(draft_to_dto(result.draft).model_dump_json())
        return 0
    if result.status.value == "CLARIFICATION_REQUIRED":
        print(
            json.dumps(
                {
                    "status": "CLARIFICATION_REQUIRED",
                    "clarification_question": result.clarification_question,
                    "missing_fields": result.missing_fields,
                }
            )
        )
        return 0
    raise ValidationError(result.error or "Draft request failed.")


def cmd_edit(args: argparse.Namespace) -> int:
    container = build_container(get_settings())
    prior = _read_draft(args.draft_file)
    decision = build_approval_decision(
        "edit",
        prior,
        recipients=_split(args.recipients),
        subject=args.subject,
        body=args.body,
        tone=args.tone,
        purpose=args.purpose,
    )
    result = container.approve_email_use_case.execute(dto_to_draft(prior), decision)
    from email_agent.application.approval_request import ApprovalStatus

    if result.status == ApprovalStatus.AWAITING_APPROVAL and result.draft is not None:
        print(draft_to_dto(result.draft).model_dump_json())
        return 0
    raise ApprovalError(result.error or "Edit rejected.")


def cmd_send(args: argparse.Namespace) -> int:
    container = build_container(get_settings())
    prior = _read_draft(args.draft_file)
    try:
        approver = resolve_approver(args.approver, container.settings)
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc
    decision = build_approval_decision("approve", prior, approver=approver)

    # AC-UI-1: delegate to exactly ONE use case (SendEmailUseCase composes
    # ApproveEmailUseCase + DeliveryService internally; M4/M6 stay frozen).
    result = container.send_email_use_case.execute(dto_to_draft(prior), decision)

    if result.status == "SENT":
        safe_log("email_sent", message_id_masked=result.message_id)
        print(
            json.dumps(
                {
                    "status": "SENT",
                    "message_id": result.message_id,
                    "thread_id": result.thread_id,
                }
            )
        )
        return 0
    raise send_result_error(result)


def cmd_reject(args: argparse.Namespace) -> int:
    container = build_container(get_settings())
    prior = _read_draft(args.draft_file)
    decision = build_approval_decision("reject", prior, reason=args.reason)
    result = container.approve_email_use_case.execute(dto_to_draft(prior), decision)
    from email_agent.application.approval_request import ApprovalStatus

    if result.status == ApprovalStatus.REJECTED:
        print(json.dumps({"status": "REJECTED"}))
        return 0
    raise ApprovalError(result.error or "Reject rejected.")


def _split(value: str | None) -> list[str] | None:
    if value is None:
        return None
    return [v.strip() for v in value.split(",") if v.strip()]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="email-agent", description="Email-Agent CLI (M7).")
    sub = parser.add_subparsers(dest="command", required=True)

    p_draft = sub.add_parser("draft", help="Draft an email from a free-text request.")
    p_draft.add_argument("--request", required=True, help="Free-text email request.")
    p_draft.add_argument("--user-name", default=None, help="Optional user profile name.")
    p_draft.set_defaults(func=cmd_draft)

    p_edit = sub.add_parser("edit", help="Edit a pending draft (round-tripped DTO file).")
    p_edit.add_argument("--draft-file", required=True, help="Path to a DraftResponseDTO JSON.")
    p_edit.add_argument("--recipients", default=None, help="Comma-separated addresses.")
    p_edit.add_argument("--subject", default=None)
    p_edit.add_argument("--body", default=None)
    p_edit.add_argument("--tone", default=None)
    p_edit.add_argument("--purpose", default=None)
    p_edit.set_defaults(func=cmd_edit)

    p_send = sub.add_parser("send", help="Approve and send a pending draft.")
    p_send.add_argument("--draft-file", required=True, help="Path to a DraftResponseDTO JSON.")
    p_send.add_argument(
        "--approver",
        default=None,
        help="Approver identity (falls back to config).",
    )
    p_send.set_defaults(func=cmd_send)

    p_reject = sub.add_parser("reject", help="Reject a pending draft.")
    p_reject.add_argument("--draft-file", required=True, help="Path to a DraftResponseDTO JSON.")
    p_reject.add_argument("--reason", default=None, help="Optional reject note.")
    p_reject.set_defaults(func=cmd_reject)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result = args.func(args)
        return int(result)
    except InterfaceError as exc:
        return _print_error(exc)
    except FileNotFoundError as exc:
        print(json.dumps({"code": "not_found", "message": str(exc)}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
