---
paths: []
---

# Hard Rules — All Projects

## Workflow discipline

- Implement one plan step at a time — do not skip ahead
- Never refactor outside the scope of the current plan step
- Always confirm before touching `pyproject.toml`, CI config, or infra files
- Never commit model weights, large data files, or notebooks with output cells
- Notebooks are for exploration only — move validated logic to `src/`

## Before any multi-file change or refactor

1. Present a numbered plan of what will be modified, created, and deleted
2. Wait for explicit user approval before making any changes
3. Never delete files, agents, skills, commands, or config — list candidates and wait for confirmation
4. If scope expands mid-task, stop and re-present the updated plan

## File paths

- All paths must be anchored to the repo root — never relative to CWD
- Use `Path(__file__).resolve().parent` or a shared `src/paths.py` that defines `REPO_ROOT`
- Apply this to DB connections, file imports, config loading, and notebook paths

## Code quality

- Type hints on all function signatures — no untyped public APIs
- Docstrings on any function that isn't immediately obvious from its name and signature
- No mutable default arguments — `def f(x=None)` not `def f(x=[])`
- Catch specific exceptions — no bare `except:` or `except Exception:`
- No `print()` in production code — use `logger.debug/info/warning/error`
- No magic numbers — use named constants or config values
- No single-letter variable names outside comprehensions, lambdas, or loop counters
- Functions over 40 lines → consider splitting
- Nesting over 3 levels → consider early returns or extraction
- Every new function gets at least one test

## Configuration

- Never hardcode paths, secrets, config values, or hyperparameters
- Config files or env vars only
- Seed all randomness: `torch.manual_seed()`, `np.random.seed()`, `random.seed()`

## Resource-constrained execution

Ask before running if any of the following apply:

1. **Costly** — API calls, cloud resources, anything that incurs $ cost
2. **Token/memory intensive** — large file/model loads, datasets >10k rows
3. **Long-running** — model training, full test suites without `-k`, estimated >30s

Prefer:
- Dry-run flags (`--dry-run`, `-n`) before destructive or expensive ops
- Targeted `pytest -k <filter>` or specific file path over full suite
- Subsampled data for local validation — log the subsample size
