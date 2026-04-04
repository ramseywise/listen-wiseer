"""Single source of truth for all repo paths.

Every module that needs a file path imports from here instead of
computing paths relative to __file__.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT: Path = Path(__file__).resolve().parent.parent
DATA_DIR: Path = REPO_ROOT / "data"
ARCHIVED_DIR: Path = DATA_DIR / "archived"
CACHE_DIR: Path = DATA_DIR / "cache"
MODELS_DIR: Path = REPO_ROOT / "models"
DB_PATH: Path = REPO_ROOT / "infrastructure" / "db" / "listen_wiseer.db"
