from __future__ import annotations

import hashlib
import re
from abc import ABC, abstractmethod

from pydantic import BaseModel
from schemas.chunks import Chunk, ChunkMetadata


class ChunkerConfig(BaseModel):
    max_tokens: int = 512
    overlap_tokens: int = 64
    min_tokens: int = 50


# Rough word-to-token ratio for multilingual text (conservative)
_WORDS_PER_TOKEN: float = 0.75


def _approx_tokens(text: str) -> int:
    return max(1, int(len(text.split()) / _WORDS_PER_TOKEN))


def _make_doc_id(url: str, section: str) -> str:
    return hashlib.sha256(f"{url}:{section}".encode()).hexdigest()[:16]


def _make_chunk(text: str, url: str, title: str, section: str, doc_id: str) -> Chunk:
    chunk_id = hashlib.sha256(f"{doc_id}:{text[:64]}".encode()).hexdigest()[:20]
    return Chunk(
        id=chunk_id,
        text=text,
        metadata=ChunkMetadata(
            url=url,
            title=title,
            section=section,
            doc_id=doc_id,
        ),
    )


class Chunker(ABC):
    """Abstract base class for all chunking strategies."""

    @abstractmethod
    def chunk_document(self, doc: dict) -> list[Chunk]:
        """Split a document dict into Chunk objects."""
        ...


# ---------------------------------------------------------------------------
# Shared text-split helpers (used by HtmlAwareChunker and StructuredChunker)
# ---------------------------------------------------------------------------


def _hard_split_text(text: str, config: ChunkerConfig) -> list[str]:
    """Word-window split returning raw text strings (no Chunk objects)."""
    words = text.split()
    step = max(1, int(config.max_tokens * _WORDS_PER_TOKEN))
    overlap_w = int(config.overlap_tokens * _WORDS_PER_TOKEN)
    min_t = config.min_tokens

    chunks: list[str] = []
    i = 0
    while i < len(words):
        window = words[i : i + step]
        chunk_text = " ".join(window)
        if _approx_tokens(chunk_text) >= min_t:
            chunks.append(chunk_text)
        i += step - overlap_w

    return chunks if chunks else [text]


def _merge_with_overlap(pieces: list[str], config: ChunkerConfig) -> list[str]:
    """Greedily merge pieces up to max_tokens, carrying overlap_tokens of context."""
    max_t = config.max_tokens
    min_t = config.min_tokens

    chunks: list[str] = []
    current_words: list[str] = []

    for piece in pieces:
        piece_words = piece.split()
        if not piece_words:
            continue
        tentative = current_words + piece_words
        if _approx_tokens(" ".join(tentative)) <= max_t:
            current_words = tentative
        else:
            if current_words:
                text_out = " ".join(current_words)
                if _approx_tokens(text_out) >= min_t:
                    chunks.append(text_out)
                current_words = current_words[-config.overlap_tokens :] + piece_words
            else:
                chunks.extend(_hard_split_text(" ".join(piece_words), config))
                current_words = []

    if current_words:
        text_out = " ".join(current_words)
        if _approx_tokens(text_out) >= min_t:
            chunks.append(text_out)

    return chunks if chunks else [" ".join(pieces)]


def _recursive_split(text: str, config: ChunkerConfig) -> list[str]:
    """Recursively split: paragraph → sentence → word-window."""
    if _approx_tokens(text) <= config.max_tokens:
        return [text] if _approx_tokens(text) >= config.min_tokens else []

    paragraphs = re.split(r"\n{2,}", text)
    if len(paragraphs) > 1:
        return _merge_with_overlap(paragraphs, config)

    sentences = re.split(r"(?<=[.!?])\s+", text)
    if len(sentences) > 1:
        return _merge_with_overlap(sentences, config)

    return _hard_split_text(text, config)


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------


