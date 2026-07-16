import pytest
from pydantic import ValidationError
from recommend.schemas import RecommendRequest, RecommendResult


class TestRecommendRequest:
    def test_valid_track_request(self):
        req = RecommendRequest(request_type="track", seed_id="abc123")
        assert req.request_type == "track"
        assert req.seed_id == "abc123"
        assert req.k == 10
        assert req.target_playlist_id is None

    def test_valid_artist_request(self):
        req = RecommendRequest(request_type="artist", seed_id="artist_xyz", k=20)
        assert req.request_type == "artist"
        assert req.k == 20

    def test_valid_playlist_request_with_target(self):
        req = RecommendRequest(
            request_type="playlist",
            seed_id="pl_abc",
            target_playlist_id="pl_target",
            k=5,
        )
        assert req.target_playlist_id == "pl_target"

    def test_valid_genre_request(self):
        req = RecommendRequest(request_type="genre", seed_id="zouk", k=50)
        assert req.k == 50

    def test_invalid_request_type(self):
        with pytest.raises(ValidationError):
            RecommendRequest(request_type="invalid", seed_id="abc123")

    def test_k_above_max_raises(self):
        with pytest.raises(ValidationError):
            RecommendRequest(request_type="track", seed_id="abc", k=51)

    def test_k_below_min_raises(self):
        with pytest.raises(ValidationError):
            RecommendRequest(request_type="track", seed_id="abc", k=0)

    def test_k_at_boundary_values(self):
        req_min = RecommendRequest(request_type="track", seed_id="abc", k=1)
        req_max = RecommendRequest(request_type="track", seed_id="abc", k=50)
        assert req_min.k == 1
        assert req_max.k == 50


class TestRecommendResult:
    def test_valid_result(self):
        result = RecommendResult(
            track_uris=["spotify:track:abc123"],
            track_ids=["abc123"],
            track_names=["Some Track"],
            scores=[0.95],
            pipeline_used="track",
            explanation="Found 1 track similar to the seed.",
        )
        assert result.track_uris == ["spotify:track:abc123"]
        assert result.scores == [0.95]

    def test_empty_result(self):
        result = RecommendResult(
            track_uris=[],
            track_ids=[],
            track_names=[],
            scores=[],
            pipeline_used="genre",
            explanation="Genre not found in ENOA map.",
        )
        assert result.track_uris == []

    def test_missing_required_field_raises(self):
        with pytest.raises(ValidationError):
            RecommendResult(
                track_uris=["spotify:track:abc"],
                track_ids=["abc"],
                track_names=["Track"],
                scores=[0.9],
                pipeline_used="track",
                # explanation missing
            )
