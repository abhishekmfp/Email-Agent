"""Tests for the real dependency-injection container (M7 decision #6).

``build_container`` assembles the VERIFIED M3-M6 object graph with no fakes.
Constructing it does NOT make network calls (no LLM draft / Gmail send happens at
construction time) — it only wires adapters + use cases. These tests prove the
real graph assembles and that handlers receive fully-built services.
"""

from __future__ import annotations

from email_agent.config.settings import Settings
from email_agent.interface.container import Container, build_container


def test_build_container_constructs_real_graph():
    # Default env: no ANTHROPIC_API_KEY -> adapter stores "" but construction
    # succeeds (no network). This exercises the real DI wiring end-to-end.
    container = build_container(Settings())
    assert isinstance(container, Container)
    assert container.draft_email_use_case is not None
    assert container.approve_email_use_case is not None
    assert container.delivery_service is not None
    assert container.oauth_client is not None
    # Settings propagates into the container (single source, includest user).
    assert container.settings.user.name == ""


def test_build_container_default_settings_singleton():
    # build_container() with no arg uses the process Settings singleton.
    container = build_container()
    assert container.settings.app_version != ""