class HtmlAwareChunker(Chunker):
    """Splits documents on HTML section boundaries with a recursive fallback.

    Primary strategy: split on h1/h2/h3 heading boundaries extracted from
    the doc's section hierarchy.  Each resulting section becomes one chunk.

    Fallback: if any section exceeds max_tokens, recursively split on
    paragraph boundaries first, then on sentence boundaries, with
    overlap_tokens of overlap preserved between adjacent splits.

    Input doc dict keys: url, title, section, text (plain text, HTML stripped).
    """

    def __init__(self, config: ChunkerConfig) -> None:
        self.config = config

    def chunk_document(self, doc: dict) -> list[Chunk]:
        url: str = doc.get("url", "")
        title: str = doc.get("title", "")
        section: str = doc.get("section", "")
        # TODO(2): real scraped docs use "full_text"; fictional corpus uses "text".
        # A standardizer should normalise this upstream before chunking.
        # TODO(2): real scraped docs include a "sections" field [{heading, level, content}]
        # already extracted from HTML. A SectionAwareChunker could consume that directly
        # instead of re-detecting headings via regex on stripped text.
        text: str = (doc.get("text") or doc.get("full_text") or "").strip()

        if not text:
            return []

        sections = self._split_sections(text)
        chunks: list[Chunk] = []
        for sec_title, sec_text in sections:
            sec_text = sec_text.strip()
            if not sec_text:
                continue
            sub_section = f"{section}/{sec_title}".strip("/") if sec_title else section
            doc_id = _make_doc_id(url, sub_section)

            if _approx_tokens(sec_text) <= self.config.max_tokens:
                if _approx_tokens(sec_text) >= self.config.min_tokens:
                    chunks.append(_make_chunk(sec_text, url, title, sub_section, doc_id))
            else:
                sub_chunks = self._recursive_split(sec_text)
                for i, sub_text in enumerate(sub_chunks):
                    chunk_section = f"{sub_section}#{i}" if len(sub_chunks) > 1 else sub_section
                    chunk_doc_id = _make_doc_id(url, chunk_section)
                    chunks.append(_make_chunk(sub_text, url, title, chunk_section, chunk_doc_id))

        if not chunks and _approx_tokens(text) >= self.config.min_tokens:
            doc_id = _make_doc_id(url, section)
            chunks.append(_make_chunk(text, url, title, section, doc_id))

        return chunks

    def _split_sections(self, text: str) -> list[tuple[str, str]]:
        heading_re = re.compile(r"^(#{1,3}\s+.+|[A-Z][A-Z0-9 :/-]{2,60})$", re.MULTILINE)
        positions = [m.start() for m in heading_re.finditer(text)]

        if not positions:
            return [("", text)]

        sections: list[tuple[str, str]] = []
        if positions[0] > 0:
            sections.append(("", text[: positions[0]]))

        for i, pos in enumerate(positions):
            end = positions[i + 1] if i + 1 < len(positions) else len(text)
            line_end = text.index("\n", pos) if "\n" in text[pos:end] else end
            heading = text[pos:line_end].strip().lstrip("#").strip()
            body = text[line_end:end].strip()
            sections.append((heading, body))

        return sections

    def _recursive_split(self, text: str) -> list[str]:
        return _recursive_split(text, self.config)


class FixedChunker(Chunker):
    """Hard word-count splits, no overlap. Baseline benchmark."""

    def __init__(self, config: ChunkerConfig) -> None:
        self.config = config

    def chunk_document(self, doc: dict) -> list[Chunk]:
        url: str = doc.get("url", "")
        title: str = doc.get("title", "")
        section: str = doc.get("section", "")
        text: str = (doc.get("text") or doc.get("full_text") or "").strip()

        if not text:
            return []

        doc_id = _make_doc_id(url, section)
        return _fixed_split(text, url, title, section, doc_id, self.config)


class OverlappingChunker(Chunker):
    """Fixed size + overlap_tokens carried between chunks."""

    def __init__(self, config: ChunkerConfig) -> None:
        self.config = config

    def chunk_document(self, doc: dict) -> list[Chunk]:
        url: str = doc.get("url", "")
        title: str = doc.get("title", "")
        section: str = doc.get("section", "")
        text: str = (doc.get("text") or doc.get("full_text") or "").strip()

        if not text:
            return []

        doc_id = _make_doc_id(url, section)
        return _overlapping_split(text, url, title, section, doc_id, self.config)


class StructuredChunker(Chunker):
    """Recursive text split: paragraph → sentence → word. No heading detection.

    Same fallback logic as HtmlAwareChunker._recursive_split, but applied
    directly to the full text without the heading pre-pass.
    """

    def __init__(self, config: ChunkerConfig) -> None:
        self.config = config

    def chunk_document(self, doc: dict) -> list[Chunk]:
        url: str = doc.get("url", "")
        title: str = doc.get("title", "")
        section: str = doc.get("section", "")
        text: str = (doc.get("text") or doc.get("full_text") or "").strip()

        if not text:
            return []

        doc_id = _make_doc_id(url, section)

        if _approx_tokens(text) <= self.config.max_tokens:
            if _approx_tokens(text) >= self.config.min_tokens:
                return [_make_chunk(text, url, title, section, doc_id)]
            return []

        sub_texts = self._recursive_split(text)
        chunks: list[Chunk] = []
        for i, sub_text in enumerate(sub_texts):
            chunk_section = f"{section}#{i}" if len(sub_texts) > 1 else section
            chunk_doc_id = _make_doc_id(url, chunk_section)
            chunks.append(_make_chunk(sub_text, url, title, chunk_section, chunk_doc_id))
        return chunks

    def _recursive_split(self, text: str) -> list[str]:
        return _recursive_split(text, self.config)


