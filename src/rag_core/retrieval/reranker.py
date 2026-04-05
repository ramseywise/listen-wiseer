from __future__ import annotations

from schemas.chunks import Chunk


class Reranker:
    """Reranker stub. Replace with Cohere or cross-encoder implementation."""

    def rerank(self, query: str, chunks: list[Chunk]) -> list[Chunk]:
        raise NotImplementedError("Reranker not yet implemented")
