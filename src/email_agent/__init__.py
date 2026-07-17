"""Email-Agent — AI-powered email assistant with human-in-the-loop approval.

Single source of truth for the package version. ``AppSettings.app_version`` and
``GET /health`` both read from this constant so there is exactly one version
definition (M7 decision #2).
"""

from __future__ import annotations

__version__ = "0.1.0"
