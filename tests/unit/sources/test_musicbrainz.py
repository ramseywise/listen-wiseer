"""Unit tests for sources.musicbrainz."""

from sources import musicbrainz as mb

_RECORDING = {
    "id": "rec-1",
    "title": "Weird Fishes",
    "score": 100,
    "length": 318000,
    "isrcs": ["GBSTK0700004"],
    "artist-credit": [
        {"name": "Band A", "joinphrase": " & ", "artist": {"id": "art-a", "name": "Band A"}},
        {"name": "Band B", "joinphrase": "", "artist": {"id": "art-b", "name": "Band B"}},
    ],
}


class TestSearchRecording:
    def test_parses_recording_and_joins_credits(self, json_client):
        client, seen = json_client({"recordings": [_RECORDING]})
        [rec] = mb.search_recording("Band A", "Weird Fishes", client=client)
        assert rec.mbid == "rec-1"
        assert rec.artist == "Band A & Band B"
        assert rec.artist_mbids == ["art-a", "art-b"]
        assert rec.isrcs == ["GBSTK0700004"]
        assert rec.score == 100
        assert seen[0].url.params["query"] == 'recording:"Weird Fishes" AND artist:"Band A"'

    def test_quotes_are_escaped(self, json_client):
        client, seen = json_client({"recordings": []})
        mb.search_recording('The "Band"', "Song", client=client)
        assert 'artist:"The \\"Band\\""' in seen[0].url.params["query"]


class TestBestMatch:
    def test_returns_hit_above_threshold(self, json_client):
        client, _ = json_client({"recordings": [_RECORDING]})
        assert mb.best_match("Band A", "Weird Fishes", client=client).mbid == "rec-1"

    def test_rejects_low_score(self, json_client):
        client, _ = json_client({"recordings": [{**_RECORDING, "score": 60}]})
        assert mb.best_match("Band A", "Weird Fishes", client=client) is None

    def test_no_hits(self, json_client):
        client, _ = json_client({"recordings": []})
        assert mb.best_match("x", "y", client=client) is None


class TestLookupSpotifyTrack:
    def test_finds_linked_recording(self, json_client):
        client, seen = json_client(
            {"relations": [{"target-type": "recording", "recording": {"id": "rec-9"}}]}
        )
        assert mb.lookup_spotify_track("abc", client=client) == "rec-9"
        assert seen[0].url.params["resource"] == "https://open.spotify.com/track/abc"

    def test_unlinked_returns_none(self, json_client):
        client, _ = json_client({})
        assert mb.lookup_spotify_track("abc", client=client) is None


class TestSearchArtist:
    def test_returns_mbid_above_threshold(self, json_client):
        client, _ = json_client({"artists": [{"id": "art-a", "score": 100}]})
        assert mb.search_artist("Band A", client=client) == "art-a"

    def test_rejects_low_score(self, json_client):
        client, _ = json_client({"artists": [{"id": "art-a", "score": 40}]})
        assert mb.search_artist("Band A", client=client) is None


class TestGetArtist:
    def test_parses_and_dedupes_relations(self, json_client):
        member = {"id": "m1", "name": "Member One"}
        client, _ = json_client(
            {
                "id": "art-a",
                "name": "Band A",
                "type": "Group",
                "country": "GB",
                "life-span": {"begin": "1991", "end": None},
                "genres": [{"name": "art rock", "count": 3}, {"name": "britpop", "count": 9}],
                "tags": [{"name": "alternative", "count": 1}],
                "relations": [
                    {"type": "member of band", "direction": "backward", "artist": member},
                    {"type": "member of band", "direction": "backward", "artist": member},
                    {"type": "url thing", "direction": "forward"},  # no artist → skipped
                ],
            }
        )
        info = mb.get_artist("art-a", client=client)
        assert info is not None
        assert info.genres == ["britpop", "art rock"]
        assert info.begin == "1991"
        assert len(info.relations) == 1
        assert info.relations[0].artist == "Member One"

    def test_missing_artist_returns_none(self, json_client):
        client, _ = json_client({})
        assert mb.get_artist("nope", client=client) is None
