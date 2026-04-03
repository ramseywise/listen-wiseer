COMPOSE = docker compose -f infrastructure/containers/docker-compose.yml

.PHONY: infra-up infra-down infra-logs app mcp-server auth lint format test test-unit test-data notebook init-db data-sync train

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

train:
	PYTHONPATH=src uv run python -m recommend.train
