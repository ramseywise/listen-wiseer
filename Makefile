# Compose resolves ${VARS} from .env next to the compose file, not the repo root — pass it explicitly.
COMPOSE = docker compose $(if $(wildcard .env),--env-file .env) -f infrastructure/containers/docker-compose.yml

.PHONY: help infra-up infra-down infra-build infra-ps infra-logs infra-smoke app doctor mcp-server navidrome lint format test test-unit test-fast test-integration test-data notebook init-db data-sync import-history resolve-ids train train-cat train-compare eval-ci eval-full eval-unit eval-trajectory eval-e2e pull status push quick-pr ship

help:
	@echo "listen-wiseer targets:"
	@echo "  app          Chainlit UI (runs doctor first, non-fatal)"
	@echo "  doctor       Check API keys (set/unset), DuckDB row counts, models/*.pkl"
	@echo "  mcp-server   MCP server (agent tools for other MCP clients)"
	@echo "  navidrome    Music server for data/library/ (http://localhost:4533)"
	@echo "  init-db      Migrate DuckDB schema; import data/archived/ CSVs if present"
	@echo "  data-sync    Last.fm genre tags → genre profiles (archived library)"
	@echo "  import-history  Spotify privacy-export JSON (data/listening_history/) → plays"
	@echo "  resolve-ids  Match played tracks to MusicBrainz/Deezer IDs (ARGS=\"--limit 500\")"
	@echo "  train        Fit GMM + LightGBM → models/*.pkl"
	@echo "  test         Full test suite"
	@echo "  test-unit    Unit tests (with coverage)"
	@echo "  test-fast    Unit tests (no coverage, quick)"
	@echo "  test-integration  Integration tests (needs DuckDB)"
	@echo "  eval-ci      Heuristic eval vs baseline — fails on >5% regression (no API cost)"
	@echo "  eval-full    Full RAGAS eval, all tiers (costs money, needs ANTHROPIC_API_KEY)"
	@echo "  eval-unit    Tier 1 intent/route eval (free, CI-safe)"
	@echo "  eval-trajectory  Tier 2 trajectory eval (costs money)"
	@echo "  eval-e2e     Tier 3 RAGAS + tool-correctness eval (costs money)"
	@echo "  lint         ruff check + format check + pyright (src/)"
	@echo "  format       ruff fix + format"
	@echo "  infra-up     Docker stack"
	@echo "  infra-down   Docker stack teardown"
	@echo "  infra-build  Rebuild Docker images"
	@echo "  infra-ps     Show container status"
	@echo "  infra-smoke  Smoke-test running stack (postgres + app + mcp)"
	@echo "  notebook     Jupyter Lab"
	@echo "  pull         git pull origin main"
	@echo "  status       Show branch, unpushed commits, staged changes, open PRs"
	@echo "  push         Push current branch to origin"
	@echo "  quick-pr     Create PR from current branch with auto-generated body"
	@echo "  ship         lint → test → pull → push → PR"

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
	@$(COMPOSE) exec -T postgres pg_isready -U wiseer -d listen_wiseer \
		&& echo "✓ postgres ready" || echo "✗ postgres not ready"
	@echo ""
	@echo "=== App (port 8501) ==="
	@curl -sf --max-time 5 http://localhost:8501 > /dev/null \
		&& echo "✓ app responding" || echo "✗ app not responding (may still be starting)"
	@echo ""
	@echo "=== MCP (port 8765, streamable HTTP) ==="
	@curl -sf --max-time 5 -X POST http://localhost:8765/mcp \
		-H 'Content-Type: application/json' \
		-H 'Accept: application/json, text/event-stream' \
		-d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"infra-smoke","version":"0"}}}' \
		| grep -q '"serverInfo"' \
		&& echo "✓ mcp initialize ok" || echo "✗ mcp not responding"

app:
	-@PYTHONPATH=src uv run python -m utils.doctor
	PYTHONPATH=src uv run chainlit run src/app/main.py

doctor:  ## Keys set (bool only), DuckDB row counts, models present, plays empty?
	PYTHONPATH=src uv run python -m utils.doctor

mcp-server:
	PYTHONPATH=src uv run python src/mcp_server/server.py

navidrome:  ## Serve legal downloads in data/library/ to Subsonic apps
	mkdir -p data/library
	$(COMPOSE) --profile library up -d navidrome

lint:
	uv run ruff check src/ --unsafe-fixes
	uv run ruff format --check src/
	uv run pyright src

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
	@echo "Bootstrapping DuckDB (schema migration; CSV import only if data/archived/ exists)..."
	PYTHONPATH=src uv run python -m etl.bootstrap

data-sync:
	PYTHONPATH=src uv run python -m etl.sync

import-history:  ## Load Spotify privacy-export JSON from data/listening_history/ into plays
	PYTHONPATH=src uv run python -m etl.history

resolve-ids:  ## Match played tracks to MusicBrainz/Deezer IDs (resumable; ARGS="--limit 500")
	PYTHONPATH=src uv run python -m etl.resolve $(ARGS)

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

# CI gate: heuristic graders only, no LLM calls.
# Compares against evals/datasets/eval_baseline.json; exits 1 if any metric
# drops >5% from baseline. Safe for fork PRs (no API key required).
eval-ci:
	PYTHONPATH=src uv run python -m evals.eval_ci

# Full RAGAS eval across all tiers (costs money).
# Requires ANTHROPIC_API_KEY in the environment.
eval-full:
	CONFIRM_EXPENSIVE_OPS=true PYTHONPATH=src uv run python -m evals.run_agent_eval --tier all

eval-unit:
	PYTHONPATH=src uv run python -m evals.run_agent_eval --tier 1

eval-trajectory:
	CONFIRM_EXPENSIVE_OPS=true PYTHONPATH=src uv run python -m evals.run_agent_eval --tier 2

eval-e2e:
	CONFIRM_EXPENSIVE_OPS=true PYTHONPATH=src uv run python -m evals.run_agent_eval --tier 3

# precommit comes from Makefile.common (identical recipe) — included below.

# --- Git workflow ---
# pull, push, quick-pr come from Makefile.common — canon (~/.claude/Makefile.common).
# Local overrides below: status (adds open-PR listing), ship (adds lint + test).

include $(HOME)/.claude/Makefile.common

status:  ## Show branch, unpushed commits, staged changes, open PRs
	@echo "=== listen-wiseer ==="
	@echo "Branch: $$(git branch --show-current)"
	@echo "Unpushed:"
	@git log origin/$$(git branch --show-current)..HEAD --oneline 2>/dev/null || echo "  (no remote tracking)"
	@echo "Staged:"
	@git diff --cached --stat 2>/dev/null || true
	@echo "Modified:"
	@git diff --stat 2>/dev/null || true
	@echo "Open PRs:"
	@gh pr list --state open --json number,title,headBranch --jq '.[] | "#\(.number) \(.title) [\(.headBranch)]"' 2>/dev/null || echo "  (none)"

ship: lint test pull push quick-pr  ## lint → test → pull → push → PR
