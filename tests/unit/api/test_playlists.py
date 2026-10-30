"""Unit tests for api.playlists — CRUD, reorder and stars against a stateful fake Navidrome."""

from tests.unit.api.conftest import failed


def _create(api, name="Mix", song_ids=("s1", "s2")) -> dict:
    response = api.post("/api/playlists", json={"name": name, "songIds": list(song_ids)})
    assert response.status_code == 201
    return response.json()


class TestCrud:
    def test_create_returns_playlist_with_songs(self, nd_api):
        body = _create(nd_api)
        assert body["name"] == "Mix"
        assert body["songCount"] == 2 and body["duration"] == 400
        assert [s["id"] for s in body["songs"]] == ["s1", "s2"]
        assert body["changed"] and body["coverArt"]

    def test_create_empty(self, nd_api):
        assert _create(nd_api, song_ids=())["songs"] == []

    def test_create_rejects_blank_name(self, nd_api):
        assert nd_api.post("/api/playlists", json={"name": ""}).status_code == 422

    def test_list_has_no_songs(self, nd_api):
        _create(nd_api)
        listed = nd_api.get("/api/playlists").json()
        assert [p["name"] for p in listed] == ["Mix"]
        assert "songs" not in listed[0]

    def test_get(self, nd_api):
        pid = _create(nd_api)["id"]
        assert [s["id"] for s in nd_api.get(f"/api/playlists/{pid}").json()["songs"]] == [
            "s1",
            "s2",
        ]

    def test_get_missing_is_404(self, nd_api):
        assert nd_api.get("/api/playlists/nope").status_code == 404

    def test_delete(self, nd_api, fake_nd):
        pid = _create(nd_api)["id"]
        assert nd_api.delete(f"/api/playlists/{pid}").status_code == 204
        assert fake_nd.playlists == {}
        assert nd_api.delete(f"/api/playlists/{pid}").status_code == 404


class TestPatch:
    def test_reorder_is_full_rewrite(self, nd_api, fake_nd):
        pid = _create(nd_api, song_ids=("s1", "s2", "s3"))["id"]
        body = nd_api.patch(f"/api/playlists/{pid}", json={"songIds": ["s3", "s1", "s2"]}).json()
        assert [s["id"] for s in body["songs"]] == ["s3", "s1", "s2"]
        assert fake_nd.playlists[pid]["name"] == "Mix"

    def test_rewrite_to_empty_clears(self, nd_api):
        pid = _create(nd_api)["id"]
        assert nd_api.patch(f"/api/playlists/{pid}", json={"songIds": []}).json()["songs"] == []

    def test_add_and_remove(self, nd_api):
        pid = _create(nd_api)["id"]
        body = nd_api.patch(
            f"/api/playlists/{pid}", json={"add": ["s3"], "removeIndexes": [0]}
        ).json()
        assert [s["id"] for s in body["songs"]] == ["s2", "s3"]

    def test_rename(self, nd_api):
        pid = _create(nd_api)["id"]
        assert nd_api.patch(f"/api/playlists/{pid}", json={"name": " Night "}).json()["name"] == (
            "Night"
        )

    def test_rewrite_plus_rename(self, nd_api):
        pid = _create(nd_api)["id"]
        body = nd_api.patch(f"/api/playlists/{pid}", json={"name": "B", "songIds": ["s2"]}).json()
        assert body["name"] == "B" and [s["id"] for s in body["songs"]] == ["s2"]

    def test_rewrite_with_add_is_422(self, nd_api):
        pid = _create(nd_api)["id"]
        response = nd_api.patch(f"/api/playlists/{pid}", json={"songIds": ["s1"], "add": ["s2"]})
        assert response.status_code == 422

    def test_unknown_song_is_404(self, nd_api):
        pid = _create(nd_api)["id"]
        assert nd_api.patch(f"/api/playlists/{pid}", json={"songIds": ["zz"]}).status_code == 404


class TestStarred:
    def test_star_list_unstar(self, nd_api):
        assert nd_api.get("/api/starred").json() == []
        assert nd_api.put("/api/starred/s2").status_code == 204
        starred = nd_api.get("/api/starred").json()
        assert [s["id"] for s in starred] == ["s2"] and starred[0]["starred"] is True
        assert nd_api.delete("/api/starred/s2").status_code == 204
        assert nd_api.get("/api/starred").json() == []

    def test_star_unknown_is_404(self, nd_api):
        assert nd_api.put("/api/starred/zz").status_code == 404

    def test_navidrome_error_is_502(self, make_api):
        api = make_api(lambda _r: failed(0, "boom"))
        assert api.get("/api/starred").status_code == 502
