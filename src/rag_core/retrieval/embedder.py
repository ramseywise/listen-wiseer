from __future__ import annotations

from pydantic_settings import BaseSettings
from sentence_transformers import SentenceTransformer


class EmbedderSettings(BaseSettings):
    model: str = "intfloat/multilingual-e5-large"
    model_config = {"env_prefix": "EMBEDDING_"}


class MultilingualEmbedder:
    """Wraps sentence-transformers multilingual model.

    multilingual-e5-large: 1024 dims, supports DA/FR/DE/NL/PT/ES.
    Prefix: 'query: ' for queries, 'passage: ' for docs (E5 requirement).
    """

    QUERY_PREFIX = "query: "
    PASSAGE_PREFIX = "passage: "

    def __init__(self, settings: EmbedderSettings) -> None:
        self.model = SentenceTransformer(settings.model)

    def embed_query(self, text: str) -> list[float]:
        """Embed a query with the required 'query: ' prefix."""
        prefixed = self.QUERY_PREFIX + text
        vector = self.model.encode(prefixed, convert_to_numpy=True)
        return vector.tolist()

    def embed_passage(self, text: str) -> list[float]:
        """Embed a single passage with the required 'passage: ' prefix."""
        prefixed = self.PASSAGE_PREFIX + text
        vector = self.model.encode(prefixed, convert_to_numpy=True)
        return vector.tolist()

    def embed_passages(self, texts: list[str]) -> list[list[float]]:
        """Embed document passages with the required 'passage: ' prefix."""
        prefixed = [self.PASSAGE_PREFIX + t for t in texts]
        vectors = self.model.encode(prefixed, convert_to_numpy=True)
        return [v.tolist() for v in vectors]
