"""
Internet Archive client — Live Music Archive, netlabels, public-domain audio. No key.
Items are albums / shows; tracks are an item's MP3 files (each carries its own title).

APIs: advancedsearch.php (items), metadata/{identifier} (files).
"""

from functools import cache
from urllib.parse import quote

from sources.http import SourceClient
from sources.schemas import FreeTrack

_BASE_URL = "https://archive.org/"
_MIN_INTERVAL = 1.0
_MP3_FORMATS = ("VBR MP3", "MP3")  # preferred derivative first; one per item
_MAX_ITEMS = 3  # each item costs a metadata request


@cache
def default_client() -> SourceClient:
    return SourceClient("archive_org", _BASE_URL, min_interval=_MIN_INTERVAL, timeout=20.0)


def _phrase(text: str) -> str:
    return '"' + text.replace('"', "") + '"'


def search_items(
    artist: str, title: str = "", *, limit: int = _MAX_ITEMS, client: SourceClient | None = None
) -> list[str]:
    """Identifiers of audio items by ``artist`` (mentioning ``title``), most downloaded first."""
    c = client or default_client()
    q = f"creator:({_phrase(artist)}) AND mediatype:audio"
    if title:
        q += f" AND {_phrase(title)}"
    data = c.get_json(
        "advancedsearch.php",
        q=q,
        **{"fl[]": "identifier", "sort[]": "downloads desc"},
        rows=limit,
        output="json",
    )
    return [d["identifier"] for d in data.get("response", {}).get("docs", [])]


def _creator(meta: dict) -> str:
    creator = meta.get("creator", "")
    return creator[0] if isinstance(creator, list) else creator


def item_tracks(identifier: str, *, client: SourceClient | None = None) -> list[FreeTrack]:
    """Downloadable MP3 tracks of one item; [] for missing or access-restricted items."""
    c = client or default_client()
    data = c.get_json(f"metadata/{identifier}")
    meta = data.get("metadata", {})
    if not meta or meta.get("access-restricted-item") == "true":
        return []
    files = data.get("files", [])
    fmt = next((f for f in _MP3_FORMATS if any(x.get("format") == f for x in files)), None)
    if fmt is None:
        return []
    return [
        FreeTrack(
            source="archive_org",
            source_id=f"{identifier}/{f['name']}",
            artist=f.get("creator") or _creator(meta),
            title=f.get("title") or f["name"].rsplit(".", 1)[0],
            download_url=f"{_BASE_URL}download/{identifier}/{quote(f['name'])}",
            page_url=f"{_BASE_URL}details/{identifier}",
            license_url=meta.get("licenseurl", ""),
        )
        for f in files
        if f.get("format") == fmt
    ]


def _loose_match(want: str, found: str) -> bool:
    want, found = want.casefold(), found.casefold()
    return bool(found) and (want in found or found in want)


def find_tracks(
    artist: str, title: str = "", *, limit: int = 10, client: SourceClient | None = None
) -> list[FreeTrack]:
    """Tracks by ``artist`` (matching ``title`` when given) from the top few items.

    Per-file creators can differ from the item's (tribute sets, compilations), so
    both artist and title are checked per track.
    """
    c = client or default_client()
    out: list[FreeTrack] = []
    for identifier in search_items(artist, title, client=c):
        out += [
            t
            for t in item_tracks(identifier, client=c)
            if _loose_match(artist, t.artist) and (not title or _loose_match(title, t.title))
        ]
        if len(out) >= limit:
            break
    return out[:limit]
