"""Unit tests for etl.resolve — plays → track_xref ID resolution."""

from datetime import datetime

import httpx
import pytest

from etl.history import track_key
from etl.resolve import pending_tracks, resolve_pending, resolve_track
from sources.http import SourceClient


def _client(handler) -> SourceClient:
    return SourceClient("test", "https://api.test/", transport=httpx.MockTransport(handler))


def _mb_handler(recordings: dict[str, dict], url_links: dict[str, str] | None = None):
    """Fake MusicBrainz: recording search keyed by title substring; URL lookups by spotify id."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/recording"):
            query = request.url.params["query"]
            hits = [r for title, r in recordings.items() if f'"{title}"' in query]
            return httpx.Response(200, json={"recordings": hits})
        if request.url.path.endswith("/url"):
            sid = request.url.params["resource"].rsplit("/", 1)[-1]
            mbid = (url_links or {}).get(sid)
            if mbid is None:
                return httpx.Response(404)
            rels = [{"target-type": "recording", "recording": {"id": mbid}}]
            return httpx.Response(200, json={"relations": rels})
        return httpx.Response(500)

    return handler


def _deezer_handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(
        200, json={"data": [{"id": 42, "isrc": "GB0001", "artist": {"name": "Artist X"}}]}
    )


def _rec(mbid: str, score: int = 100) -> dict:
    return {
        "id": mbid,
        "title": "t",
        "score": score,
        "artist-credit": [{"name": "Artist X", "artist": {"id": "art-x", "name": "Artist X"}}],
    }


def _add_play(conn, artist, title, spotify_id=None, ms=200_000, ts="2023-01-01 10:00:00"):
    conn.execute(
        "INSERT INTO plays (ts, track_key, spotify_id, track_name, artist_name, ms_played)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        [datetime.fromisoformat(ts), track_key(artist, title), spotify_id, title, artist, ms],
    )


@pytest.fixture
def played(mem_conn):
    for minute in range(3):
        _add_play(mem_conn, "Artist X", "Hit", "sp-hit", ts=f"2023-01-01 10:0{minute}:00")
    _add_play(mem_conn, "Artist X", "Deep Cut", "sp-deep", ts="2023-01-02 10:00:00")
    _add_play(mem_conn, "Artist X", "Deep Cut", "sp-deep", ts="2023-01-02 11:00:00")
    _add_play(mem_conn, "Artist X", "Once", ts="2023-01-03 10:00:00")
    _add_play(mem_conn, "Artist X", "Skipped", ms=3_000, ts="2023-01-04 10:00:00")
    _add_play(mem_conn, "Artist X", "Skipped", ms=3_000, ts="2023-01-04 11:00:00")
    return mem_conn


class TestPendingTracks:
    def test_filters_and_orders_by_plays(self, played):
        todo = pending_tracks(played)
        assert todo["track_name"].to_list() == ["Hit", "Deep Cut"]
        assert todo["n_plays"].to_list() == [3, 2]

    def test_min_plays_and_limit(self, played):
        assert len(pending_tracks(played, min_plays=1)) == 3
        assert len(pending_tracks(played, min_plays=1, limit=1)) == 1


class TestResolveTrack:
    def test_search_hit(self):
        ids = resolve_track(
            "Artist X",
            "Hit",
            mb_client=_client(_mb_handler({"Hit": _rec("rec-hit")})),
            deezer_client=_client(_deezer_handler),
        )
        assert ids["mbid"] == "rec-hit"
        assert ids["mb_method"] == "search"
        assert ids["artist_mbids"] == ["art-x"]
        assert (ids["deezer_id"], ids["isrc"]) == (42, "GB0001")

    def test_falls_back_to_spotify_url(self):
        ids = resolve_track(
            "Artist X",
            "Hit",
            "sp-hit",
            mb_client=_client(_mb_handler({"Hit": _rec("weak", score=50)}, {"sp-hit": "rec-url"})),
            deezer_client=_client(_deezer_handler),
        )
        assert (ids["mbid"], ids["mb_method"], ids["mb_score"]) == ("rec-url", "spotify_url", None)

    def test_unmatched(self):
        ids = resolve_track(
            "Artist X",
            "Nope",
            mb_client=_client(_mb_handler({})),
            deezer_client=_client(lambda _r: httpx.Response(200, json={"data": []})),
        )
        assert ids["mbid"] is None and ids["mb_method"] is None and ids["deezer_id"] is None


class TestResolvePending:
    def test_writes_rows_and_is_resumable(self, played):
        mb_client = _client(_mb_handler({"Hit": _rec("rec-hit")}))
        dz = _client(_deezer_handler)
        assert resolve_pending(played, mb_client=mb_client, deezer_client=dz) == (2, 1)

        rows = dict(played.execute("SELECT track_name, mbid FROM track_xref").fetchall())
        assert rows == {"Hit": "rec-hit", "Deep Cut": None}
        # Second run: nothing pending (unmatched are not retried by default)
        assert resolve_pending(played, mb_client=mb_client, deezer_client=dz) == (0, 0)

    def test_retry_unmatched(self, played):
        dz = _client(_deezer_handler)
        resolve_pending(played, mb_client=_client(_mb_handler({})), deezer_client=dz)
        fixed = _client(_mb_handler({"Deep Cut": _rec("rec-deep")}))
        written, matched = resolve_pending(
            played, mb_client=fixed, deezer_client=dz, retry_unmatched=True
        )
        assert (written, matched) == (2, 1)
        mbid = played.execute(
            "SELECT mbid FROM track_xref WHERE track_name = 'Deep Cut'"
        ).fetchone()[0]
        assert mbid == "rec-deep"

    def test_source_error_leaves_no_row(self, played):
        broken = _client(lambda _r: httpx.Response(500))
        assert resolve_pending(played, mb_client=broken, deezer_client=broken) == (0, 0)
        assert played.execute("SELECT count(*) FROM track_xref").fetchone()[0] == 0
