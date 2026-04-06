from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel

from .chunks import Chunk


class Intent(StrEnum):
    ARTIST_INFO = "artist_info"  # "who is Aphex Twin?", "tell me about Radiohead"
    GENRE_INFO = "genre_info"  # "what is zouk?", "explain bossa nova"
    HISTORY = "history"  # "what have I been listening to?", "my recent plays"
    CHIT_CHAT = "chit_chat"  # greetings, small talk
    OUT_OF_SCOPE = "out_of_scope"  # unrelated to music


class RetrievalResult(BaseModel):
    chunk: Chunk
    score: float
    source: str = "hybrid"  # "vector" | "bm25" | "hybrid"


class GradedChunk(BaseModel):
    chunk: Chunk
    score: float
    relevant: bool
