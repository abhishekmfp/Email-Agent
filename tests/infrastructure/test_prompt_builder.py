"""Tests for the PromptBuilder (M3, ADR 6)."""

from __future__ import annotations

from email_agent.infrastructure.prompt_builder import PromptBuilder


def test_build_returns_separated_system_and_user() -> None:
    prompt = PromptBuilder().build("Please email Bob about the meeting")
    assert prompt.system
    assert prompt.user_request == "Please email Bob about the meeting"
    # user request is never merged into system instructions
    assert "Please email Bob" not in prompt.system


def test_build_adds_user_name_to_system_not_user() -> None:
    prompt = PromptBuilder().build("Draft a note", user_name="Abhishek")
    assert "Abhishek" in prompt.system
    assert prompt.user_request == "Draft a note"
