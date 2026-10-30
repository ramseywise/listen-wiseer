# Compose resolves ${VARS} from .env next to the compose file, not the repo root — pass it explicitly.
COMPOSE = docker compose $(if $(wildcard .env),--env-file .env) -f infrastructure/containers/docker-compose.yml
# API_PORT given on the make command line / shell wins over .env; the ?= default does not.
COMPOSE_ENV = $(if $(filter command line environment,$(origin API_PORT)),API_PORT=$(API_PORT))

.PHONY: help infra-up infra-down infra-build infra-ps infra-logs infra-smoke app dev doctor mcp-server navidrome seed-library migrate-playlists api web web-build lint format test test-unit test-fast test-integration test-data notebook init-db data-sync import-history resolve-ids train train-cat train-compare eval-ci eval-full eval-unit eval-trajectory eval-e2e pull status push quick-pr ship

help:
	@echo "listen-wiseer targets:"
	@echo "  app          Player API + assistant (doctor first, non-fatal); run \`make web\` alongside for the UI"
	@echo "  doctor       Check API keys (set/unset), DuckDB row counts, models/*.pkl"
	@echo "  mcp-server   MCP server (agent tools for other MCP clients)"
	@echo "  navidrome    Music server for MUSIC_DIR (default data/library/, http://localhost:4533)"
	@echo "  seed-library Download ~5 CC tracks from archive.org, create Navidrome admin, scan"
	@echo "  api          Player API (FastAPI) on 127.0.0.1:8000, reload (API_PORT=8010 to move)"
	@echo "  migrate-playlists  DuckDB local_playlists → Navidrome, report unmatched (ARGS=\"--dry-run\")"
	@echo "  web          Player web UI dev server (Vite, proxies /api → VITE_API_TARGET, default :8000)"
	@echo "  web-build    Build the web UI → web/dist (make api/app then serve it at /)"
	@echo "  dev          api + web together (Ctrl-C stops both)"
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
	@echo "  infra-up     Docker stack: postgres, navidrome, api + web on http://localhost:\$$API_PORT (8000), mcp"
	@echo "  infra-down   Docker stack teardown (volumes kept)"
	@echo "  infra-build  Rebuild Docker images"
	@echo "  infra-ps     Show container status"
	@echo "  infra-smoke  Smoke-test running stack (postgres, api health/web/stream, mcp)"
	@echo "  notebook     Jupyter Lab"
	@echo "  pull         git pull origin main"
	@echo "  status       Show branch, unpushed commits, staged changes, open PRs"
	@echo "  push         Push current branch to origin"
	@echo "  quick-pr     Create PR from current branch with auto-generated body"
	@echo "  ship         lint → test → pull → push → PR"

infra-up:  ## postgres + db-init + navidrome + api (web at http://localhost:$API_PORT) + mcp
	mkdir -p data/library/downloads logs
	$(COMPOSE_ENV) $(COMPOSE) up -d

infra-down:  ## keeps volumes (Navidrome users/playlists, Postgres); add -v by hand to wipe
	$(COMPOSE) down --remove-orphans

infra-build:
	$(COMPOSE_ENV) $(COMPOSE) build

infra-ps:
	$(COMPOSE) ps

infra-logs:
	$(COMPOSE) logs -f

infra-smoke:  ## postgres, /api/health (navidrome:true), / (index.html), Range stream → 206, mcp
	@COMPOSE="$(COMPOSE)" API_PORT=$$($(COMPOSE) port api 8000 | sed 's/.*://') \
		infrastructure/containers/smoke.sh

app:
	-@PYTHONPATH=src uv run python -m utils.doctor
	PYTHONPATH=src uv run uvicorn --factory api.app:create_app --host 127.0.0.1 --port $(API_PORT)

dev:  ## api (reload) + web (Vite) in one terminal; Ctrl-C stops both
	@trap 'kill 0' INT TERM; $(MAKE) --no-print-directory api & $(MAKE) --no-print-directory web & wait

doctor:  ## Keys set (bool only), DuckDB row counts, models present, plays empty?
	PYTHONPATH=src uv run python -m utils.doctor

mcp-server:
	PYTHONPATH=src uv run python src/mcp_server/server.py

navidrome:  ## Serve MUSIC_DIR (default data/library/) to the web player + Subsonic apps
	mkdir -p data/library/downloads
	$(COMPOSE) up -d navidrome

seed-library:  ## CC tracks → MUSIC_DIR/downloads/, first-run admin, startScan (ARGS="--no-record")
	PYTHONPATH=src uv run python -m library.seed $(ARGS)

migrate-playlists:  ## One-off: local_playlists → Navidrome via library.match (no-op if none)
	PYTHONPATH=src uv run python -m library.migrate_playlists $(ARGS)

API_PORT ?= 8000
api:  ## FastAPI backend for web/ (Navidrome proxy); localhost only
	PYTHONPATH=src uv run uvicorn --factory api.app:create_app --host 127.0.0.1 --port $(API_PORT) --reload --reload-dir src

web:  ## API_PORT=8010 make web → proxies to the API on that port
	VITE_API_TARGET=$${VITE_API_TARGET:-http://127.0.0.1:$(API_PORT)} npm --prefix web run dev

web-build:
	npm --prefix web run build

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
