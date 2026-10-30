"""Local readiness check: API keys, DuckDB tables, trained models, Navidrome.

Never prints secret values — only whether each key is set.

Run:
    PYTHONPATH=src uv run python -m utils.doctor            # report, always exit 0
    PYTHONPATH=src uv run python -m utils.doctor --strict   # exit 1 if any warning
    make doctor
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from dataclasses import dataclass, field
from pathlib import Path

import duckdb

from paths import CACHE_DIR, DB_PATH, MODELS_DIR
from sources.subsonic import SubsonicClient
from utils.exceptions import SourceError

# (settings field, what it enables). anthropic is the only hard requirement for chat.
API_KEYS: tuple[tuple[str, str], ...] = (
    ("anthropic_api_key", "chat agent (required)"),
    ("tavily_api_key", "artist/genre context"),
    ("last_fm_api_key", "Last.fm similar artists/tags"),
    ("listenbrainz_token", "ListenBrainz radio/CF"),
    ("listenbrainz_user", "ListenBrainz radio/CF"),
    ("youtube_api_key", "YouTube playback links"),
    ("jamendo_client_id", "legal CC downloads"),
    ("langfuse_public_key", "tracing (optional)"),
)
REQUIRED_KEYS: frozenset[str] = frozenset({"anthropic_api_key"})

REQUIRED_MODELS: tuple[str, ...] = ("gmm_corpus.pkl", "scaler_corpus.pkl")
CORPUS_CACHE = "corpus_features.parquet"


@dataclass
class DoctorReport:
    keys: dict[str, bool] = field(default_factory=dict)
    db_path: Path = DB_PATH
    db_ok: bool = False
    db_error: str | None = None
    table_counts: dict[str, int] = field(default_factory=dict)
    models: dict[str, bool] = field(default_factory=dict)
    n_classifiers: int = 0
    corpus_cache: bool = False
    navidrome_url: str | None = None  # None = not checked
    navidrome_songs: int | None = None  # None = unreachable
    navidrome_error: str | None = None
    warnings: list[str] = field(default_factory=list)


def check_keys(source: object) -> dict[str, bool]:
    """Map each known key name → whether it has a non-empty value on ``source``."""
    return {name: bool(str(getattr(source, name, "") or "").strip()) for name, _ in API_KEYS}


def _is_lfs_pointer(path: Path) -> bool:
    with path.open("rb") as fh:
        return fh.read(40).startswith(b"version https://git-lfs")


def table_counts(db_path: Path) -> dict[str, int]:
    """Row count per base table, opened read-only so the DB file is never touched."""
    conn = duckdb.connect(str(db_path), read_only=True)
    try:
        names = [
            r[0]
            for r in conn.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_type = 'BASE TABLE' ORDER BY table_name"
            ).fetchall()
        ]
        # names come from information_schema, not user input
        sql = 'SELECT COUNT(*) FROM "{}"'
        return {n: int(conn.execute(sql.format(n)).fetchall()[0][0]) for n in names}
    finally:
        conn.close()


def navidrome_songs(client: SubsonicClient) -> int:
    """Song count from Navidrome's scan status; closes ``client``. Raises SourceError."""

    async def _count() -> int:
        try:
            return (await client.scan_status()).count
        finally:
            await client.aclose()

    return asyncio.run(_count())


def navidrome_configured(settings: object) -> bool:
    """Blank user or password = player app not set up → skip the check, don't report it down."""
    return bool(
        getattr(settings, "navidrome_user", "") and getattr(settings, "navidrome_password", "")
    )


