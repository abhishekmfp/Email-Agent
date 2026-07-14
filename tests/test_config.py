"""Smoke tests for the M1 configuration layer (freeze boundary: M1 only)."""

from __future__ import annotations

import importlib

import pytest
from pydantic import ValidationError

from email_agent.config import Settings, get_settings


def test_settings_defaults() -> None:
    """Defaults are applied when no environment overrides are present."""
    settings = Settings(
        app_name="Email-Agent",
        app_version="0.1.0",
        log_level="INFO",
        environment="development",
    )
    assert settings.app_name == "Email-Agent"
    assert settings.app_version == "0.1.0"
    assert settings.log_level == "INFO"
    assert settings.environment == "development"


def test_settings_environment_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """Explicit values override defaults (config layer is env-driven)."""
    monkeypatch.setenv("APP_NAME", "Custom Agent")
    monkeypatch.setenv("APP_VERSION", "9.9.9")
    settings = Settings()
    assert settings.app_name == "Custom Agent"
    assert settings.app_version == "9.9.9"


def test_log_level_valid_normalized(monkeypatch: pytest.MonkeyPatch) -> None:
    """A valid lower-case log level is normalized to upper-case."""
    monkeypatch.setenv("LOG_LEVEL", "debug")
    assert Settings().log_level == "DEBUG"


def test_log_level_invalid_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """An unknown log level is rejected with a ValidationError."""
    monkeypatch.setenv("LOG_LEVEL", "LOUD")
    with pytest.raises(ValidationError):
        Settings()


def test_environment_valid_normalized(monkeypatch: pytest.MonkeyPatch) -> None:
    """A valid mixed-case environment is normalized to lower-case."""
    monkeypatch.setenv("ENVIRONMENT", "Production")
    assert Settings().environment == "production"


def test_environment_invalid_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """An unknown environment is rejected with a ValidationError."""
    monkeypatch.setenv("ENVIRONMENT", "vortex")
    with pytest.raises(ValidationError):
        Settings()


def test_get_settings_is_cached() -> None:
    """get_settings() returns the same singleton across calls."""
    first = get_settings()
    second = get_settings()
    assert first is second
    # Clear the cache so later tests start fresh (no global leakage).
    get_settings.cache_clear()
    importlib.reload(pytest)
