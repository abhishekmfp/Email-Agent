"""Tests for the DraftResponse boundary validator (M3, ADR 4).

The validator's job is semantic/presence rules (a final draft needs
recipients+subject+body; recipients must be non-empty). Field *type* conformance
is enforced by the ``DraftResponse`` pydantic model at construction — see
``test_draft_response.py``.
"""

from __future__ import annotations

import pytest

from email_agent.infrastructure.draft_response import DraftResponse
from email_agent.infrastructure.draft_response_validator import (
    DraftResponseValidationError,
    DraftResponseValidator,
)

VALID = DraftResponse(recipients=["a@b.com"], subject="Subject", body="Body text", tone="formal")


def _validator() -> DraftResponseValidator:
    return DraftResponseValidator()


def test_valid_final_draft_passes() -> None:
    _validator().validate(VALID)


def test_clarification_draft_without_content_passes() -> None:
    clar = DraftResponse(
        recipients=[],
        subject="",
        body="",
        clarification_required=True,
        missing_fields=["recipients"],
    )
    _validator().validate(clar)  # allowed; clarification path


def test_missing_recipient_in_final_draft_fails() -> None:
    bad = DraftResponse(recipients=[], subject="S", body="B")
    with pytest.raises(DraftResponseValidationError):
        _validator().validate(bad)


def test_empty_recipient_string_fails() -> None:
    bad = DraftResponse(recipients=[""], subject="S", body="B")
    with pytest.raises(DraftResponseValidationError):
        _validator().validate(bad)
