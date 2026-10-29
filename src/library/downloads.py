"""
Legal downloads into the local library (data/library/<artist>/<title>.mp3), which
Navidrome serves to phone apps. Sources: Jamendo (CC) then Internet Archive.
Never YouTube or Deezer — their terms forbid downloading.
"""

import re
from collections.abc import Callable
from datetime import datetime
from functools import cache
from pathlib import Path

import duckdb
from mutagen import MutagenError
from mutagen.id3 import ID3, TIT2, TPE1, UFID, WCOP, ID3NoHeaderError

from etl.history import track_key
from paths import DATA_DIR
from sources import archive_org, jamendo
from sources.http import SourceClient
from sources.schemas import FreeTrack
from utils.exceptions import SourceError
from utils.logging import get_logger

log = get_logger(__name__)

LIBRARY_DIR = DATA_DIR / "library"
_MB_UFID_OWNER = "http://musicbrainz.org"  # Picard's recording-MBID frame

_Finder = Callable[..., list[FreeTrack]]
_FINDERS: tuple[tuple[str, _Finder], ...] = (
    ("jamendo", jamendo.find_tracks),
    ("archive_org", archive_org.find_tracks),
)


@cache
def default_downloader() -> SourceClient:
    return SourceClient("download", "", timeout=60.0)


def find_free(artist: str, title: str = "", *, limit: int = 10) -> list[FreeTrack]:
    """Legally downloadable matches across sources; a failing source is skipped."""
    out: list[FreeTrack] = []
    for name, find in _FINDERS:
        try:
            out += find(artist, title, limit=limit)
        except SourceError as exc:
            log.warning("library.find_free_failed", source=name, error=str(exc))
    return out[:limit]


def _safe(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", name).strip(" .") or "unknown"


def local_path(conn: duckdb.DuckDBPyConnection, artist: str, title: str) -> str | None:
    """Path of a downloaded copy that still exists on disk, else None."""
    row = conn.execute(
        "SELECT path FROM library WHERE track_key = ?", [track_key(artist, title)]
    ).fetchone()
    return row[0] if row and Path(row[0]).is_file() else None


def tag(path: Path, track: FreeTrack, mbid: str = "") -> None:
    """Write the ID3 frames Navidrome / Picard read: recording MBID (UFID), licence (WCOP),
    and artist / title when the file has none. Best effort — a bad file is only logged."""
    try:
        try:
            tags = ID3(path)
        except ID3NoHeaderError:
            tags = ID3()
        if "TPE1" not in tags:
            tags.add(TPE1(encoding=3, text=track.artist))
        if "TIT2" not in tags:
            tags.add(TIT2(encoding=3, text=track.title))
        if mbid:
            tags.add(UFID(owner=_MB_UFID_OWNER, data=mbid.encode()))
        if track.license_url:
            tags.add(WCOP(url=track.license_url))
        tags.save(path)
    except MutagenError as exc:
        log.warning("library.tag_failed", path=str(path), error=str(exc))


def download(
    conn: duckdb.DuckDBPyConnection,
    track: FreeTrack,
    *,
    mbid: str = "",
    requested: tuple[str, str] | None = None,
    library_dir: Path = LIBRARY_DIR,
    client: SourceClient | None = None,
) -> Path:
    """Download ``track`` into the library, tag it and record it; raises SourceError on failure.

    ``requested`` (artist, title) is what the user asked for — also recorded, so playback
    finds the file under either name ("Weird Fishes" vs "Weird Fishes / Arpeggi").
    """
    dest = library_dir / _safe(track.artist) / f"{_safe(track.title)}.mp3"
    if not dest.is_file():
        (client or default_downloader()).download(track.download_url, dest)
        tag(dest, track, mbid)
    keys = {track_key(track.artist, track.title)}
    if requested:
        keys.add(track_key(*requested))
    for key in keys:
        conn.execute(
            "INSERT OR REPLACE INTO library VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                key,
                track.artist,
                track.title,
                mbid,
                track.source,
                track.source_id,
                track.license_url,
                str(dest),
                datetime.now(),
            ],
        )
    log.info("library.downloaded", source=track.source, artist=track.artist, path=str(dest))
    return dest
