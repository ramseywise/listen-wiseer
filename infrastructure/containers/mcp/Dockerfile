FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    curl \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv

COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev

COPY src/ ./src/

RUN mkdir -p /app/data

EXPOSE 8765

# MCP server uses stdio transport — no HTTP health endpoint
HEALTHCHECK NONE

CMD ["uv", "run", "--no-sync", "python", "src/mcp_server/server.py"]
