"""Application bootstrap for Email-Agent.

Milestone M1 — Project Foundation only. This module establishes the
application entry point and confirms the project starts successfully. It
contains NO application features, business logic, configuration loading,
or external integrations (FastAPI / OpenAI / Gmail). Those are deferred
to later milestones.
"""

from __future__ import annotations

import logging
import sys

logger = logging.getLogger(__name__)

# Exact startup banner required by the M1 bootstrap spec.
STARTUP_MESSAGE = " Email-Agent started successfully"


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
