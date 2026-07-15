"""Typed structured response returned by the Anthropic adapter (M3, ADR 3).

This is the AI<->application contract: the LLM produces only this structured
object, the application validates it (``DraftResponseValidator``), and only then
constructs a domain ``EmailDraft``. The domain layer never sees this type — it
remains unaware that an LLM exists (domain_inward invariant, ADR 7).
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class DraftResponse(BaseModel):
    """Structured draft produced by the Anthropic LLM.

    All fields default to tolerant values so partial LLM output does not raise
    at construction; semantic/structural validation happens in
    ``DraftResponseValidator``. ``recipients`` are explicit email addresses
    only — the LLM must never infer recipients; if it lacks them it sets
    ``clarification_required``.
    """

    model_config = {"extra": "ignore"}

    recipients: list[str] = Field(default_factory=list)
    subject: str = ""
    body: str = ""
    tone: str | None = None
    purpose: str | None = None
    clarification_required: bool = False
    missing_fields: list[str] = Field(default_factory=list)
