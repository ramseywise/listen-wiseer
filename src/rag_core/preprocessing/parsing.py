"""Document parsing, cleaning, and deduplication for RAG preprocessing."""

import hashlib
import re
from typing import Any

from utils.logging import get_logger

logger = get_logger(__name__)


# =============================================================================
# TEXT CLEANING
# =============================================================================


def clean_text(text: str) -> str:
    """Clean text by removing noise and normalizing whitespace.

    Args:
        text: Raw input text

    Returns:
        Cleaned text

    """
    if not text:
        return ""

    # Normalize whitespace
    text = re.sub(r"\s+", " ", text)

    # Remove excessive newlines
    text = re.sub(r"\n{3,}", "\n\n", text)

    # Remove common email signatures/noise
    noise_patterns = [
        r"Sent from my iPhone",
        r"Отправлено с iPhone",
        r"Envoyé de mon iPhone",
        r"Von meinem iPhone gesendet",
        r"Get Outlook for .*",
        r"--\s*\n.*$",  # Email signature separator
    ]
    for pattern in noise_patterns:
        text = re.sub(pattern, "", text, flags=re.IGNORECASE | re.MULTILINE)

    return text.strip()


def normalize_german_text(text: str) -> str:
    """Normalize German-specific text patterns.

    Args:
        text: Input text

    Returns:
        Normalized text

    """
    if not text:
        return ""

    # Normalize umlauts (optional - for search matching)
    # text = text.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue")

    # Normalize common terms
    text = re.sub(r"sev\s*desk", "sevdesk", text, flags=re.IGNORECASE)
    text = re.sub(r"sev\s*Desk", "sevDesk", text)

    return text


def remove_boilerplate(text: str, patterns: list[str] | None = None) -> str:
    """Remove boilerplate content from documents.

    Args:
        text: Input text
        patterns: Optional custom patterns to remove

    Returns:
        Text with boilerplate removed

    """
    if not text:
        return ""

    default_patterns = [
        r"Cookie-Einstellungen",
        r"Datenschutzerklärung",
        r"Impressum",
        r"© \d{4}.*$",
        r"Alle Rechte vorbehalten",
    ]

    all_patterns = (patterns or []) + default_patterns

    for pattern in all_patterns:
        text = re.sub(pattern, "", text, flags=re.IGNORECASE | re.MULTILINE)

    return text.strip()


# =============================================================================
# LANGUAGE DETECTION
# =============================================================================


def detect_language(text: str) -> dict[str, Any]:
    """Detect language and non-German content.

    Args:
        text: Input text

    Returns:
        Language detection results

    """
    if not text or len(text.strip()) < 10:
        return {"language": "unknown", "confidence": 0.0, "issues": ["too_short"]}

    issues = []

    # Check for Cyrillic (Russian, etc.)
    if re.search(r"[\u0400-\u04FF]", text):
        issues.append("cyrillic")

    # Check for Chinese/Japanese/Korean
    if re.search(r"[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]", text):
        issues.append("cjk")

    # Check for Arabic
    if re.search(r"[\u0600-\u06FF]", text):
        issues.append("arabic")

    # German indicators
    german_indicators = ["ä", "ö", "ü", "ß", "und", "die", "der", "das", "ist", "nicht"]
    german_count = sum(1 for ind in german_indicators if ind.lower() in text.lower())

    if issues:
        return {"language": "non_german", "confidence": 0.9, "issues": issues}
    elif german_count >= 3:
        return {"language": "german", "confidence": 0.8, "issues": []}
    else:
        return {"language": "uncertain", "confidence": 0.5, "issues": []}


def filter_non_german(documents: list[dict], text_field: str = "text") -> list[dict]:
    """Filter out non-German documents.

    Args:
        documents: List of document dictionaries
        text_field: Field name containing text

    Returns:
        Filtered list of German documents

    """
    german_docs = []
    filtered_count = 0

    for doc in documents:
        text = doc.get(text_field) or doc.get("Text") or doc.get("content", "")
        lang = detect_language(text)

        if lang["language"] in ["german", "uncertain"]:
            german_docs.append(doc)
        else:
            filtered_count += 1

    logger.info(f"Filtered {filtered_count} non-German documents, kept {len(german_docs)}")
    return german_docs


# =============================================================================
# DEDUPLICATION
# =============================================================================


