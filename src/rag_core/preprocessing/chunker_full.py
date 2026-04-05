"""Chunking for the RAG system."""

from abc import ABC, abstractmethod

from langchain_text_splitters import (
    CharacterTextSplitter,
    HTMLSemanticPreservingSplitter,
    RecursiveCharacterTextSplitter,
)

from utils.logging import get_logger

logger = get_logger(__name__)


class Chunker(ABC):
    """Abstract base class for chunking text."""

    @abstractmethod
    def chunk(self, text: str) -> list[str]:
        """Split the input text into smaller chunks.

        Args:
            text (str): The full input document.

        Returns:
            List[str]: A list of chunked strings.

        """
        pass


class FixedCharacterChunker(Chunker):
    """Split text into (almost) fixed-size, non-overlapping character chunks."""

    def __init__(self, chunk_size: int = 1000):
        """Initialize the FixedCharacterChunker."""
        self.splitter = CharacterTextSplitter(chunk_size=chunk_size, chunk_overlap=0, separator="")

    def chunk(self, text: str) -> list[str]:
        """Split the input text into smaller chunks."""
        chunks = self.splitter.split_text(text)
        logger.debug(f"[Chunker] Chunked {len(text)} chars → {len(chunks)} chunks")
        return chunks


class OverlappingCharacterChunker(Chunker):
    """Splits text into (almost) fixed-size, overlapping character chunks.

    Each chunk overlaps its predecessor by `chunk_overlap` characters.
    """

    def __init__(self, chunk_size: int = 1000, chunk_overlap: int = 200):
        """Initialize the OverlappingCharacterChunker."""
        self.splitter = CharacterTextSplitter(
            chunk_size=chunk_size, chunk_overlap=chunk_overlap, separator=""
        )

    def chunk(self, text: str) -> list[str]:
        """Split the input text into smaller chunks."""
        chunks = self.splitter.split_text(text)
        logger.debug(f"[Chunker] Text={len(text)} chars → {len(chunks)} overlapping chunks")
        return chunks


class StructuredChunker(Chunker):
    """Split text into hierarchical chunks, preserving natural boundaries."""

    # NOTE: LangChain's RecursiveCharacterTextSplitter splits on larger separators first (e.g., paragraphs)
    # This could be approved by using the html-elements and sections!!

    def __init__(
        self,
        chunk_size: int = 1000,
        separators: list[str] | None = None,
    ):
        """Initialize the StructuredChunker."""
        # Default separators: blank lines, then newlines, then spaces, then characters
        if separators is None:
            separators = ["\n\n", "\n", " ", ""]
        self.splitter = RecursiveCharacterTextSplitter(
            separators=separators,
            chunk_size=chunk_size,
            chunk_overlap=0,
        )

    def chunk(self, text: str) -> list[str]:
        """Split text into structured chunks."""
        chunks = self.splitter.split_text(text)
        logger.debug(f"[Chunker] Text={len(text)} chars → {len(chunks)} structured chunks")
        return chunks


class HtmlChunker(Chunker):
    """Split HTML content into chunks while preserving semantic elements like tables and lists."""

    def __init__(
        self,
        headers_to_split_on: list[tuple[str, str]],
        max_chunk_size: int = 1000,
        chunk_overlap: int = 0,
        allowlist_tags: list[str] | None = None,
        denylist_tags: list[str] | None = None,
    ):
        """Initialize the HtmlChunker."""
        self._chunk_overlap = chunk_overlap
        # HTMLSemanticPreservingSplitter preserves tables, lists, etc.
        self.splitter = HTMLSemanticPreservingSplitter(
            max_chunk_size=max_chunk_size,
            chunk_overlap=chunk_overlap,
            allowlist_tags=allowlist_tags,
            denylist_tags=denylist_tags,
            headers_to_split_on=headers_to_split_on,
        )

    def chunk(self, text: str) -> list[str]:
        """Split HTML content into chunks while preserving semantic elements like tables and lists."""
        # HTML splitter returns Document objects
        docs = self.splitter.split_text(text)
        chunks = [doc.page_content for doc in docs]
        logger.debug(f"[Chunker] HTML {len(text)} chars → {len(chunks)} semantic chunks")
        return chunks


