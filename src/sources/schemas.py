"""
Pydantic v2 schemas for free music-data sources.
MusicBrainz recording MBID is the canonical track ID; other IDs are cross-refs.
"""

from pydantic import BaseModel


class Recording(BaseModel):
    mbid: str
    title: str
    artist: str
    artist_mbids: list[str] = []
    isrcs: list[str] = []
    length_ms: int | None = None
    score: int = 0  # MusicBrainz search score, 0–100


class ArtistRelation(BaseModel):
    type: str  # e.g. "member of band", "influenced by"
    direction: str  # "forward" | "backward"
    artist: str
    mbid: str


class ArtistInfo(BaseModel):
    mbid: str
    name: str
    type: str | None = None
    country: str | None = None
    begin: str | None = None
    end: str | None = None
    genres: list[str] = []
    tags: list[str] = []
    relations: list[ArtistRelation] = []


class TrackRef(BaseModel):
    """Source-agnostic track identity: what playlists store and playback resolves."""

    artist: str
    title: str
    mbid: str = ""


class SimilarItem(BaseModel):
    """One candidate from a similarity/recommendation source. Empty title = artist-level."""

    source: str  # "lastfm" | "listenbrainz" | "deezer"
    artist: str = ""
    title: str = ""
    mbid: str = ""
    match: float = 0.0


class PlayableTrack(BaseModel):
    artist: str
    title: str
    youtube_url: str  # watch URL if a video was found, else a search URL
    youtube_embed_url: str = ""
    deezer_id: int | None = None
    deezer_url: str = ""
    preview_url: str = ""  # 30s mp3; signed URL, expires
    isrc: str = ""
