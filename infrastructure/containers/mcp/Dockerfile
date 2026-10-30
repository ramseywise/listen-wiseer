# syntax=docker/dockerfile:1
# Build context: repo root (see docker-compose.yml). Dockerfile.dockerignore alongside
# limits the context to pyproject.toml, uv.lock and src/.

# ── builder: compile wheels into /app/.venv ──────────────────────────────────
FROM python:3.11-slim AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir uv

WORKDIR /app
COPY pyproject.toml uv.lock ./
# Code runs from src/ via PYTHONPATH, so the project itself is not installed.
# Optional extras would be added here, e.g. `--extra <name>`.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

# ── runtime ──────────────────────────────────────────────────────────────────
FROM python:3.11-slim

RUN useradd --create-home --uid 1000 app

WORKDIR /app
ENV PATH=/app/.venv/bin:$PATH \
    PYTHONPATH=/app/src \
    PYTHONUNBUFFERED=1 \
    MCP_TRANSPORT=streamable-http \
    MCP_SERVER_HOST=0.0.0.0 \
    MCP_SERVER_PORT=8765

COPY --from=builder /app/.venv /app/.venv
COPY src/ ./src/

RUN mkdir -p data models infrastructure/db \
    && chown -R app:app /app/data /app/models /app/infrastructure \
    && chown app:app /app

USER app

EXPOSE 8765

# TCP probe on the streamable-http port (no curl in this image)
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import os, socket; socket.create_connection(('127.0.0.1', int(os.environ['MCP_SERVER_PORT'])), 2)" || exit 1

CMD ["python", "src/mcp_server/server.py"]
