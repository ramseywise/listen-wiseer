"""Unit tests for agent.tools.downloads — legal download search + fetch."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from agent.tools import downloads
from sources.schemas import FreeTrack
from utils.exceptions import SourceError

FREE = FreeTrack(source="archive_org", source_id="show1/a.mp3", artist="Band A",
                 title="Ripple", download_url="https://archive.org/download/show1/a.mp3",
                 license_url="https://cc/by")  # fmt: skip


@contextmanager
def _db():
    yield None


def test_find_lists_with_licence():
    with patch.object(downloads, "find_free", return_value=[FREE]):
        out = downloads._find_free_downloads("Band A")
    assert out == "1. Band A — Ripple (archive_org, licence: https://cc/by)"


def test_find_none_points_to_bandcamp():
    with patch.object(downloads, "find_free", return_value=[]):
        assert "Bandcamp" in downloads._find_free_downloads("Radiohead", "Creep")


def test_download_success():
    with (
        patch.object(downloads, "find_free", return_value=[FREE]),
        patch.object(downloads, "db", _db),
        patch.object(downloads, "download", return_value=Path("/lib/a.mp3")) as dl,
    ):
        out = downloads._download_track("Band A", "Ripple", mbid="m")
    assert out.startswith("Downloaded Band A — Ripple") and out.endswith("/lib/a.mp3")
    assert dl.call_args.kwargs == {"mbid": "m"}


def test_download_failure_reported():
    with (
        patch.object(downloads, "find_free", return_value=[FREE]),
        patch.object(downloads, "db", _db),
        patch.object(downloads, "download", side_effect=SourceError("HTTP 403")),
    ):
        assert downloads._download_track("Band A", "Ripple").startswith("Download failed")
