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
# `embeddings` extra: semantic memory search (sentence-transformers). torch resolves to
# the CPU-only wheel on Linux via [tool.uv.sources] in pyproject.toml.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project --extra embeddings

# ── runtime ──────────────────────────────────────────────────────────────────
FROM python:3.11-slim

# libgomp1: OpenMP runtime for LightGBM; curl: HEALTHCHECK
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl libgomp1 \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 1000 app

WORKDIR /app
ENV PATH=/app/.venv/bin:$PATH \
    PYTHONPATH=/app/src \
    PYTHONUNBUFFERED=1

COPY --from=builder /app/.venv /app/.venv
COPY src/ ./src/

RUN mkdir -p data/listening_history data/cache logs models infrastructure/db \
    && chown -R app:app /app/data /app/logs /app/models /app/infrastructure \
    && chown app:app /app

USER app

EXPOSE 8501

HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8501/ || exit 1

CMD ["chainlit", "run", "src/app/main.py", "--host", "0.0.0.0", "--port", "8501"]
