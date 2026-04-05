from __future__ import annotations

from opensearchpy import AsyncOpenSearch
from pydantic_settings import BaseSettings
from schemas.chunks import Chunk
from schemas.retrieval import RetrievalResult

from utils.logging import get_logger

log = get_logger(__name__)

INDEX_MAPPING = {
    "mappings": {
        "properties": {
            "text": {"type": "text"},
            "title": {"type": "text"},
            "section": {"type": "keyword"},
            "url": {"type": "keyword"},
            "language": {"type": "keyword"},
            "embedding": {"type": "knn_vector", "dimension": 1024},
        }
    },
    "settings": {"index": {"knn": True}},
}


class OpenSearchSettings(BaseSettings):
    url: str = "https://localhost:9200"
    index: str = "help-docs"
    user: str = ""
    password: str = ""
    model_config = {"env_prefix": "OPENSEARCH_"}


class OpenSearchClient:
    def __init__(self, settings: OpenSearchSettings) -> None:
        self._settings = settings
        self._client = AsyncOpenSearch(
            hosts=[settings.url],
            http_auth=(settings.user, settings.password) if settings.user else None,
            verify_certs=False,
            ssl_show_warn=False,
        )

    async def ensure_index(self, dims: int = 1024) -> None:
        """Create index with knn_vector field + BM25 text field if not exists."""
        index = self._settings.index
        exists = await self._client.indices.exists(index=index)
        if exists:
            log.info("opensearch.index.exists", index=index)
            return

        mapping = dict(INDEX_MAPPING)
        mapping["mappings"]["properties"]["embedding"]["dimension"] = dims
        await self._client.indices.create(index=index, body=mapping)
        log.info("opensearch.index.created", index=index, dims=dims)

    async def hybrid_search(
        self,
        query_text: str,
        query_vector: list[float],
        k: int = 5,
        section_filter: list[str] | None = None,
        bm25_weight: float = 0.3,
        vector_weight: float = 0.7,
    ) -> list[RetrievalResult]:
        """Run hybrid BM25 + k-NN search and return ranked results."""
        hybrid_queries: list[dict] = [
            {"match": {"text": query_text}},
            {"knn": {"embedding": {"vector": query_vector, "k": k}}},
        ]

        body: dict = {
            "query": {"hybrid": {"queries": hybrid_queries}},
            "size": k,
        }

        if section_filter:
            body["query"] = {
                "bool": {
                    "must": {"hybrid": {"queries": hybrid_queries}},
                    "filter": {"terms": {"section": section_filter}},
                }
            }

        response = await self._client.search(index=self._settings.index, body=body)
        hits = response["hits"]["hits"]

        results = []
        for hit in hits:
            src = hit["_source"]
            from schemas.chunks import ChunkMetadata

            chunk = Chunk(
                id=hit["_id"],
                text=src["text"],
                metadata=ChunkMetadata(
                    url=src["url"],
                    title=src["title"],
                    section=src["section"],
                    language=src.get("language", "da"),
                    doc_id=hit["_id"],
                ),
            )
            results.append(RetrievalResult(chunk=chunk, score=hit["_score"]))

        log.info("opensearch.search.done", n_results=len(results), query=query_text[:60])
        return results

    async def upsert_chunks(self, chunks: list[Chunk]) -> None:
        """Bulk upsert chunks into the index."""
        if not chunks:
            return

        actions = []
        for chunk in chunks:
            actions.append({"index": {"_index": self._settings.index, "_id": chunk.id}})
            doc = {
                "text": chunk.text,
                "title": chunk.metadata.title,
                "section": chunk.metadata.section,
                "url": chunk.metadata.url,
                "language": chunk.metadata.language,
            }
            if chunk.embedding is not None:
                doc["embedding"] = chunk.embedding
            actions.append(doc)

        response = await self._client.bulk(body=actions)
        if response.get("errors"):
            log.error("opensearch.upsert.errors", n_chunks=len(chunks))
        else:
            log.info("opensearch.upsert.done", n_chunks=len(chunks))
