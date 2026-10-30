# syntax=docker/dockerfile:1
# Player app image: FastAPI (src/api) + the built web/ it serves at /. Also runs db-init.
# Build context: repo root (see docker-compose.yml). Dockerfile.dockerignore alongside
# limits the context to pyproject.toml, uv.lock, src/ and web/ sources.

# ── web: Vite build → /web/dist ──────────────────────────────────────────────
FROM node:22-slim AS web

WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN --mount=type=cache,target=/root/.npm npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run build

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
# `embeddings` extra: semantic memory search for the agent (sentence-transformers; torch
# resolves to the CPU-only wheel on Linux via [tool.uv.sources]). UV_EXTRAS= drops it.
ARG UV_EXTRAS="--extra embeddings"
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project ${UV_EXTRAS}

# ── runtime ──────────────────────────────────────────────────────────────────
FROM python:3.11-slim AS runtime

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
# paths.WEB_DIST_DIR = REPO_ROOT/web/dist = /app/web/dist
COPY --from=web /web/dist ./web/dist

RUN mkdir -p data/listening_history data/cache data/library logs models infrastructure/db \
    && chown -R app:app /app/data /app/logs /app/models /app/infrastructure \
    && chown app:app /app

USER app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD curl -fsS http://localhost:8000/api/health || exit 1

CMD ["uvicorn", "api.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
