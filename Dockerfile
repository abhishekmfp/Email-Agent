# syntax=docker/dockerfile:1

# Email-Agent — M8 dev/test image.
# The CI gate runs:  docker build -t email-agent . && docker run --rm email-agent uv run pytest -q
# This image ships the full toolchain so `uv run pytest` works out of the box.
# It is NOT a slim runtime image; serving the app is documented separately (see README).

FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1

# uv is the package manager; install it standalone (no pip build deps needed).
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Install dependencies first (better layer caching) using the locked toolchain.
COPY pyproject.toml uv.lock ./
RUN uv sync --dev --locked

# Copy the project source + tests.
COPY src ./src
COPY tests ./tests

# Default command: run the test suite (matches the M8 demo command).
CMD ["uv", "run", "pytest", "-q"]
