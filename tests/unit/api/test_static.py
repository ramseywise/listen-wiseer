"""Built web/ served by the API: hashed assets immutable, SPA fallback no-cache, /api stays JSON."""

from collections.abc import Callable, Iterator
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from api.app import create_app
from api.static import IMMUTABLE, NO_CACHE
from sources.subsonic import SubsonicClient
from tests.unit.api.conftest import connect_to, navidrome

INDEX = "<!doctype html><div id=root></div>"


@pytest.fixture
def dist(tmp_path: Path) -> Path:
    d = tmp_path / "dist"
    (d / "assets").mkdir(parents=True)
    (d / "index.html").write_text(INDEX)
    (d / "assets" / "index-abc123.js").write_text("console.log(1)")
    (d / "favicon.svg").write_text("<svg/>")
    (tmp_path / "secret.txt").write_text("outside dist")
    return d


@pytest.fixture
def web_api(tmp_path: Path) -> Iterator[Callable[[Path], TestClient]]:
    opened: list[TestClient] = []

    def _make(web_dist: Path) -> TestClient:
        subsonic = SubsonicClient(
            "http://nd.test", "me", "pw", transport=httpx.MockTransport(navidrome)
        )
        app = create_app(
            subsonic=subsonic, db_connect=connect_to(tmp_path / "t.db"), web_dist=web_dist
        )
        client = TestClient(app)
        client.__enter__()
        opened.append(client)
        return client

    yield _make
    for client in opened:
        client.__exit__(None, None, None)


def test_root_and_spa_routes_serve_index_no_cache(web_api, dist: Path) -> None:
    api = web_api(dist)
    for path in ("/", "/albums/al1", "/playlists/pl1/edit"):
        r = api.get(path)
        assert r.status_code == 200, path
        assert r.text == INDEX
        assert r.headers["cache-control"] == NO_CACHE
        assert r.headers["content-type"].startswith("text/html")


def test_hashed_asset_is_immutable(web_api, dist: Path) -> None:
    r = web_api(dist).get("/assets/index-abc123.js")
    assert r.status_code == 200
    assert r.text == "console.log(1)"
    assert r.headers["cache-control"] == IMMUTABLE


def test_missing_asset_is_404_not_index(web_api, dist: Path) -> None:
    r = web_api(dist).get("/assets/gone-000.js")
    assert r.status_code == 404
    assert r.json() == {"detail": "Not Found"}


def test_top_level_dist_file_served(web_api, dist: Path) -> None:
    r = web_api(dist).get("/favicon.svg")
    assert r.status_code == 200
    assert r.text == "<svg/>"
    assert r.headers["cache-control"] == NO_CACHE


def test_traversal_outside_dist_falls_back_to_index(web_api, dist: Path) -> None:
    r = web_api(dist).get("/..%2Fsecret.txt")
    assert r.status_code == 200
    assert r.text == INDEX


def test_api_404s_stay_json(web_api, dist: Path) -> None:
    api = web_api(dist)
    assert api.get("/api/nope").status_code == 404
    assert api.get("/api/nope").json() == {"detail": "Not Found"}
    assert api.get("/api").json() == {"detail": "Not Found"}
    r = api.get("/api/albums/missing")  # route-level 404 keeps its detail
    assert r.status_code == 404
    assert r.headers["content-type"] == "application/json"


def test_api_routes_unaffected(web_api, dist: Path) -> None:
    r = web_api(dist).get("/api/health")
    assert r.status_code == 200
    assert r.json()["navidrome"] is True


def test_non_get_unknown_path_stays_json(web_api, dist: Path) -> None:
    r = web_api(dist).post("/somewhere")
    assert r.status_code in (404, 405)
    assert r.headers["content-type"] == "application/json"


def test_missing_dist_is_a_no_op(web_api, tmp_path: Path) -> None:
    api = web_api(tmp_path / "no-build")
    r = api.get("/")
    assert r.status_code == 404
    assert r.json() == {"detail": "Not Found"}
    assert api.get("/api/health").status_code == 200
