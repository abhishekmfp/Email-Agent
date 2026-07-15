"""Configuration package for Email-Agent.

Exposes the application ``Settings`` model and the cached ``get_settings()``
accessor. Import from this package rather than the submodule::

    from email_agent.config import Settings, get_settings
"""

from __future__ import annotations

from email_agent.config.settings import (
    AnthropicSettings,
    Settings,
    get_settings,
)

__all__ = ["AnthropicSettings", "Settings", "get_settings"]
