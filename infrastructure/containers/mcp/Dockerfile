FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    curl \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv

COPY pyproject.toml README.md ./
RUN uv pip install --system --no-cache-dir -e .

COPY src/ ./src/

RUN mkdir -p /app/data

EXPOSE 8765

HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
    CMD curl -f http://localhost:8765/health || exit 1

CMD ["uv", "run", "python", "src/mcp_server/server.py"]
