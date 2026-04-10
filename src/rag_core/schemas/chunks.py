from __future__ import annotations

from pydantic import BaseModel


class ChunkMetadata(BaseModel):
    url: str
    title: str
    section: str
    language: str = "en"
    doc_id: str
    parent_id: str | None = None
    # Music-domain enrichment fields
    topic: str | None = None  # e.g. "artist", "genre", "history"
    content_type: str | None = None  # e.g. "biography", "wiki", "commentary"
    source_id: str | None = None  # upstream identifier (Spotify ID, MusicBrainz, etc.)


class Chunk(BaseModel):
    id: str
    text: str
    metadata: ChunkMetadata
    embedding: list[float] | None = None
