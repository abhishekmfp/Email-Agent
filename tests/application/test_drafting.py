"""Tests for the DraftingService + DraftEmailUseCase (M3 acceptance).

AnthropicAdapter is mocked. The acceptance path drives a sample request ->
validated DraftResponse -> EmailDraft in AWAITING_APPROVAL, asserting the
AWAITING_APPROVAL state, no send, and the clarification/error branches.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from email_agent.application.draft_email_use_case import DraftEmailUseCase

from email_agent.application.draft_request import DraftRequest
from email_agent.application.drafting_service import DraftingService
from email_agent.domain.draft_state import DraftState
from email_agent.infrastructure.draft_response import DraftResponse
from email_agent.infrastructure.draft_response_validator import DraftResponseValidator
from email_agent.infrastructure.errors import AnthropicProviderError
from email_agent.infrastructure.prompt_builder import PromptBuilder


def _service(adapter: MagicMock, *, max_attempts: int = 3) -> DraftingService:
    return DraftingService(
        adapter=adapter,
        validator=DraftResponseValidator(),
        prompt_builder=PromptBuilder(),
        max_attempts=max_attempts,
    )


def test_acceptance_request_yields_draft_in_awaiting_approval() -> None:
    adapter = MagicMock()
    adapter.generate_draft.return_value = DraftResponse(
        recipients=["boss@corp.com"], subject="Update", body="Here is the update."
    )
    result = _service(adapter).draft(DraftRequest(user_request="Email my boss an update"))

    assert result.status.value == "SUCCESS"
    assert result.draft is not None
    assert result.draft.state is DraftState.AWAITING_APPROVAL
    assert result.draft.recipients[0].email == "boss@corp.com"
    assert result.preview is not None
    # No Gmail/approval/send path touched in M3.
    adapter.generate_draft.assert_called_once()


def test_clarification_branch_returns_no_draft() -> None:
    adapter = MagicMock()
    adapter.generate_draft.return_value = DraftResponse(
        recipients=[],
        subject="",
        body="",
        clarification_required=True,
        missing_fields=["recipients"],
    )
    result = _service(adapter).draft(DraftRequest(user_request="Email someone"))

    assert result.status.value == "CLARIFICATION_REQUIRED"
    assert result.draft is None
    assert result.missing_fields == ["recipients"]
    assert result.preview is None


def test_transient_provider_failure_retries_then_errors() -> None:
    adapter = MagicMock()
    adapter.generate_draft.side_effect = AnthropicProviderError("timeout")
    result = _service(adapter, max_attempts=3).draft(DraftRequest(user_request="Email my boss"))

    assert result.status.value == "ERROR"
    assert result.draft is None
    assert adapter.generate_draft.call_count == 3  # ADR 5: retry in service


def test_validation_failure_surfaces_error_no_draft() -> None:
    # Provider returns a final draft with empty content -> validator rejects.
    adapter = MagicMock()
    adapter.generate_draft.return_value = DraftResponse(
        recipients=[],
        subject="",
        body="",  # not clarification_required -> invalid
    )
    result = _service(adapter).draft(DraftRequest(user_request="Email someone"))

    assert result.status.value == "ERROR"
    assert result.draft is None
    # No retry on validation failure (only on transient provider error).
    assert adapter.generate_draft.call_count == 1


def test_use_case_thin_wrapper() -> None:
    adapter = MagicMock()
    adapter.generate_draft.return_value = DraftResponse(
        recipients=["x@y.com"], subject="S", body="B"
    )
    uc = DraftEmailUseCase(_service(adapter))
    result = uc.execute(DraftRequest(user_request="hi"))

    assert result.status.value == "SUCCESS"
    assert result.draft is not None
