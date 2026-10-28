"""Unit tests for recommend.discover — open-world multi-source discovery ranking."""

from datetime import datetime

import httpx
import pytest

from etl.history import track_key
from recommend.discover import History, discover, gather, load_history, rank
from sources.http import SourceClient
from sources.schemas import SimilarItem


def _t(source: str, artist: str, title: str, match: float = 0.5, mbid: str = "") -> SimilarItem:
    return SimilarItem(source=source, artist=artist, title=title, match=match, mbid=mbid)


def _a(source: str, artist: str, match: float = 1.0) -> SimilarItem:
    return SimilarItem(source=source, artist=artist, match=match)


def _titles(cands) -> list[str]:
    return [c.title for c in cands]


class TestRank:
    def test_source_agreement_beats_single_source(self):
        items = [
            _t("lastfm", "A", "Both", 0.5),
            _t("listenbrainz", "A", "Both", 0.5),
            _t("lastfm", "B", "Solo", 1.0),
        ]
        out = rank(items)
        assert _titles(out) == ["Both", "Solo"]
        assert out[0].sources == ["lastfm", "listenbrainz"]

    def test_dedupes_case_and_whitespace(self):
        items = [_t("lastfm", "Artist", "Song"), _t("listenbrainz", " artist ", "SONG", mbid="m1")]
        out = rank(items)
        assert len(out) == 1
        assert out[0].mbid == "m1"

    def test_artist_level_support_boosts(self):
        items = [_t("lastfm", "A", "x", 0.5), _t("lastfm", "B", "y", 0.5), _a("deezer", "B")]
        assert _titles(rank(items)) == ["y", "x"]

    def test_heavy_rotation_penalised(self):
        items = [_t("lastfm", "A", "Worn", 0.6), _t("lastfm", "B", "Fresh", 0.5)]
        history = History(play_counts={track_key("A", "Worn"): 50})
        out = rank(items, history)
        assert _titles(out) == ["Fresh", "Worn"]
        assert out[1].n_plays == 50

    def test_seed_track_excluded_and_seed_artist_known(self):
        items = [_t("lastfm", "Seed", "Same"), _t("lastfm", "Seed", "Other")]
        out = rank(items, seed_artist="Seed", seed_title="Same")
        assert _titles(out) == ["Other"]
        assert out[0].known_artist is True

    def test_mbid_only_items_skipped(self):
        items = [SimilarItem(source="listenbrainz", mbid="m1", match=1.0), _t("lastfm", "A", "x")]
        assert _titles(rank(items)) == ["x"]

    def test_per_artist_cap(self):
        items = [_t("lastfm", "A", f"t{i}", 1.0 - i / 10) for i in range(5)]
        assert _titles(rank(items)) == ["t0", "t1"]

    def test_known_new_mix(self):
        known = [_t("lastfm", f"K{i}", "k", 0.9) for i in range(4)]
        new = [_t("lastfm", f"N{i}", "n", 0.1) for i in range(4)]
        history = History(known_artists={f"k{i}" for i in range(4)})
        out = rank(known + new, history, n=4, new_artist_ratio=0.5)
        assert sum(c.known_artist for c in out) == 2
        # Sorted by score: known (0.9) before new (0.1)
        assert [c.known_artist for c in out] == [True, True, False, False]

    def test_mix_backfills_when_one_side_short(self):
        items = [_t("lastfm", f"N{i}", "n") for i in range(5)]
        assert len(rank(items, n=4, new_artist_ratio=0.25)) == 4


def _client(handler) -> SourceClient:
    return SourceClient("test", "https://api.test/", transport=httpx.MockTransport(handler))


def _lb_handler(request: httpx.Request) -> httpx.Response:
    tracks = [
        {
            "title": "Shared",
            "creator": "Peer",
            "identifier": "https://musicbrainz.org/recording/m1",
        },
        {"title": "Radio Only", "creator": "Other", "identifier": []},
    ]
    return httpx.Response(200, json={"payload": {"jspf": {"playlist": {"track": tracks}}}})


def _lastfm_handler(request: httpx.Request) -> httpx.Response:
    method = request.url.params["method"]
    if method == "track.getsimilar":
        sim = [{"name": "Shared", "artist": {"name": "Peer"}, "match": "0.8", "mbid": ""}]
        return httpx.Response(200, json={"similartracks": {"track": sim}})
    return httpx.Response(
        200, json={"similarartists": {"artist": [{"name": "Peer", "match": "1"}]}}
    )


class TestGatherAndDiscover:
    def test_gather_fails_soft(self):
        broken = _client(lambda _r: httpx.Response(500))
        items = gather("Seed", "Song", lb_client=_client(_lb_handler), lastfm_client=broken,
                       deezer_client=broken)  # fmt: skip
        assert {i.title for i in items} == {"Shared", "Radio Only"}

    def test_track_seed_adds_similar_tracks(self):
        dz = _client(lambda _r: httpx.Response(200, json={"data": []}))
        lfm = _client(_lastfm_handler)
        without = gather("Seed", lastfm_client=lfm, lb_client=None, deezer_client=dz)
        with_title = gather("Seed", "Song", lastfm_client=lfm, deezer_client=dz)
        assert not any(i.source == "lastfm" and i.title for i in without)
        assert any(i.source == "lastfm" and i.title == "Shared" for i in with_title)

    def test_discover_end_to_end(self, mem_conn):
        mem_conn.execute(
            "INSERT INTO plays (ts, track_key, track_name, artist_name, ms_played)"
            " VALUES (?, ?, ?, ?, ?)",
            [datetime(2024, 1, 1), track_key("Other", "Old Fave"), "Old Fave", "Other", 200_000],
        )
        out = discover(
            "Seed",
            "Song",
            conn=mem_conn,
            lastfm_client=_client(_lastfm_handler),
            lb_client=_client(_lb_handler),
            deezer_client=_client(lambda _r: httpx.Response(200, json={"data": []})),
        )
        top = out[0]
        assert (top.title, top.mbid, top.sources) == ("Shared", "m1", ["lastfm", "listenbrainz"])
        radio_only = next(c for c in out if c.title == "Radio Only")
        assert radio_only.known_artist is True  # "Other" is in plays


class TestLoadHistory:
    @pytest.mark.parametrize(("ms", "expected"), [(200_000, 1), (5_000, 0)])
    def test_counts_only_real_plays(self, mem_conn, ms, expected):
        mem_conn.execute(
            "INSERT INTO plays (ts, track_key, track_name, artist_name, ms_played)"
            " VALUES (?, ?, ?, ?, ?)",
            [datetime(2024, 1, 1), track_key("A", "x"), "x", "A", ms],
        )
        h = load_history(mem_conn)
        assert h.play_counts.get(track_key("A", "x"), 0) == expected
        assert ("a" in h.known_artists) is bool(expected)
