"""Smoke tests for the M1 bootstrap entry point (freeze boundary: M1 only)."""

from __future__ import annotations

import logging

import pytest

from email_agent.main import STARTUP_MESSAGE, main


def test_main_returns_zero() -> None:
    """main() must exit cleanly with process code 0."""
    assert main() == 0


def test_main_logs_startup_banner(caplog: pytest.LogCaptureFixture) -> None:
    """The exact startup banner must be emitted at INFO."""
    with caplog.at_level(logging.INFO):
        main()
    assert any(STARTUP_MESSAGE in rec.message for rec in caplog.records)
    assert any(rec.levelno == logging.INFO for rec in caplog.records)
