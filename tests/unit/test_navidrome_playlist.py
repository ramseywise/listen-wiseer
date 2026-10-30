"""Unit tests for library.navidrome_playlist — match → createPlaylist, report, config guard."""

from unittest.mock import patch

import httpx
import pytest

import library.navidrome_playlist as nd_playlist
from library.navidrome_playlist import (
    NavidromeNotConfigured,
    SavedPlaylist,
    describe,
    list_navidrome_playlists_sync,
    navidrome_configured,
    save_to_navidrome,
)
from sources.schemas import TrackRef
from sources.subsonic import SubsonicClient, SubsonicUnavailable
from utils.config import Settings

LIBRARY = [
    {"id": "s1", "title": "April Showers", "artist": "ProleteR"},
    {"id": "s2", "title": "Talk to me", "artist": "Miranda Shvangiradze"},
]


class FakeNavidrome:
    def __init__(self) -> None:
        self.created: list[tuple[str, list[str]]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        endpoint = request.url.path.removeprefix("/rest/")
        q = request.url.params
        body: dict = {}
        if endpoint == "search3":
            words = q["query"].lower().split()
            hits = [
                s for s in LIBRARY if all(w in f"{s['title']} {s['artist']}".lower() for w in words)
            ]
            body = {"searchResult3": {"song": hits}}
        elif endpoint == "createPlaylist":
            self.created.append((q["name"], q.get_list("songId")))
            body = {"playlist": {"id": "pl9", "name": q["name"], "entry": []}}
        elif endpoint == "getPlaylists":
            body = {"playlists": {"playlist": [{"id": "pl9", "name": "Mix", "songCount": 2}]}}
        return httpx.Response(200, json={"subsonic-response": {"status": "ok", **body}})


@pytest.fixture
def fake() -> FakeNavidrome:
    return FakeNavidrome()


def _client(handler) -> SubsonicClient:
    return SubsonicClient("http://nd.test", "me", "pw", transport=httpx.MockTransport(handler))


async def test_creates_playlist_from_matches_in_order_without_repeats(fake: FakeNavidrome) -> None:
    tracks = [
        TrackRef(artist="Miranda Shvangiradze", title="Talk to me"),
        TrackRef(artist="Radiohead", title="Reckoner"),
        TrackRef(artist="ProleteR", title="April Showers"),
        TrackRef(artist="ProleteR", title="April Showers (Remastered)"),
    ]
    saved = await save_to_navidrome("Mix", tracks, client=_client(fake))
    assert fake.created == [("Mix", ["s2", "s1"])]
    assert (saved.playlist_id, saved.matched, saved.n_tracks) == ("pl9", 3, 4)
    assert saved.unmatched == [TrackRef(artist="Radiohead", title="Reckoner")]


async def test_nothing_matched_creates_nothing(fake: FakeNavidrome) -> None:
    saved = await save_to_navidrome("Mix", [TrackRef(artist="X", title="Y")], client=_client(fake))
    assert fake.created == []
    assert saved.playlist_id is None
    assert "was not created" in describe(saved)


async def test_navidrome_down_raises() -> None:
    def refused(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    with pytest.raises(SubsonicUnavailable):
        await save_to_navidrome("Mix", [TrackRef(artist="A", title="x")], client=_client(refused))


async def test_not_configured_raises_before_any_request() -> None:
    with (
        patch.object(nd_playlist, "navidrome_configured", return_value=False),
        pytest.raises(NavidromeNotConfigured),
    ):
        await save_to_navidrome("Mix", [TrackRef(artist="A", title="x")])


def test_navidrome_configured_needs_url_user_and_password() -> None:
    base = {"navidrome_url": "http://nd", "navidrome_user": "me", "navidrome_password": "pw"}
    assert navidrome_configured(Settings(_env_file=None, **base))  # type: ignore[call-arg]
    assert not navidrome_configured(Settings(_env_file=None, **{**base, "navidrome_password": ""}))  # type: ignore[call-arg]


def test_describe_lists_unmatched() -> None:
    saved = SavedPlaylist(
        name="Mix", n_tracks=2, playlist_id="pl1", matched=1,
        unmatched=[TrackRef(artist="B", title="y")],
    )  # fmt: skip
    text = describe(saved)
    assert text.startswith("Saved playlist 'Mix' to the music library (Navidrome id pl1): 1 of 2")
    assert text.endswith("- B — y")


def test_list_sync_runs_off_loop_and_handles_unconfigured(fake: FakeNavidrome) -> None:
    with (
        patch.object(nd_playlist, "navidrome_configured", return_value=True),
        patch.object(nd_playlist, "_client_from_settings", return_value=_client(fake)),
    ):
        [summary] = list_navidrome_playlists_sync() or []
    assert (summary.id, summary.song_count) == ("pl9", 2)
    with patch.object(nd_playlist, "navidrome_configured", return_value=False):
        assert list_navidrome_playlists_sync() is None
