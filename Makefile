COMPOSE = docker compose -f infrastructure/containers/docker-compose.yml

.PHONY: help infra-up infra-down infra-build infra-ps infra-logs infra-smoke app mcp-server auth lint format test test-unit test-fast test-integration test-data notebook init-db data-sync train train-cat train-compare eval-unit eval-trajectory eval-e2e

help:
	@echo "listen-wiseer targets:"
	@echo "  app          Chainlit UI"
	@echo "  mcp-server   MCP server (triggers OAuth on first run)"
	@echo "  auth         Spotify OAuth → .spotify_cache"
	@echo "  init-db      Bootstrap DuckDB from CSVs"
	@echo "  data-sync    Live Spotify → DuckDB (requires .spotify_cache)"
	@echo "  train        Fit GMM + LightGBM → models/*.pkl"
	@echo "  test         Full test suite"
	@echo "  test-unit    Unit tests (with coverage)"
	@echo "  test-fast    Unit tests (no coverage, quick)"
	@echo "  test-integration  Integration tests (needs DuckDB/Spotify)"
	@echo "  eval-unit    Tier 1 intent/route eval (free, CI-safe)"
	@echo "  eval-trajectory  Tier 2 trajectory eval (costs money)"
	@echo "  eval-e2e     Tier 3 RAGAS + DeepEval eval (costs money)"
	@echo "  lint         ruff check + format check"
	@echo "  format       ruff fix + format"
	@echo "  infra-up     Docker stack"
	@echo "  infra-down   Docker stack teardown"
	@echo "  infra-build  Rebuild Docker images"
	@echo "  infra-ps     Show container status"
	@echo "  infra-smoke  Smoke-test running stack (postgres + app)"
	@echo "  notebook     Jupyter Lab"

infra-up:
	$(COMPOSE) up -d

infra-down:
	$(COMPOSE) down --volumes --remove-orphans

infra-build:
	$(COMPOSE) build

infra-ps:
	$(COMPOSE) ps

infra-logs:
	$(COMPOSE) logs -f

infra-smoke:
	@echo "=== Container status ==="
	@$(COMPOSE) ps
	@echo ""
	@echo "=== Postgres ==="
	@$(COMPOSE) exec -T postgres pg_isready -U postgres -d listenwise \
		&& echo "✓ postgres ready" || echo "✗ postgres not ready"
	@echo ""
	@echo "=== App (port 8501) ==="
	@curl -sf --max-time 5 http://localhost:8501 > /dev/null \
		&& echo "✓ app responding" || echo "✗ app not responding (may still be starting)"

app:
	PYTHONPATH=src uv run chainlit run src/app/main.py

mcp-server:
	PYTHONPATH=src uv run python src/mcp_server/server.py

auth:
	PYTHONPATH=src uv run python -c "from spotify.auth import SpotifyAuth; SpotifyAuth().authenticate(); print('Auth complete — .spotify_cache written.')"

lint:
	uv run ruff check src/ --unsafe-fixes
	uv run ruff format --check src/

format:
	uv run ruff check --fix src/
	uv run ruff format src/

test:
	uv run pytest

test-unit:
	uv run pytest tests/unit/ -v

test-fast:
	uv run pytest tests/unit/ --no-cov -q

test-integration:
	uv run pytest tests/integration/ -v

test-data:
	uv run pytest tests/unit/test_data_schemas.py tests/unit/test_data_loader.py -v

notebook:
	uv run jupyter lab notebooks/

init-db:
	@echo "Bootstrapping DuckDB from archived CSVs..."
	PYTHONPATH=src uv run python -m etl.bootstrap

data-sync:
	@echo "Requires .spotify_cache - run 'make auth' once to authenticate first"
	PYTHONPATH=src uv run python -m etl.sync

# Default training (LightGBM, same as before but with fixed features)
train:
	PYTHONPATH=src uv run python -m recommend.train

# Train with CatBoost instead
train-cat:
	PYTHONPATH=src uv run python -m recommend.train --model-type catboost

# Head-to-head comparison (informational, no models saved)
train-compare:
	PYTHONPATH=src uv run python -m recommend.train --compare

# --- Agent eval harness ---

eval-unit:
	PYTHONPATH=src uv run python -m evals.run_agent_eval --tier 1

eval-trajectory:
	CONFIRM_EXPENSIVE_OPS=true PYTHONPATH=src uv run python -m evals.run_agent_eval --tier 2

eval-e2e:
	CONFIRM_EXPENSIVE_OPS=true PYTHONPATH=src uv run python -m evals.run_agent_eval --tier 3
