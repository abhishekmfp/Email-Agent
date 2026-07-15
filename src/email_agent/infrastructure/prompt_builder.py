"""Prompt construction for the Anthropic drafting path (M3, ADR 6).

Prompt construction is extracted from ``AnthropicAdapter`` into this dedicated
helper. The builder separates the system instructions (app context / the AI's
job description) from the untrusted user request using distinct message roles —
a core prompt-injection defense (decisions-manifest: system vs user). The user
request is never concatenated into the system instructions.

This module imports nothing from the application or domain layers (it accepts
plain primitives), preserving the inward dependency direction.
"""

from __future__ import annotations

from dataclasses import dataclass

_SYSTEM_TEMPLATE = """\
You are an email-drafting assistant. Your job is to turn a free-text request \
into a complete, professional email draft.

Output ONLY a single JSON object, with no prose and no markdown code fences, \
matching this exact shape:
{
  "recipients": [list of explicit email addresses],
  "subject": "string",
  "body": "string",
  "tone": "optional string (e.g. formal, friendly, concise)",
  "purpose": "optional string describing the email's intent",
  "clarification_required": false,
  "missing_fields": []
}

Rules:
- Recipients are NEVER inferred. If the request does not state explicit recipient \
addresses, set clarification_required=true and list the missing fields.
- If essential information (recipient, subject, or body content) is missing or \
ambiguous, set clarification_required=true and populate missing_fields; still return \
the best partial draft you can.
- Do NOT invent factual details (dates, commitments, names, business decisions).
- Improve grammar, tone, and formatting only where reasonable.
- When the information is sufficient, provide a complete, ready-to-send subject and body.
"""


@dataclass(frozen=True)
class DraftPrompt:
    """A fully-built prompt with separated system and user content."""

    system: str
    user_request: str


class PromptBuilder:
    """Builds a ``DraftPrompt`` from a user request and optional profile name."""

    def __init__(self, system_template: str = _SYSTEM_TEMPLATE) -> None:
        self._system_template = system_template

    def build(self, user_request: str, *, user_name: str | None = None) -> DraftPrompt:
        """Return a prompt with the system instructions and the raw user request.

        The user request is placed in its own message role and is never merged
        into the system instructions. An optional user name is added as app
        context to the system instructions (not user-injected content).
        """
        system = self._system_template
        if user_name:
            system = (
                f"{system}\n\nThe user's name is {user_name}. "
                "You may sign the email naturally on their behalf when appropriate."
            )
        return DraftPrompt(system=system, user_request=user_request)
