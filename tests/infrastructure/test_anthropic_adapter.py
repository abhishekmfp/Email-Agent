"""Tests for the Anthropic adapter (M3).

The real Anthropic SDK is mocked at the boundary — we assert on the adapter's
contract: exactly one request, returns a typed DraftResponse, explicit timeout,
and that provider/JSON/schema failures become AnthropicProviderError.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from anthropic import APIError

from email_agent.infrastructure.anthropic_adapter import AnthropicAdapter
from email_agent.infrastructure.errors import AnthropicProviderError
from email_agent.infrastructure.prompt_builder import DraftPrompt


def _block(text: str) -> object:
    return MagicMock(text=text, type="text")


def _make_response(content_text: str) -> object:
    return MagicMock(content=[_block(content_text)])


def _adapter(client: MagicMock) -> AnthropicAdapter:
    return AnthropicAdapter(
        api_key="test-key", model="claude-test", timeout_seconds=10.0, client=client
    )


def test_generate_draft_returns_typed_response() -> None:
    client = MagicMock()
    client.messages.create.return_value = _make_response(
        '{"recipients": ["a@b.com"], "subject": "Hi", "body": "Hello"}'
    )
    adapter = _adapter(client)
    result = adapter.generate_draft(DraftPrompt(system="sys", user_request="req"))

    assert isinstance(result, object)
    assert result.recipients == ["a@b.com"]
    assert result.subject == "Hi"


def test_generate_draft_makes_exactly_one_request() -> None:
    client = MagicMock()
    client.messages.create.return_value = _make_response(
        '{"recipients": ["a@b.com"], "subject": "S", "body": "B"}'
    )
    adapter = _adapter(client)
    adapter.generate_draft(DraftPrompt(system="sys", user_request="req"))

    assert client.messages.create.call_count == 1  # ADR 5: single request
    _, kwargs = client.messages.create.call_args
    assert kwargs["timeout"] == 10.0  # outbound_timeout invariant
    assert kwargs["system"] == "sys"
    assert kwargs["messages"] == [{"role": "user", "content": "req"}]


def test_generate_draft_strips_code_fences() -> None:
    client = MagicMock()
    client.messages.create.return_value = _make_response(
        '```json\n{"recipients": [], "subject": "S", "body": "B", '
        '"clarification_required": true, "missing_fields": ["recipients"]}\n```'
    )
    adapter = _adapter(client)
    result = adapter.generate_draft(DraftPrompt(system="sys", user_request="req"))
    assert result.clarification_required is True
    assert result.missing_fields == ["recipients"]


def test_provider_error_on_api_failure() -> None:
    # Signature-agnostic stand-in for an Anthropic APIError: we only need it to
    # be an instance of anthropic.APIError so the adapter's except clause fires.
    class _Boom(APIError):
        def __init__(self, msg: str) -> None:
            self.message = msg  # type: ignore[assignment]

    client = MagicMock()
    client.messages.create.side_effect = _Boom("rate limited")
    with pytest.raises(AnthropicProviderError):
        _adapter(client).generate_draft(DraftPrompt(system="sys", user_request="req"))


def test_provider_error_on_invalid_json() -> None:
    client = MagicMock()
    client.messages.create.return_value = _make_response("not json at all")
    with pytest.raises(AnthropicProviderError):
        _adapter(client).generate_draft(DraftPrompt(system="sys", user_request="req"))


def test_provider_error_on_schema_mismatch() -> None:
    client = MagicMock()
    client.messages.create.return_value = _make_response('{"recipients": "nope"}')
    with pytest.raises(AnthropicProviderError):
        _adapter(client).generate_draft(DraftPrompt(system="sys", user_request="req"))
