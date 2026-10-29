"""Unit tests for sources.lastfm and sources.listenbrainz."""

from sources import lastfm, listenbrainz


class TestLastfmSimilarTracks:
    def test_parses_tracks(self, json_client):
        client, seen = json_client(
            {
                "similartracks": {
                    "track": [
                        {"name": "Song", "match": "0.8", "mbid": "m1", "artist": {"name": "X"}},
                        {"name": "Other", "match": 0.3, "artist": {"name": "Y"}},
                    ]
                }
            }
        )
        items = lastfm.similar_tracks("A", "B", client=client)
        assert [(i.artist, i.title, i.match) for i in items] == [
            ("X", "Song", 0.8),
            ("Y", "Other", 0.3),
        ]
        assert items[1].mbid == ""
        assert seen[0].url.params["method"] == "track.getsimilar"

    def test_single_object_is_wrapped(self, json_client):
        client, _ = json_client(
            {"similartracks": {"track": {"name": "Solo", "match": 1, "artist": {"name": "Z"}}}}
        )
        assert [i.title for i in lastfm.similar_tracks("A", "B", client=client)] == ["Solo"]

    def test_error_body_returns_empty(self, json_client):
        client, _ = json_client({"error": 6, "message": "Track not found"})
        assert lastfm.similar_tracks("A", "B", client=client) == []


class TestLastfmSimilarArtists:
    def test_parses_artists(self, json_client):
        client, _ = json_client(
            {"similarartists": {"artist": [{"name": "X", "match": "0.9", "mbid": "a1"}]}}
        )
        [item] = lastfm.similar_artists("A", client=client)
        assert (item.artist, item.title, item.mbid, item.match) == ("X", "", "a1", 0.9)

    def test_no_key_returns_empty(self, monkeypatch):
        monkeypatch.setattr(lastfm, "default_client", lambda: None)
        assert lastfm.similar_artists("A") == []


class TestListenbrainzCf:
    def test_parses_mbids(self, json_client):
        client, seen = json_client({"payload": {"mbids": [{"recording_mbid": "r1", "score": 0.7}]}})
        [item] = listenbrainz.cf_recommendations("me", client=client)
        assert (item.mbid, item.match, item.source) == ("r1", 0.7, "listenbrainz")
        assert seen[0].url.path.endswith("/cf/recommendation/user/me/recording")

    def test_no_recs_yet(self, json_client):
        client, _ = json_client({})
        assert listenbrainz.cf_recommendations("me", client=client) == []

    def test_no_user_returns_empty(self, json_client, monkeypatch):
        monkeypatch.setattr(listenbrainz.settings, "listenbrainz_user", "")
        client, seen = json_client({})
        assert listenbrainz.cf_recommendations(client=client) == []
        assert seen == []


class TestLbRadio:
    def test_parses_jspf(self, json_client):
        rec = "https://musicbrainz.org/recording/"
        client, seen = json_client(
            {
                "payload": {
                    "jspf": {
                        "playlist": {
                            "track": [
                                {"title": "T1", "creator": "X", "identifier": [rec + "r1"]},
                                {"title": "T2", "creator": "Y", "identifier": rec + "r2"},
                            ]
                        }
                    }
                }
            }
        )
        items = listenbrainz.lb_radio("artist:(X)", client=client)
        assert [(i.artist, i.title, i.mbid, i.match) for i in items] == [
            ("X", "T1", "r1", 1.0),
            ("Y", "T2", "r2", 0.5),
        ]
        assert seen[0].url.params["prompt"] == "artist:(X)"

    def test_no_token_returns_empty(self, monkeypatch):
        monkeypatch.setattr(listenbrainz, "default_client", lambda: None)
        assert listenbrainz.lb_radio("tag:(jazz)") == []
