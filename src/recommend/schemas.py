from typing import Literal

from pydantic import BaseModel, Field


class RecommendRequest(BaseModel):
    request_type: Literal["track", "artist", "playlist", "genre"]
    seed_id: str  # track_id | artist_id | playlist_id | genre_name
    target_playlist_id: str | None = None  # if set: load classifier for this playlist
    k: int = Field(default=10, ge=1, le=50)


class RecommendResult(BaseModel):
    track_uris: list[str]  # "spotify:track:{id}"
    track_ids: list[str]  # raw Spotify IDs
    track_names: list[str]  # human-readable for agent response
    scores: list[float]  # similarity/rerank scores, 0-1
    pipeline_used: str  # "track" | "artist" | "playlist" | "genre"
    explanation: str  # 1-2 sentence summary for agent to surface to user
