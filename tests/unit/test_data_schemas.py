"""Tests for data/schemas.py — Pydantic v2 models."""

from utils.schemas import (
    ArtistFeatures,
    AudioFeatures,
    ListeningHistoryEntry,
    TrackFeatures,
)


class TestArtistFeatures:
    def test_basic(self):
        a = ArtistFeatures(id="a1", popularity=72, genres=["rock", "indie"])
        assert a.id == "a1"
        assert a.popularity == 72
        assert a.genres == ["rock", "indie"]

    def test_defaults(self):
        a = ArtistFeatures(id="a1")
        assert a.popularity == 0
        assert a.genres == []


class TestAudioFeatures:
    def test_all_fields(self):
        af = AudioFeatures(
            id="t1",
            danceability=0.8,
            energy=0.6,
            loudness=-5.0,
            tempo=120.0,
            key=7,
            mode=1,
        )
        assert af.danceability == 0.8
        assert af.key == 7

    def test_defaults(self):
        af = AudioFeatures(id="t1")
        assert af.valence == 0.0
        assert af.time_signature == 4


class TestTrackFeatures:
    def test_basic(self):
        t = TrackFeatures(
            id="t1",
            uri="spotify:track:t1",
            name="Song A",
            release_date="1973-04-01",
            artist_ids=["a1"],
            artist_names=["Artist X"],
        )
        assert t.name == "Song A"
        assert t.playlist_id == ""


class TestListeningHistoryEntry:
    def test_alias_mapping(self):
        """Field aliases should map Spotify export keys correctly."""
        entry = ListeningHistoryEntry(
            **{
                "ts": "2023-01-01T10:00:00Z",
                "ms_played": 240000,
                "master_metadata_track_name": "Song A",
                "master_metadata_album_artist_name": "Artist X",
                "master_metadata_album_album_name": "Album 1",
                "spotify_track_uri": "spotify:track:abc123",
                "reason_start": "clickrow",
                "reason_end": "trackdone",
                "skipped": False,
            }
        )
        assert entry.track_name == "Song A"
        assert entry.artist_name == "Artist X"
        assert entry.skipped is False

    def test_none_coercion(self):
        """Spotify exports use null for episode/podcast fields — should become empty string."""
        entry = ListeningHistoryEntry(
            **{
                "ts": "2023-01-01T10:00:00Z",
                "ms_played": 0,
                "master_metadata_track_name": None,
                "master_metadata_album_artist_name": None,
                "master_metadata_album_album_name": None,
            }
        )
        assert entry.track_name == ""
        assert entry.artist_name == ""

    def test_missing_optional_fields(self):
        entry = ListeningHistoryEntry(ts="2023-01-01T10:00:00Z")
        assert entry.ms_played == 0
        assert entry.skipped is False
