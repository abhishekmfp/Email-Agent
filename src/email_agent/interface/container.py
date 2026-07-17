"""Dependency-injection container for the interface layer (M7 decision #6).

All dependencies are constructed ONCE at application startup (the container is
built by the app factory). Request handlers receive fully-constructed services;
no infrastructure is instantiated inside a request handler.

The container builds the exact object graph the VERIFIED M3-M6 use cases and
services require; it does NOT modify those inner modules (all M3-M6 invariants
frozen). The Send action is composed by the application-layer SendEmailUseCase
(Option gamma), which the interface delegates /send to (AC-UI-1).
"""

from __future__ import annotations

from dataclasses import dataclass

from email_agent.application.approve_email_use_case import ApproveEmailUseCase
from email_agent.application.draft_email_use_case import DraftEmailUseCase
from email_agent.application.drafting_service import DraftingService
from email_agent.application.send_email_use_case import SendEmailUseCase
from email_agent.config.settings import Settings, get_settings
from email_agent.infrastructure.anthropic_adapter import AnthropicAdapter
from email_agent.infrastructure.draft_response_validator import DraftResponseValidator
from email_agent.infrastructure.gmail_adapter import GmailAdapter
from email_agent.infrastructure.google_oauth_client import GoogleOAuthClient
from email_agent.infrastructure.oauth_token_store import OAuthTokenStore
from email_agent.infrastructure.prompt_builder import PromptBuilder


@dataclass(frozen=True)
class Container:
    """Fully-constructed service graph handed to interface handlers."""

    settings: Settings
    draft_email_use_case: DraftEmailUseCase
    approve_email_use_case: ApproveEmailUseCase
    send_email_use_case: SendEmailUseCase  # M7 Option gamma: composes approve + delivery
    delivery_service: object  # DeliveryService; typed loosely to avoid import cycle churn
    oauth_client: GoogleOAuthClient


def build_container(settings: Settings | None = None) -> Container:
    """Construct the full dependency graph once, at startup.

    Args:
        settings: injected Settings (defaults to the process singleton). Tests
            pass a custom Settings (e.g. with a fake Anthropic key / gmail config).
    """
    settings = settings or get_settings()

    # Drafting path (M3).
    anthropic_adapter = AnthropicAdapter(
        api_key=settings.anthropic.api_key,
        model=settings.anthropic.model,
        timeout_seconds=settings.anthropic.request_timeout_seconds,
    )
    draft_validator = DraftResponseValidator()
    prompt_builder = PromptBuilder()
    drafting_service = DraftingService(
        adapter=anthropic_adapter,
        validator=draft_validator,
        prompt_builder=prompt_builder,
    )
    draft_email_use_case = DraftEmailUseCase(drafting_service=drafting_service)

    # OAuth + delivery path (M5 + M6). Token store lives outside the repo.
    from email_agent.application.delivery_service import DeliveryService

    token_store = OAuthTokenStore(path=".email-agent/oauth_tokens.json")
    oauth_client = GoogleOAuthClient(gmail=settings.gmail, store=token_store)
    gmail_adapter = GmailAdapter(
        from_address=settings.gmail.from_address,
        timeout_seconds=settings.gmail.send_timeout_seconds,
    )
    delivery_service = DeliveryService(oauth_client=oauth_client, gmail_adapter=gmail_adapter)

    approve_email_use_case = ApproveEmailUseCase()

    # M7 Option gamma: compose approve + delivery into one application use case.
    # Interface delegates /send to this; it does NOT call DeliveryService itself.
    send_email_use_case = SendEmailUseCase(
        approve_use_case=approve_email_use_case,
        delivery_service=delivery_service,
    )

    return Container(
        settings=settings,
        draft_email_use_case=draft_email_use_case,
        approve_email_use_case=approve_email_use_case,
        send_email_use_case=send_email_use_case,
        delivery_service=delivery_service,
        oauth_client=oauth_client,
    )