class AdjacencyChunker(Chunker):
    """Fixed splits with positional chunk IDs enabling neighbor lookup at query time.

    chunk_id format: {doc_id}_chunk{i}

    After calling chunk_document(), call neighbors(chunk_id) to get the
    (prev_chunk_id, next_chunk_id) pair for context-window expansion.
    """

    def __init__(self, config: ChunkerConfig) -> None:
        self.config = config
        self._last_doc_id: str = ""
        self._last_count: int = 0

    def chunk_document(self, doc: dict) -> list[Chunk]:
        url: str = doc.get("url", "")
        title: str = doc.get("title", "")
        section: str = doc.get("section", "")
        text: str = (doc.get("text") or doc.get("full_text") or "").strip()

        if not text:
            self._last_doc_id = ""
            self._last_count = 0
            return []

        doc_id = _make_doc_id(url, section)
        words = text.split()
        step = max(1, int(self.config.max_tokens * _WORDS_PER_TOKEN))
        min_t = self.config.min_tokens

        chunks: list[Chunk] = []
        i = 0
        while i < len(words):
            window = words[i : i + step]
            chunk_text = " ".join(window)
            if _approx_tokens(chunk_text) >= min_t:
                idx = len(chunks)
                chunk_section = f"{section}_chunk{idx}"
                chunk_doc_id = _make_doc_id(url, chunk_section)
                chunks.append(
                    Chunk(
                        id=f"{doc_id}_chunk{idx}",
                        text=chunk_text,
                        metadata=ChunkMetadata(
                            url=url,
                            title=title,
                            section=chunk_section,
                            doc_id=chunk_doc_id,
                        ),
                    )
                )
            i += step

        self._last_doc_id = doc_id
        self._last_count = len(chunks)
        return chunks

    def neighbors(self, chunk_id: str) -> tuple[str | None, str | None]:
        """Return (prev_chunk_id, next_chunk_id) for the given chunk_id.

        chunk_id must follow the format produced by chunk_document: {doc_id}_chunk{i}.
        Raises RuntimeError if chunk_document has not been called yet.
        Raises ValueError if chunk_id format is invalid.
        """
        if self._last_count == 0:
            raise RuntimeError("Call chunk_document() before calling neighbors().")

        try:
            base_id, idx_str = chunk_id.rsplit("_chunk", 1)
            idx = int(idx_str)
        except ValueError as exc:
            raise ValueError(f"Bad chunk_id format: {chunk_id!r}") from exc

        prev_id = f"{base_id}_chunk{idx - 1}" if idx > 0 else None
        next_id = f"{base_id}_chunk{idx + 1}" if (idx + 1) < self._last_count else None
        return prev_id, next_id


