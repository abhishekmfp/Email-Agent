"""Application bootstrap for Email-Agent.

Milestone M1 — Project Foundation established the entry point. M7 adds the
FastAPI ``app`` object (built by the interface layer) for ``uvicorn
email_agent.main:app`` and preserves the ``main()`` bootstrap for the CLI/script
path. The CLI entry point itself lives in ``email_agent.interface.cli``.
"""

from __future__ import annotations

import logging
import sys

from fastapi import FastAPI

logger = logging.getLogger(__name__)

# Exact startup banner required by the M1 bootstrap spec.
STARTUP_MESSAGE = " Email-Agent started successfully"

# FastAPI application, constructed lazily so importing this module does not
# trigger heavy dependency construction at import time (tests import ``app`` on
# demand). Built once at process start by the ASGI server / first access.
app = None


def get_app() -> FastAPI:
    """Construct and cache the FastAPI app (dependency graph built once)."""
    global app
    if app is None:
        from email_agent.interface.api import create_app

        app = create_app()
    return app


def configure_logging() -> None:
    """Configure root logging for the application entry point.

    Uses a minimal, production-sane stream handler. Format/level are kept
    simple on purpose — richer log configuration belongs to a later milestone.
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stdout,
    )


def main() -> int:
    """Application entry point.

    Performs the minimal bootstrap steps for the foundation milestone and
    returns a process exit code.

    Returns:
        int: 0 on successful startup, non-zero on failure.
    """
    configure_logging()
    logger.info(STARTUP_MESSAGE)
    return 0


if __name__ == "__main__":
    sys.exit(main())