def run_checks(
    source: object,
    db_path: Path = DB_PATH,
    models_dir: Path = MODELS_DIR,
    cache_dir: Path = CACHE_DIR,
    navidrome: SubsonicClient | None = None,
) -> DoctorReport:
    """Collect the full readiness report; no side effects on disk.

    Navidrome is optional (the player app needs it, chat doesn't), so its state is
    reported but never adds a warning.
    """
    report = DoctorReport(keys=check_keys(source), db_path=db_path)

    if navidrome is not None:
        report.navidrome_url = navidrome.base_url
        try:
            report.navidrome_songs = navidrome_songs(navidrome)
        except SourceError as exc:
            report.navidrome_error = str(exc).splitlines()[0]

    for name in sorted(REQUIRED_KEYS):
        if not report.keys.get(name):
            report.warnings.append(f"{name.upper()} not set — the chat agent cannot run")

    if not db_path.exists():
        report.db_error = "missing"
    elif _is_lfs_pointer(db_path):
        report.db_error = "Git LFS pointer, not a database — run `git lfs pull`"
    else:
        try:
            report.table_counts = table_counts(db_path)
            report.db_ok = True
        except duckdb.Error as exc:
            report.db_error = str(exc).splitlines()[0]
    if report.db_error:
        report.warnings.append(f"DuckDB not usable at {db_path}: {report.db_error}")
    elif report.table_counts.get("plays", 0) == 0:
        report.warnings.append(
            "`plays` is empty — history tools return nothing; drop the Spotify export in "
            "data/listening_history/ then `make import-history && make resolve-ids`"
        )

    report.models = {m: (models_dir / m).exists() for m in REQUIRED_MODELS}
    report.n_classifiers = len(list(models_dir.glob("classifier_*.pkl")))
    report.corpus_cache = (cache_dir / CORPUS_CACHE).exists()
    if not all(report.models.values()) or not report.corpus_cache:
        report.warnings.append(
            "models not trained — recommend_* tools will be unavailable; run `make train`"
        )
    elif report.n_classifiers == 0:
        report.warnings.append("no classifier_*.pkl — playlist recommendations disabled")

    return report


def render(report: DoctorReport) -> str:
    """Plain-text report. Keys show set/unset only."""

    def mark(ok: bool) -> str:
        return "ok " if ok else "-- "

    lines = ["listen-wiseer doctor", "", "API keys (set / unset — values never shown):"]
    purpose = dict(API_KEYS)
    for name, ok in report.keys.items():
        lines.append(
            f"  {mark(ok)}{name.upper():<22} {'set' if ok else 'unset':<6} {purpose[name]}"
        )

    lines += ["", f"DuckDB ({report.db_path}):"]
    if report.db_ok:
        for name, n in report.table_counts.items():
            lines.append(f"  {name:<24} {n:>8}")
    else:
        lines.append(f"  -- {report.db_error}")

    lines += ["", "Models:"]
    for name, ok in report.models.items():
        lines.append(f"  {mark(ok)}{name}")
    lines.append(f"  {mark(report.n_classifiers > 0)}classifier_*.pkl x{report.n_classifiers}")
    lines.append(f"  {mark(report.corpus_cache)}data/cache/{CORPUS_CACHE}")

    if report.navidrome_url is not None:
        lines += ["", f"Navidrome ({report.navidrome_url}, optional — player app):"]
        if report.navidrome_songs is not None:
            lines.append(f"  ok reachable, {report.navidrome_songs} songs")
        else:
            lines.append(f"  -- unreachable: {report.navidrome_error} (`make navidrome`)")

    lines.append("")
    if report.warnings:
        lines.append(f"Warnings ({len(report.warnings)}):")
        lines += [f"  ! {w}" for w in report.warnings]
    else:
        lines.append("All checks passed.")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check keys, DuckDB and models are ready.")
    parser.add_argument("--strict", action="store_true", help="exit 1 if any warning")
    args = parser.parse_args(argv)

    from utils.config import settings

    navidrome = (
        SubsonicClient.from_settings(settings, timeout=3.0)
        if navidrome_configured(settings)
        else None
    )
    report = run_checks(settings, navidrome=navidrome)
    sys.stdout.write(render(report))
    return 1 if args.strict and report.warnings else 0


if __name__ == "__main__":
    sys.exit(main())
