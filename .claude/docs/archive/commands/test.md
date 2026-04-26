---
name: test
description: "Run targeted tests. Pass a module, file, or test name as argument. Defaults to full unit suite."
tools: Read, Bash, Grep, Glob
---

Run tests based on `$ARGUMENTS`:

## Argument handling

- **No argument**: `uv run pytest tests/unit/ --tb=short -q`
- **Module name** (e.g. `recommend`): `uv run pytest tests/unit/ -k "$ARGUMENTS" --tb=short -v`
- **File path** (e.g. `tests/unit/test_train.py`): `uv run pytest $ARGUMENTS --tb=short -v`
- **Test name** (e.g. `test_gmm_fit`): `uv run pytest tests/unit/ -k "$ARGUMENTS" --tb=short -v`
- **`--failed`**: `uv run pytest tests/unit/ --lf --tb=short -v` (rerun last failures)

## After running

Report:
- Pass/fail count
- Any failures: paste the short traceback
- If all pass: one line confirmation, nothing more
