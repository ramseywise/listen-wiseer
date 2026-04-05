COMPOSE = docker compose -f infrastructure/containers/docker-compose.yml

.PHONY: help infra-up infra-down infra-logs app mcp-server auth lint format test test-unit test-fast test-integration test-data notebook init-db data-sync train

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
	@echo "  lint         ruff check + format check"
	@echo "  format       ruff fix + format"
	@echo "  infra-up     Docker stack"
	@echo "  infra-down   Docker stack teardown"
	@echo "  notebook     Jupyter Lab"

infra-up:
	$(COMPOSE) up -d

infra-down:
	$(COMPOSE) down --volumes --remove-orphans

infra-logs:
	$(COMPOSE) logs -f

app:
	PYTHONPATH=src uv run chainlit run src/app/main.py

mcp-server:
	PYTHONPATH=src uv run python src/mcp_server/server.py

auth:
	PYTHONPATH=src uv run python -c "from spotify.auth import SpotifyAuth; SpotifyAuth().authenticate(); print('Auth complete — .spotify_cache written.')"

lint:
	uv run ruff check src/
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
	PYTHONPATH=src uv run python -m recommend.train

# Head-to-head comparison (informational, no models saved)
train-compare:
	PYTHONPATH=src uv run python -m recommend.train --compare
