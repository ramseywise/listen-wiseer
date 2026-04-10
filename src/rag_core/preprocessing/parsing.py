"""Document parsing, cleaning, and deduplication for RAG preprocessing."""

from __future__ import annotations

import hashlib
import re
from typing import Any

from utils.logging import get_logger

logger = get_logger(__name__)


# =============================================================================
# TEXT CLEANING
# =============================================================================


def clean_text(text: str) -> str:
    """Normalize whitespace and strip common noise patterns."""
    if not text:
        return ""

    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)

    noise_patterns = [
        r"Sent from my iPhone",
        r"Get Outlook for .*",
        r"--\s*\n.*$",
    ]
    for pattern in noise_patterns:
        text = re.sub(pattern, "", text, flags=re.IGNORECASE | re.MULTILINE)

    return text.strip()


def remove_boilerplate(text: str, patterns: list[str] | None = None) -> str:
    """Remove boilerplate content using caller-supplied patterns.

    Args:
        text: Input text.
        patterns: Optional list of regex patterns to strip.

    Returns:
        Text with matched patterns removed.
    """
    if not text:
        return ""

    for pattern in patterns or []:
        text = re.sub(pattern, "", text, flags=re.IGNORECASE | re.MULTILINE)

    return text.strip()


# =============================================================================
# DEDUPLICATION
# =============================================================================


def compute_text_hash(text: str, normalize: bool = True) -> str:
    """Compute MD5 hash for exact deduplication.

    Args:
        text: Input text.
        normalize: Lowercase + collapse whitespace before hashing.

    Returns:
        Hex digest string.
    """
    if normalize:
        text = text.lower().strip()
        text = re.sub(r"\s+", " ", text)
    return hashlib.md5(text.encode(), usedforsecurity=False).hexdigest()


def deduplicate_exact(
    documents: list[dict],
    text_field: str = "text",
    keep: str = "first",
) -> list[dict]:
    """Remove exact-duplicate documents by text hash.

    Args:
        documents: List of document dicts.
        text_field: Key containing the document text.
        keep: Which duplicate to keep — ``'first'`` or ``'last'``.

    Returns:
        Deduplicated list in original order.
    """
    seen_hashes: set[str] = set()
    unique_docs: list[dict] = []
    duplicate_count = 0

    docs_to_process = documents if keep == "first" else list(reversed(documents))

    for doc in docs_to_process:
        text = doc.get(text_field) or doc.get("content", "")
        text_hash = compute_text_hash(text)

        if text_hash not in seen_hashes:
            seen_hashes.add(text_hash)
            unique_docs.append(doc)
        else:
            duplicate_count += 1

    result = unique_docs if keep == "first" else list(reversed(unique_docs))
    logger.info("parsing.dedup.exact.done", removed=duplicate_count, kept=len(result))
    return result


def deduplicate_fuzzy(
    documents: list[dict],
    embedder: Any,
    text_field: str = "text",
    threshold: float = 0.95,
) -> list[dict]:
    """Remove near-duplicate documents using embedding cosine similarity.

    Args:
        documents: List of document dicts.
        embedder: Callable that returns a list of float vectors.
        text_field: Key containing the document text.
        threshold: Cosine similarity above which two docs are considered duplicates.

    Returns:
        Deduplicated list (earlier document kept).
    """
    from sklearn.metrics.pairwise import cosine_similarity

    texts = [doc.get(text_field) or doc.get("content", "") for doc in documents]
    embeddings = embedder([t[:500] for t in texts])
    sim_matrix = cosine_similarity(embeddings)
    to_remove: set[int] = set()

    for i in range(len(sim_matrix)):
        if i in to_remove:
            continue
        for j in range(i + 1, len(sim_matrix)):
            if sim_matrix[i, j] >= threshold:
                to_remove.add(j)

    unique_docs = [doc for i, doc in enumerate(documents) if i not in to_remove]
    logger.info("parsing.dedup.fuzzy.done", removed=len(to_remove), kept=len(unique_docs))
    return unique_docs


# =============================================================================
# DOCUMENT ENRICHMENT
# =============================================================================


def extract_metadata(text: str, url: str | None = None) -> dict[str, Any]:
    """Extract lightweight metadata from document text and URL.

    Args:
        text: Document text.
        url: Optional source URL used to infer content category.

    Returns:
        Dict with ``word_count``, ``char_count``, and optional ``type``.
    """
    metadata: dict[str, Any] = {
        "word_count": len(text.split()),
        "char_count": len(text),
    }

    if "?" in text[:100]:
        metadata["type"] = "faq"
    else:
        metadata["type"] = "informational"

    return metadata


def enrich_documents(documents: list[dict], text_field: str = "text") -> list[dict]:
    """Attach extracted metadata to each document dict in-place.

    Args:
        documents: List of document dicts.
        text_field: Key containing the document text.

    Returns:
        Enriched list (same objects, extra keys merged in).
    """
    enriched = []
    for doc in documents:
        text = doc.get(text_field) or doc.get("content", "")
        url = doc.get("url", "")
        metadata = extract_metadata(text, url)
        enriched.append({**doc, **metadata})

    logger.info("parsing.enrich.done", count=len(enriched))
    return enriched


# =============================================================================
# FULL PREPROCESSING PIPELINE
# =============================================================================


def preprocess_corpus(
    documents: list[dict],
    text_field: str = "text",
    clean: bool = True,
    deduplicate: bool = True,
    enrich: bool = True,
    boilerplate_patterns: list[str] | None = None,
) -> list[dict]:
    """Run full preprocessing pipeline on a document corpus.

    Language-agnostic: no language filtering is applied.  Pass
    ``boilerplate_patterns`` to strip domain-specific noise.

    Args:
        documents: Raw document dicts.
        text_field: Key containing raw text.
        clean: Whether to normalize whitespace and strip noise.
        deduplicate: Whether to remove exact duplicates.
        enrich: Whether to attach word/char count metadata.
        boilerplate_patterns: Optional list of regex patterns to strip.

    Returns:
        Preprocessed document list.
    """
    logger.info("parsing.preprocess.start", n_docs=len(documents))
    result = documents

    if clean:
        for doc in result:
            text = doc.get(text_field) or doc.get("content", "")
            cleaned = clean_text(text)
            cleaned = remove_boilerplate(cleaned, boilerplate_patterns)
            doc[text_field] = cleaned

    if deduplicate:
        result = deduplicate_exact(result, text_field)

    if enrich:
        result = enrich_documents(result, text_field)

    logger.info("parsing.preprocess.done", n_in=len(documents), n_out=len(result))
    return result