def compute_text_hash(text: str, normalize: bool = True) -> str:
    """Compute hash for text deduplication.

    Args:
        text: Input text
        normalize: Whether to normalize before hashing

    Returns:
        MD5 hash of text

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
    """Remove exact duplicate documents.

    Args:
        documents: List of document dictionaries
        text_field: Field name containing text
        keep: Which duplicate to keep ('first' or 'last')

    Returns:
        Deduplicated document list

    """
    seen_hashes: set[str] = set()
    unique_docs = []
    duplicate_count = 0

    docs_to_process = documents if keep == "first" else list(reversed(documents))

    for doc in docs_to_process:
        text = doc.get(text_field) or doc.get("Text") or doc.get("content", "")
        text_hash = compute_text_hash(text)

        if text_hash not in seen_hashes:
            seen_hashes.add(text_hash)
            unique_docs.append(doc)
        else:
            duplicate_count += 1

    result = unique_docs if keep == "first" else list(reversed(unique_docs))
    logger.info(f"Removed {duplicate_count} exact duplicates, kept {len(result)}")
    return result


def deduplicate_fuzzy(
    documents: list[dict],
    embedder,
    text_field: str = "text",
    threshold: float = 0.95,
) -> list[dict]:
    """Remove near-duplicate documents using embedding similarity.

    Args:
        documents: List of document dictionaries
        embedder: Function to create embeddings
        text_field: Field name containing text
        threshold: Similarity threshold for duplicates

    Returns:
        Deduplicated document list

    """
    from sklearn.metrics.pairwise import cosine_similarity

    texts = [doc.get(text_field) or doc.get("Text") or doc.get("content", "") for doc in documents]

    # Embed all texts
    embeddings = embedder([t[:500] for t in texts])  # Truncate for speed

    # Find duplicates
    sim_matrix = cosine_similarity(embeddings)
    to_remove = set()

    for i in range(len(sim_matrix)):
        if i in to_remove:
            continue
        for j in range(i + 1, len(sim_matrix)):
            if sim_matrix[i, j] >= threshold:
                to_remove.add(j)  # Keep earlier document

    unique_docs = [doc for i, doc in enumerate(documents) if i not in to_remove]
    logger.info(f"Removed {len(to_remove)} fuzzy duplicates, kept {len(unique_docs)}")
    return unique_docs


# =============================================================================
# DOCUMENT ENRICHMENT
# =============================================================================


def extract_metadata(text: str, url: str | None = None) -> dict[str, Any]:
    """Extract metadata from document text.

    Args:
        text: Document text
        url: Optional source URL

    Returns:
        Extracted metadata

    """
    metadata = {}

    # Extract category from URL if available
    if url:
        if "hilfe.sevdesk" in url:
            metadata["source"] = "help_center"
        elif "blog.sevdesk" in url:
            metadata["source"] = "blog"
        elif "api.sevdesk" in url:
            metadata["source"] = "api_docs"

        # Extract article ID from URL
        id_match = re.search(r"/articles/(\d+)", url)
        if id_match:
            metadata["article_id"] = id_match.group(1)

    # Detect document type from content
    if "Schritt 1" in text or "Anleitung" in text.lower():
        metadata["type"] = "procedural"
    elif "FAQ" in text or "?" in text[:100]:
        metadata["type"] = "faq"
    else:
        metadata["type"] = "informational"

    # Word count
    metadata["word_count"] = len(text.split())
    metadata["char_count"] = len(text)

    return metadata


def enrich_documents(documents: list[dict], text_field: str = "text") -> list[dict]:
    """Enrich documents with extracted metadata.

    Args:
        documents: List of document dictionaries
        text_field: Field name containing text

    Returns:
        Enriched documents

    """
    enriched = []

    for doc in documents:
        text = doc.get(text_field) or doc.get("Text") or doc.get("content", "")
        url = doc.get("url") or doc.get("URL", "")

        metadata = extract_metadata(text, url)

        enriched_doc = {**doc, **metadata}
        enriched.append(enriched_doc)

    logger.info(f"Enriched {len(enriched)} documents with metadata")
    return enriched


# =============================================================================
# FULL PREPROCESSING PIPELINE
# =============================================================================


def preprocess_corpus(
    documents: list[dict],
    text_field: str = "text",
    clean: bool = True,
    filter_language: bool = True,
    deduplicate: bool = True,
    enrich: bool = True,
) -> list[dict]:
    """Run full preprocessing pipeline on corpus.

    Args:
        documents: Raw documents
        text_field: Field name containing text
        clean: Whether to clean text
        filter_language: Whether to filter non-German
        deduplicate: Whether to remove duplicates
        enrich: Whether to add metadata

    Returns:
        Preprocessed documents

    """
    logger.info(f"Starting preprocessing of {len(documents)} documents")

    result = documents

    # Clean text
    if clean:
        for doc in result:
            text = doc.get(text_field) or doc.get("Text") or doc.get("content", "")
            cleaned = clean_text(text)
            cleaned = remove_boilerplate(cleaned)
            doc[text_field] = cleaned

    # Filter non-German
    if filter_language:
        result = filter_non_german(result, text_field)

    # Deduplicate
    if deduplicate:
        result = deduplicate_exact(result, text_field)

    # Enrich with metadata
    if enrich:
        result = enrich_documents(result, text_field)

    logger.info(f"Preprocessing complete: {len(documents)} → {len(result)} documents")
    return result
