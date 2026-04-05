from __future__ import annotations

from pydantic import BaseModel


class ChunkMetadata(BaseModel):
    url: str
    title: str
    section: str
    language: str = "da"
    doc_id: str  # hash of url + section
    parent_id: str | None = None  # set by ParentDocChunker; points to parent section chunk


class Chunk(BaseModel):
    id: str
    text: str
    metadata: ChunkMetadata
    embedding: list[float] | None = None
