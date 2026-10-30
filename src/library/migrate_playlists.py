"""
One-off: DuckDB ``local_playlists`` → Navidrome playlists (D2 — Navidrome is the source of
truth; ``local_playlists`` stays as JSPF export only). Each track is matched to a library song;
unmatched tracks are reported, not dropped silently. A local playlist whose name already exists
in Navidrome is skipped, so re-running doesn't duplicate. No rows → no-op.

Run:
    PYTHONPATH=src uv run python -m library.migrate_playlists [--dry-run]
    make migrate-playlists
"""

import argparse
import asyncio
import sys
from dataclasses import dataclass, field

import duckdb

from etl.db import get_connection
from library.match import MatchCache, default_cache
from library.playlists import get_tracks, list_playlists
from library.to_navidrome import song_ids_for
from sources.schemas import TrackRef
from sources.subsonic import SubsonicClient
from utils.logging import get_logger

log = get_logger(__name__)


@dataclass
class Migrated:
    name: str
    n_tracks: int
    navidrome_id: str | None = None  # None = skipped (exists) or dry run
    skipped: bool = False
    unmatched: list[TrackRef] = field(default_factory=list)


def load_local(conn: duckdb.DuckDBPyConnection) -> list[tuple[str, list[TrackRef]]]:
    return [(p["name"], get_tracks(conn, p["id"])) for p in reversed(list_playlists(conn))]


async def migrate(
    client: SubsonicClient,
    local: list[tuple[str, list[TrackRef]]],
    *,
    dry_run: bool = False,
    cache: MatchCache | None = None,
) -> list[Migrated]:
    if not local:
        return []
    existing = {p.name for p in await client.playlists()}
    out: list[Migrated] = []
    for name, tracks in local:
        if name in existing:
            out.append(Migrated(name, len(tracks), skipped=True))
            continue
        song_ids, missed = await song_ids_for(client, tracks, cache=cache)
        report = Migrated(name, len(tracks), unmatched=[tracks[i] for i in missed])
        if not dry_run:
            report.navidrome_id = (await client.create_playlist(name, song_ids)).id
            existing.add(name)
        log.info(
            "migrate_playlists.playlist",
            name=name,
            matched=len(song_ids),
            unmatched=len(missed),
            dry_run=dry_run,
        )
        out.append(report)
    return out


def render(results: list[Migrated], *, dry_run: bool) -> str:
    if not results:
        return "No local playlists to migrate.\n"
    lines = []
    for r in results:
        if r.skipped:
            lines.append(f"= {r.name}: already in Navidrome, skipped")
            continue
        verb = "would create" if dry_run else "created"
        lines.append(f"+ {r.name}: {verb} with {r.n_tracks - len(r.unmatched)}/{r.n_tracks} tracks")
        lines += [f"    not in library: {t.artist} — {t.title}" for t in r.unmatched]
    return "\n".join(lines) + "\n"


async def _run(dry_run: bool) -> list[Migrated]:
    from utils.config import settings

    conn = get_connection(read_only=True)
    try:
        local = load_local(conn)
    finally:
        conn.close()
    client = SubsonicClient.from_settings(settings)
    try:
        return await migrate(client, local, dry_run=dry_run, cache=default_cache())
    finally:
        await client.aclose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Move DuckDB local_playlists to Navidrome.")
    parser.add_argument("--dry-run", action="store_true", help="match only; create nothing")
    args = parser.parse_args(argv)
    results = asyncio.run(_run(args.dry_run))
    sys.stdout.write(render(results, dry_run=args.dry_run))
    return 0


if __name__ == "__main__":
    sys.exit(main())
