"""
MusicBrainz WS/2 client — canonical IDs, genres, and artist relationships.
No auth; requires a descriptive User-Agent; hard limit 1 req/s per IP.

API docs: https://musicbrainz.org/doc/MusicBrainz_API
"""

from functools import cache

from sources.http import SourceClient
from sources.schemas import ArtistInfo, ArtistRelation, Recording

_BASE_URL = "https://musicbrainz.org/ws/2/"
_MIN_INTERVAL = 1.1


@cache
def default_client() -> SourceClient:
    return SourceClient(
        "musicbrainz", _BASE_URL, min_interval=_MIN_INTERVAL, params={"fmt": "json"}
    )


def _quote(value: str) -> str:
    """Quote a value for a Lucene phrase query."""
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _by_count(items: list[dict]) -> list[str]:
    return [i["name"] for i in sorted(items, key=lambda i: i.get("count", 0), reverse=True)]


def _parse_recording(r: dict) -> Recording:
    credits = r.get("artist-credit", [])
    return Recording(
        mbid=r["id"],
        title=r.get("title", ""),
        artist="".join(c.get("name", "") + c.get("joinphrase", "") for c in credits),
        artist_mbids=[c["artist"]["id"] for c in credits if "artist" in c],
        isrcs=r.get("isrcs", []),
        length_ms=r.get("length"),
        score=int(r.get("score", 0)),
    )


def search_recording(
    artist: str, title: str, *, limit: int = 5, client: SourceClient | None = None
) -> list[Recording]:
    """Search recordings by artist + title. Results ordered by MusicBrainz score."""
    c = client or default_client()
    query = f"recording:{_quote(title)} AND artist:{_quote(artist)}"
    data = c.get_json("recording", query=query, limit=limit)
    return [_parse_recording(r) for r in data.get("recordings", [])]


def best_match(
    artist: str, title: str, *, min_score: int = 90, client: SourceClient | None = None
) -> Recording | None:
    """Top search hit if its score clears ``min_score``, else None."""
    hits = search_recording(artist, title, limit=1, client=client)
    return hits[0] if hits and hits[0].score >= min_score else None


def lookup_spotify_track(spotify_id: str, *, client: SourceClient | None = None) -> str | None:
    """Recording MBID linked to a Spotify track URL, if anyone has linked it (low coverage)."""
    c = client or default_client()
    data = c.get_json(
        "url", resource=f"https://open.spotify.com/track/{spotify_id}", inc="recording-rels"
    )
    for rel in data.get("relations", []):
        if rel.get("target-type") == "recording":
            return rel["recording"]["id"]
    return None


def search_artist(
    name: str, *, min_score: int = 90, client: SourceClient | None = None
) -> str | None:
    """Artist MBID for a name if the top hit's score clears ``min_score``."""
    c = client or default_client()
    data = c.get_json("artist", query=f"artist:{_quote(name)}", limit=1)
    hits = data.get("artists", [])
    return hits[0]["id"] if hits and int(hits[0].get("score", 0)) >= min_score else None


def get_artist(mbid: str, *, client: SourceClient | None = None) -> ArtistInfo | None:
    """Artist metadata with genres/tags (by vote count) and de-duplicated artist relations."""
    c = client or default_client()
    data = c.get_json(f"artist/{mbid}", inc="genres+tags+artist-rels")
    if not data:
        return None

    seen: set[tuple[str, str, str]] = set()
    relations: list[ArtistRelation] = []
    for rel in data.get("relations", []):
        other = rel.get("artist")
        if not other:
            continue
        key = (rel.get("type", ""), other["id"], rel.get("direction", ""))
        if key in seen:
            continue
        seen.add(key)
        relations.append(
            ArtistRelation(type=key[0], direction=key[2], artist=other["name"], mbid=other["id"])
        )

    life_span = data.get("life-span", {})
    return ArtistInfo(
        mbid=data["id"],
        name=data["name"],
        type=data.get("type"),
        country=data.get("country"),
        begin=life_span.get("begin"),
        end=life_span.get("end"),
        genres=_by_count(data.get("genres", [])),
        tags=_by_count(data.get("tags", [])),
        relations=relations,
    )
