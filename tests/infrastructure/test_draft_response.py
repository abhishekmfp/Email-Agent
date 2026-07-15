"""Tests for the DraftResponse pydantic model (M3).

Confirms field types and defaults are enforced at construction — this is the
first guard against malformed LLM output, before the semantic validator runs.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from email_agent.infrastructure.draft_response import DraftResponse


def test_defaults_are_tolerant() -> None:
    resp = DraftResponse()
    assert resp.recipients == []
    assert resp.subject == ""
    assert resp.body == ""
    assert resp.clarification_required is False
    assert resp.missing_fields == []


def test_non_string_subject_rejected() -> None:
    with pytest.raises(ValidationError):
        DraftResponse(recipients=["a@b.com"], subject=5, body="B")  # type: ignore[arg-type]


def test_non_list_recipients_rejected() -> None:
    with pytest.raises(ValidationError):
        DraftResponse(recipients="a@b.com", subject="S", body="B")  # type: ignore[arg-type]


def test_non_list_missing_fields_rejected() -> None:
    with pytest.raises(ValidationError):
        DraftResponse(
            recipients=["a@b.com"],
            subject="S",
            body="B",
            missing_fields="x",  # type: ignore[arg-type]
        )
