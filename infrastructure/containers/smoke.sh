#!/usr/bin/env bash
# Smoke-test the running compose stack: postgres, api (health → web → stream), mcp.
# Usage: COMPOSE="docker compose -f ..." API_PORT=8000 smoke.sh   (make infra-smoke sets both)
set -uo pipefail

API="http://localhost:${API_PORT:-8000}"
COMPOSE=${COMPOSE:-docker compose -f infrastructure/containers/docker-compose.yml}
failed=0
ok() { echo "✓ $*"; }
ko() { echo "✗ $*"; failed=1; }
json() { python3 -c "import json, sys; d = json.load(sys.stdin); print($1)"; }

echo "=== Container status ==="
$COMPOSE ps --format 'table {{.Name}}\t{{.Status}}'

echo "=== Postgres ==="
$COMPOSE exec -T postgres pg_isready -q -U wiseer -d listen_wiseer && ok "postgres ready" || ko "postgres not ready"

echo "=== API ($API) ==="
health=$(curl -sf --max-time 5 "$API/api/health") || health=""
echo "  /api/health → ${health:-<no response>}"
[[ "$health" == *'"navidrome":true'* ]] && ok "api up, navidrome reachable" || ko "api health: navidrome not true"

curl -sf --max-time 5 "$API/" | grep -q '<div id="root">' && ok "/ serves index.html" || ko "/ did not serve the web build"

album=$(curl -sf --max-time 10 "$API/api/albums?size=1" | json 'd[0]["id"] if d else ""' 2>/dev/null)
song=$( [ -n "$album" ] && curl -sf --max-time 10 "$API/api/albums/$album" | json 'd["songs"][0]["id"]' 2>/dev/null)
if [ -n "${song:-}" ]; then
    out=$(curl -s --max-time 15 -o /dev/null -H 'Range: bytes=0-1023' \
        -w '%{http_code} %{size_download}B %{content_type}' "$API/api/stream/$song")
    echo "  /api/stream/$song (Range: bytes=0-1023) → $out"
    [[ "$out" == 206\ 1024B* ]] && ok "stream honours Range (206)" || ko "stream: expected 206 with 1024 bytes"
else
    ko "no song to stream (empty library? run make seed-library)"
fi

echo "=== MCP (port 8765, streamable HTTP) ==="
curl -sf --max-time 5 -X POST http://localhost:8765/mcp \
    -H 'Content-Type: application/json' \
    -H 'Accept: application/json, text/event-stream' \
    -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"infra-smoke","version":"0"}}}' \
    | grep -q '"serverInfo"' && ok "mcp initialize ok" || ko "mcp not responding"

exit $failed
