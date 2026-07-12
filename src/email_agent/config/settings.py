"""Application configuration settings for Email-Agent.

Milestone M1 — Project Foundation only. This module defines the generic,
application-level configuration via ``pydantic-settings``. It deliberately
contains NO Gmail, OpenAI, or other external-integration settings, and NO
business or agent logic. Those belong to later milestones.

Future expansion pattern: add new *sections* as separate ``BaseSettings``
subclasses (e.g. ``GmailSettings`` with ``env_prefix="GMAIL_"`` and
``OpenAISettings`` with ``env_prefix="OPENAI_"``) and compose them into a
top-level ``Settings`` when those milestones land. The generic app settings
below stay prefix-free so section prefixes never collide with them.
"""

from __future__ import annotations

import logging
from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Canonical set of accepted environment names. Kept as a module constant so
# the validator message and future code share one source of truth.
_ALLOWED_ENVIRONMENTS = frozenset({"development", "staging", "production", "test"})


class Settings(BaseSettings):
    """Generic application settings.

    Values are loaded from environment variables (case-insensitive) and/or a
    ``.env`` file, falling back to safe local-development defaults. All
    fields are validated on construction — an invalid ``log_level`` or
    ``environment`` raises immediately rather than failing later at runtime.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = Field(
        default="Email-Agent",
        description="Human-readable application name.",
    )
    app_version: str = Field(
        default="0.1.0",
        description="Application version (semver). Keep in sync with pyproject.toml.",
    )
    log_level: str = Field(
        default="INFO",
        description="Logging level name: DEBUG, INFO, WARNING, ERROR, CRITICAL.",
    )
    environment: str = Field(
        default="development",
        description="Deployment environment: development, staging, production, test.",
    )

    @field_validator("log_level")
    @classmethod
    def _validate_log_level(cls, value: str) -> str:
        """Normalize to uppercase and reject unknown level names.

        Uses the public ``logging.getLevelNamesMapping()`` (3.11+) so custom
        levels registered elsewhere in the process are also accepted.
        """
        normalized = value.strip().upper()
        if normalized not in logging.getLevelNamesMapping():
            raise ValueError(
                f"Invalid log_level {value!r}; expected one of "
                f"{sorted(logging.getLevelNamesMapping())}"
            )
        return normalized

    @field_validator("environment")
    @classmethod
    def _validate_environment(cls, value: str) -> str:
        """Normalize to lowercase and reject unknown environment names."""
        normalized = value.strip().lower()
        if normalized not in _ALLOWED_ENVIRONMENTS:
            raise ValueError(
                f"Invalid environment {value!r}; expected one of "
                f"{sorted(_ALLOWED_ENVIRONMENTS)}"
            )
        return normalized


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide ``Settings`` singleton.

    Cached so environment parsing and validation happen exactly once per
    process. Tests that need fresh env values should call
    ``get_settings.cache_clear()`` before re-importing.
    """
    return Settings()