class ParentDocChunker(Chunker):
    """Two-level chunking: small child chunks for indexing, full sections as parents.

    chunk_document() returns child chunks only — these get embedded and indexed.
    Each child chunk's metadata.parent_id points to the parent section's doc_id.

    get_parent(parent_id) returns the full parent text for context at retrieval time.

    child_chunk_size: token budget for indexed chunks (default 128)
    max_tokens in config: token budget for parent sections (default 512)
    """

    def __init__(self, config: ChunkerConfig, child_chunk_size: int = 128) -> None:
        self.config = config
        self.child_chunk_size = child_chunk_size
        self._parents: dict[str, str] = {}  # parent_id -> full section text

    def chunk_document(self, doc: dict) -> list[Chunk]:
        url: str = doc.get("url", "")
        title: str = doc.get("title", "")
        section: str = doc.get("section", "")
        text: str = (doc.get("text") or doc.get("full_text") or "").strip()

        if not text:
            return []

        parent_sections = self._split_sections(text)
        child_chunks: list[Chunk] = []

        for sec_title, sec_text in parent_sections:
            sec_text = sec_text.strip()
            if not sec_text:
                continue

            sub_section = f"{section}/{sec_title}".strip("/") if sec_title else section
            parent_id = _make_doc_id(url, sub_section)
            self._parents[parent_id] = sec_text

            children = self._split_into_children(sec_text, url, title, sub_section, parent_id)
            child_chunks.extend(children)

        return child_chunks

    def get_parent(self, parent_id: str) -> str | None:
        """Return the full parent section text for the given parent_id."""
        return self._parents.get(parent_id)

    def _split_sections(self, text: str) -> list[tuple[str, str]]:
        heading_re = re.compile(r"^(#{1,3}\s+.+|[A-Z][A-Z0-9 :/-]{2,60})$", re.MULTILINE)
        positions = [m.start() for m in heading_re.finditer(text)]

        if not positions:
            return [("", text)]

        sections: list[tuple[str, str]] = []
        if positions[0] > 0:
            sections.append(("", text[: positions[0]]))

        for i, pos in enumerate(positions):
            end = positions[i + 1] if i + 1 < len(positions) else len(text)
            line_end = text.index("\n", pos) if "\n" in text[pos:end] else end
            heading = text[pos:line_end].strip().lstrip("#").strip()
            body = text[line_end:end].strip()
            sections.append((heading, body))

        return sections

    def _split_into_children(
        self,
        text: str,
        url: str,
        title: str,
        section: str,
        parent_id: str,
    ) -> list[Chunk]:
        """Split parent text into child chunks of child_chunk_size tokens."""
        words = text.split()
        step = max(1, int(self.child_chunk_size * _WORDS_PER_TOKEN))
        min_t = self.config.min_tokens

        chunks: list[Chunk] = []
        i = 0
        while i < len(words):
            window = words[i : i + step]
            chunk_text = " ".join(window)
            if _approx_tokens(chunk_text) >= min_t:
                idx = len(chunks)
                chunk_section = f"{section}#child{idx}"
                chunk_doc_id = _make_doc_id(url, chunk_section)
                chunk_id = hashlib.sha256(
                    f"{parent_id}:child{idx}:{chunk_text[:64]}".encode()
                ).hexdigest()[:20]
                chunks.append(
                    Chunk(
                        id=chunk_id,
                        text=chunk_text,
                        metadata=ChunkMetadata(
                            url=url,
                            title=title,
                            section=chunk_section,
                            doc_id=chunk_doc_id,
                            parent_id=parent_id,
                        ),
                    )
                )
            i += step

        # Fallback: if parent fits in child_chunk_size, return as single child
        if not chunks and _approx_tokens(text) >= min_t:
            chunk_id = hashlib.sha256(f"{parent_id}:child0:{text[:64]}".encode()).hexdigest()[:20]
            chunks.append(
                Chunk(
                    id=chunk_id,
                    text=text,
                    metadata=ChunkMetadata(
                        url=url,
                        title=title,
                        section=f"{section}#child0",
                        doc_id=_make_doc_id(url, f"{section}#child0"),
                        parent_id=parent_id,
                    ),
                )
            )

        return chunks


# ---------------------------------------------------------------------------
# Shared split helpers (used by FixedChunker and OverlappingChunker)
# ---------------------------------------------------------------------------


def _fixed_split(
    text: str,
    url: str,
    title: str,
    section: str,
    doc_id: str,
    config: ChunkerConfig,
) -> list[Chunk]:
    """Split by word count with no overlap."""
    words = text.split()
    step = max(1, int(config.max_tokens * _WORDS_PER_TOKEN))
    min_t = config.min_tokens

    chunks: list[Chunk] = []
    for i in range(0, len(words), step):
        window = words[i : i + step]
        chunk_text = " ".join(window)
        if _approx_tokens(chunk_text) >= min_t:
            chunk_section = (
                f"{section}#{len(chunks)}" if chunks or i + step < len(words) else section
            )
            chunk_doc_id = _make_doc_id(url, chunk_section)
            chunks.append(_make_chunk(chunk_text, url, title, chunk_section, chunk_doc_id))

    return chunks if chunks else [_make_chunk(text, url, title, section, doc_id)]


def _overlapping_split(
    text: str,
    url: str,
    title: str,
    section: str,
    doc_id: str,
    config: ChunkerConfig,
) -> list[Chunk]:
    """Split by word count with overlap_tokens overlap between adjacent chunks."""
    words = text.split()
    step = max(1, int(config.max_tokens * _WORDS_PER_TOKEN))
    overlap_w = int(config.overlap_tokens * _WORDS_PER_TOKEN)
    min_t = config.min_tokens

    chunks: list[Chunk] = []
    i = 0
    while i < len(words):
        window = words[i : i + step]
        chunk_text = " ".join(window)
        if _approx_tokens(chunk_text) >= min_t:
            chunk_section = f"{section}#{len(chunks)}"
            chunk_doc_id = _make_doc_id(url, chunk_section)
            chunks.append(_make_chunk(chunk_text, url, title, chunk_section, chunk_doc_id))
        i += max(1, step - overlap_w)

    return chunks if chunks else [_make_chunk(text, url, title, section, doc_id)]
