from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel

from .chunks import Chunk


class Intent(StrEnum):
    HOW_TO = "how_to"
    TROUBLESHOOT = "troubleshoot"
    REFERENCE = "reference"
    CHIT_CHAT = "chit_chat"
    OUT_OF_SCOPE = "out_of_scope"


class RetrievalResult(BaseModel):
    chunk: Chunk
    score: float
    source: str = "hybrid"  # "vector" | "bm25" | "hybrid"


class GradedChunk(BaseModel):
    chunk: Chunk
    score: float
    relevant: bool