class AdjacencyChunker(Chunker):
    """Split text into non-overlapping character chunks and provides adjacency via index."""

    # NOTE: see vectorgraph based RAG-systems. Instead of logging adjacent chunks they create a graph containing
    # the chunks as nodes and the context similarity between chunks as edges.
    def __init__(self, chunk_size: int = 1000):
        """Initialize the AdjacencyChunker."""
        # no overlap
        self.splitter = CharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=0,
        )
        self._chunks: list[str] = []

    def chunk(self, text: str) -> list[str]:
        """Return a list of chunks in order. Adjacency is implied by list indices."""
        self._chunks = self.splitter.split_text(text)
        return self._chunks

    def neighbors(self, chunk_id: str) -> tuple[str | None, str | None]:
        """Return the IDs of the previous and next chunks, if they exist (else None)."""
        # ensure chunk was called at least once
        if not self._chunks:
            raise RuntimeError("Call .chunk(text) before calling neighbors().")

        try:
            base_id, idx_str = chunk_id.rsplit("_chunk", 1)
            idx = int(idx_str)
        except ValueError as err:
            raise ValueError(f"Bad chunk_id format: {chunk_id}") from err

        # ensure chunk was called at least once
        if not hasattr(self, "_chunks"):
            raise RuntimeError("Call .chunk(text) before asking for neighbors()")

        prev_id = f"{base_id}_chunk{idx - 1}" if idx > 0 else None
        next_id = f"{base_id}_chunk{idx + 1}" if (idx + 1) < len(self._chunks) else None
        return prev_id, next_id


# ============================================================
# CHUNKING STRATEGIES COMPARISON
# ============================================================


def chunk_fixed_size(text: str, chunk_size: int = 500, overlap: int = 50) -> list[str]:
    """Simple fixed-size chunking."""
    chunks = []
    for i in range(0, len(text), chunk_size - overlap):
        chunks.append(text[i : i + chunk_size])
    return chunks


def chunk_semantic(text: str, max_chunk_size: int = 500) -> list[str]:
    """
    Semantic chunking - split on sentence boundaries.
    Respects paragraph and sentence structure.
    """
    import re

    # Split into paragraphs first
    paragraphs = re.split(r"\n\n+", text)

    chunks = []
    current_chunk = ""

    for para in paragraphs:
        # If paragraph itself is too long, split by sentences
        if len(para) > max_chunk_size:
            sentences = re.split(r"(?<=[.!?])\s+", para)
            for sent in sentences:
                if len(current_chunk) + len(sent) < max_chunk_size:
                    current_chunk += " " + sent if current_chunk else sent
                else:
                    if current_chunk:
                        chunks.append(current_chunk.strip())
                    current_chunk = sent
        else:
            if len(current_chunk) + len(para) < max_chunk_size:
                current_chunk += "\n\n" + para if current_chunk else para
            else:
                if current_chunk:
                    chunks.append(current_chunk.strip())
                current_chunk = para

    if current_chunk:
        chunks.append(current_chunk.strip())

    return chunks


def chunk_recursive(
    text: str, max_chunk_size: int = 500, separators: list[str] = None
) -> list[str]:
    """
    Recursive chunking - try larger separators first, then smaller.
    Similar to LangChain's RecursiveCharacterTextSplitter.
    """
    if separators is None:
        separators = ["\n\n", "\n", ". ", " ", ""]

    if len(text) <= max_chunk_size:
        return [text] if text.strip() else []

    for sep in separators:
        if sep in text:
            parts = text.split(sep)
            chunks = []
            current = ""

            for part in parts:
                if len(current) + len(part) + len(sep) <= max_chunk_size:
                    current = current + sep + part if current else part
                else:
                    if current:
                        chunks.append(current)
                    if len(part) > max_chunk_size:
                        # Recurse with next separator
                        chunks.extend(
                            chunk_recursive(
                                part, max_chunk_size, separators[separators.index(sep) + 1 :]
                            )
                        )
                    else:
                        current = part

            if current:
                chunks.append(current)

            return chunks

    # Fallback: hard split
    return [text[i : i + max_chunk_size] for i in range(0, len(text), max_chunk_size)]
