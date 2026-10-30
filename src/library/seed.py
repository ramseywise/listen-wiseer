"""Seed the library with a few Creative Commons tracks from the Internet Archive and have
Navidrome index them — enough to exercise the player without a real collection.

Creates the Navidrome admin (NAVIDROME_USER / NAVIDROME_PASSWORD) on a fresh server via its
first-run ``/auth/createAdmin`` endpoint, downloads into $MUSIC_DIR/downloads/, then runs
``startScan`` and waits for it.

Run:
    PYTHONPATH=src uv run python -m library.seed               # record downloads in DuckDB
    PYTHONPATH=src uv run python -m library.seed --no-record   # files only, DB untouched
    make seed-library
"""

import argparse
import asyncio
import sys
import time
from pathlib import Path

import duckdb
import httpx

from etl.db import get_connection, init_schema
from library import downloads
from sources import archive_org
from sources.http import SourceClient
from sources.schemas import FreeTrack
from sources.subsonic import ScanStatus, SubsonicClient
from utils.config import settings
from utils.exceptions import SourceError
from utils.logging import configure_logging, get_logger

log = get_logger(__name__)

# (archive.org item, tracks to take) — netlabel releases with clean per-file artist/album tags,
# so Navidrome groups them into albums.
SEED_ITEMS: tuple[tuple[str, int], ...] = (
    ("DWK123", 3),  # ProleteR — Curses From Past Times (CC BY-NC-ND 3.0)
    ("Vkrsnl038MirandaShvangiradzeTalkToMeEp", 2),  # Miranda Shvangiradze — Talk to Me EP
)
_SCAN_TIMEOUT_S = 120.0
_SCAN_POLL_S = 1.0


def seed_tracks(
    items: tuple[tuple[str, int], ...] = SEED_ITEMS, *, client: SourceClient | None = None
) -> list[FreeTrack]:
    """First ``n`` MP3 tracks of each archive.org item; an unavailable item is skipped."""
    out: list[FreeTrack] = []
    for identifier, n in items:
        try:
            tracks = archive_org.item_tracks(identifier, client=client)
        except SourceError as exc:
            log.warning("seed.item_failed", item=identifier, error=str(exc))
            continue
        out += tracks[:n]
    return out


def download_all(
    conn: duckdb.DuckDBPyConnection,
    tracks: list[FreeTrack],
    *,
    library_dir: Path = downloads.LIBRARY_DIR,
    client: SourceClient | None = None,
) -> list[Path]:
    """Download each track (already-present files are not refetched); failures are logged."""
    paths: list[Path] = []
    for track in tracks:
        try:
            paths.append(downloads.download(conn, track, library_dir=library_dir, client=client))
        except SourceError as exc:
            log.warning("seed.download_failed", title=track.title, error=str(exc))
    return paths


async def ensure_admin(
    base_url: str, user: str, password: str, *, transport: httpx.AsyncBaseTransport | None = None
) -> bool:
    """Create the first admin on a fresh Navidrome. True if created, False if users exist."""
    async with httpx.AsyncClient(base_url=base_url, timeout=10.0, transport=transport) as http:
        try:
            response = await http.post(
                "/auth/createAdmin", json={"username": user, "password": password}
            )
        except httpx.HTTPError as exc:
            raise SourceError(f"navidrome: createAdmin failed: {exc}") from exc
    if response.status_code == 403:  # "Cannot create another first admin"
        return False
    if response.is_error:
        raise SourceError(f"navidrome: createAdmin HTTP {response.status_code}")
    return True


async def scan_and_wait(
    client: SubsonicClient, *, timeout_s: float = _SCAN_TIMEOUT_S, poll_s: float = _SCAN_POLL_S
) -> ScanStatus:
    """Trigger a scan and poll until Navidrome reports it finished (or the timeout passes)."""
    status = await client.start_scan()
    deadline = time.monotonic() + timeout_s
    while status.scanning and time.monotonic() < deadline:
        await asyncio.sleep(poll_s)
        status = await client.scan_status()
    if status.scanning:
        log.warning("seed.scan_still_running", timeout_s=timeout_s)
    return status


async def _index(client: SubsonicClient) -> tuple[ScanStatus, int]:
    created = await ensure_admin(
        client.base_url, settings.navidrome_user, settings.navidrome_password
    )
    log.info("seed.admin", user=settings.navidrome_user, created=created)
    status = await scan_and_wait(client)
    albums = await client.album_list("alphabeticalByName", size=500)
    return status, len(albums.albums)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Seed CC tracks into the library + scan.")
    parser.add_argument(
        "--no-record", action="store_true", help="don't record downloads in the project DuckDB"
    )
    args = parser.parse_args(argv)
    configure_logging(settings.log_level)

    if not (settings.navidrome_user and settings.navidrome_password):
        log.error("seed.no_credentials", hint="set NAVIDROME_USER / NAVIDROME_PASSWORD in .env")
        return 1

    conn = duckdb.connect() if args.no_record else get_connection()
    try:
        init_schema(conn)
        tracks = seed_tracks()
        paths = download_all(conn, tracks)
    finally:
        conn.close()
    log.info("seed.downloaded", n=len(paths), of=len(tracks), dir=str(downloads.LIBRARY_DIR))

    async def _run() -> tuple[ScanStatus, int]:
        client = SubsonicClient.from_settings(settings)
        try:
            return await _index(client)
        finally:
            await client.aclose()

    try:
        status, n_albums = asyncio.run(_run())
    except SourceError as exc:
        log.error("seed.navidrome_failed", error=str(exc), url=settings.navidrome_url)
        return 1
    log.info("seed.done", songs=status.count, albums=n_albums)
    return 0 if paths and n_albums else 1


if __name__ == "__main__":
    sys.exit(main())
