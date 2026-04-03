"""
Pydantic v2 schemas for Spotify API data structures.
Replaces Marshmallow schemas in api/data/playlist_schema.py.
"""

from pydantic import BaseModel, Field, field_validator


class ArtistFeatures(BaseModel):
    id: str
    popularity: int = 0
    genres: list[str] = []


class AudioFeatures(BaseModel):
    id: str
    danceability: float = 0.0
    energy: float = 0.0
    loudness: float = 0.0
    speechiness: float = 0.0
    acousticness: float = 0.0
    instrumentalness: float = 0.0
    liveness: float = 0.0
    valence: float = 0.0
    tempo: float = 0.0
    key: int = 0
    mode: int = 0
    duration_ms: int = 0
    time_signature: int = 4


class TrackFeatures(BaseModel):
    id: str
    uri: str
    name: str
    release_date: str
    artist_ids: list[str]
    artist_names: list[str]
    playlist_id: str = ""
    playlist_name: str = ""


class PlaylistTrack(BaseModel):
    """Fully enriched track — track + audio + artist features merged."""

    id: str
    uri: str
    track_name: str
    release_date: str
    artist_ids: list[str]
    artist_names: list[str]
    playlist_id: str
    playlist_name: str

    # Audio features
    danceability: float = 0.0
    energy: float = 0.0
    loudness: float = 0.0
    speechiness: float = 0.0
    acousticness: float = 0.0
    instrumentalness: float = 0.0
    liveness: float = 0.0
    valence: float = 0.0
    tempo: float = 0.0
    key: int = 0
    mode: int = 0
    duration_ms: int = 0

    # Artist / genre features
    popularity: float = 0.0
    genres: str = ""
    first_genre: str = ""
    genre_cat: str = ""

    # Derived categorical features
    year: int = 0
    decade: str = ""
    key_mode: str = ""


class ListeningHistoryEntry(BaseModel):
    """One entry from a Spotify extended streaming history JSON export."""

    ts: str
    ms_played: int = 0
    track_name: str = Field("", alias="master_metadata_track_name")
    artist_name: str = Field("", alias="master_metadata_album_artist_name")
    album_name: str = Field("", alias="master_metadata_album_album_name")
    spotify_track_uri: str = ""
    reason_start: str = ""
    reason_end: str = ""
    skipped: bool = False

    @field_validator("track_name", "artist_name", "album_name", mode="before")
    @classmethod
    def coerce_none(cls, v: object) -> str:
        return v if v is not None else ""

    model_config = {"populate_by_name": True}
