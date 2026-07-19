"""Project-wide pytest fixtures.

Unit-test fixtures (sample_tracks_df, listening_history_dir) live in
tests/unit/conftest.py.

Integration-test fixtures live in tests/integration/conftest.py.
"""

import os

# Two separate OpenMP problems, both fixed here, both before lightgbm is imported.
#
# 1. Load order. LightGBM and torch (via sentence-transformers) each ship their own
#    libomp.dylib, and they are different builds. Whichever loads first wins; if
#    torch's wins, LightGBM training segfaults inside its C library. Importing
#    lightgbm below — before any test module pulls in torch — pins the runtime to
#    LightGBM's copy for the whole session.
# 2. Thread count. LightGBM's OpenMP thread pool races pytest-cov's SQLite writer,
#    which surfaces at the END of a run as `INTERNALERROR sqlite3.OperationalError`
#    / a failed assert in coverage's combine step. All tests report as passing but
#    pytest exits 3, so CI goes red on a green suite. Measured 2026-07-19 on
#    macOS/arm64: 3 of 5 runs failed by default, 13 of 13 passed with this pinned.
#
# Both are macOS/arm64-observed; the settings are harmless elsewhere. Set the env
# var before the import — LightGBM reads it when its runtime initializes.
os.environ.setdefault("OMP_NUM_THREADS", "1")

import lightgbm  # noqa: E402, F401
