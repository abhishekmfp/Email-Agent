"""Interface layer for Email-Agent (M7).

Thin translation shell over the VERIFIED application use cases. Owns the
transport contract (DTOs), dependency wiring, structured logging, and the
unified error envelope. Never exposes domain types directly and never
introduces business rules (Translation Boundary Principle). See
``interface.api`` (FastAPI) and ``interface.cli`` (argparse).
"""

from __future__ import annotations

__all__ = ["api", "cli", "container", "errors", "logging", "models", "translation"]
