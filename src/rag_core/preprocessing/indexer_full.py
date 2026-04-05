"""Indexer for the RAG system."""

import re
from typing import Any, cast

from bs4 import BeautifulSoup
from elasticsearch import Elasticsearch
from opensearchpy import OpenSearch

from src.datastore.embedding_store import (
    EmbeddingStore,
)
from src.datastore.metadata_store import (
    MetadataStore,
)
from src.preprocessing.chunker_full import (
    Chunker,
    HtmlChunker,
)
from src.retriever.dense_retriever import (
    DenseRetriever,
)
from src.retriever.sparse_retriever import (
    SparseRetriever,
)
from utils.logging import get_logger

logger = get_logger(__name__)


class ChunkIndexer:
    """Index chunks for vector DB.

    Responsible for:
    1) Pulling full HTML from a MetadataStore,
    2) Splitting into chunks via HtmlChunker,
    3) Embedding each chunk with both a BM25 sparse_vector and a SentenceTransformer dense_vector,
    4) Writing each chunk into EmbeddingStore under `index_name` with the fields:
       - sparse_embedding (type: sparse_vector)
       - dense_embedding  (type: dense_vector)
       - page_title       (type: text)
       - software_version (type: integer)
       - doc_id           (type: keyword)
       - url              (type: text).
    """

    def __init__(
        self,
        metadata_store: MetadataStore,
        embedding_store: EmbeddingStore,
        index: str,
        chunker: Chunker,
        db_client: Elasticsearch | OpenSearch | None = None,
        dense_retriever: DenseRetriever | None = None,
        sparse_retriever: SparseRetriever | None = None,
        tokenizer_language: str = "german",
    ):
        """Initialize the ChunkIndexer."""
        self.metadata_store = metadata_store
        self.embedding_store = embedding_store
        self.index = index
        self.chunker = chunker
        self.dense_retriever = dense_retriever
        self.sparse_retriever = sparse_retriever
        self.tokenizer_language = tokenizer_language
        self.db = db_client

    def _extract_metadata(
        self, doc_id: str, meta: dict, ver_rx: re.Pattern, title_rx: re.Pattern
    ) -> tuple[str, str, int | None, bool]:
        """Extract page_title, content, version, and already_chunked flag from document metadata."""
        full_html = meta.get("Text", "")
        logger.debug(f"Doc={doc_id} raw text: {full_html[:200]}...")

        mver = ver_rx.search(full_html)
        version = int(mver.group(1)) if mver else None
        page_title = ""
        already_chunked = False

        source = meta.get("source_type", "")
        if source == "faq":
            page_title = meta["page_title"]
            full_html = meta["body_text"]
        elif source == "help":
            mtit = title_rx.search(full_html)
            page_title = mtit.group(1).strip() if mtit else ""
        elif source == "atlassian" and isinstance(self.chunker, AtlassianChunker):
            page_title, full_html = self._process_atlassian_doc(full_html)
            already_chunked = self._check_atlassian_structure(full_html)
            if already_chunked:
                full_html = self._format_atlassian_chunks(full_html)
        elif source == "blog" and isinstance(self.chunker, BlogChunker):
            page_title, full_html = self.chunker.split_title_and_body(full_html)
        else:
            logger.error(f"[ChunkIndexer] Doc {doc_id}: missing/invalid source_type")

        logger.debug(
            f"Doc={doc_id}: title='{page_title[:50] if page_title else 'N/A'}', v={version or 'N/A'}"
        )
        return page_title, full_html, version, already_chunked

    def _process_atlassian_doc(self, full_html: str) -> tuple[str, str]:
        """Process Atlassian document: extract title and clean body text."""
        # Called only when isinstance(self.chunker, AtlassianChunker) - safe to cast
        chunker = cast(AtlassianChunker, self.chunker)
        page_title, body = chunker.split_title_and_body(full_html)
        body = re.sub(r'data-loadable-(?:begin|end)="[^"]*"\s*', "", body)
        body = BeautifulSoup(body, "html.parser").get_text("\n", strip=True)
        return page_title, body

    def _check_atlassian_structure(self, full_html: str) -> bool:
        """Check if Atlassian doc has Voraussetzung/Anweisungen structure."""
        pattern = re.compile(
            r"Voraussetzung[:\s\-–]*\n*(?P<v>.*?)\n*(?:Anweisungen|Anweisung)[:\s\-–]*\n*(?P<a>.*)",
            flags=re.IGNORECASE | re.DOTALL,
        )
        return bool(pattern.search(full_html))

    def _format_atlassian_chunks(self, full_html: str) -> str:
        """Format Atlassian doc with Voraussetzung/Anweisungen structure."""
        pattern = re.compile(
            r"Voraussetzung[:\s\-–]*\n*(?P<v>.*?)\n*(?:Anweisungen|Anweisung)[:\s\-–]*\n*(?P<a>.*)",
            flags=re.IGNORECASE | re.DOTALL,
        )
        m = pattern.search(full_html)
        if m:
            v = m.group("v").strip()
            a = m.group("a").strip()
            return f"Voraussetzung:\n{v}\n\nAnweisungen:\n{a}"
        return full_html

    def _add_embeddings(self, chunk_id: str, chunk: str, body: dict[str, Any]) -> None:
        """Add sparse and dense embeddings to the chunk body."""
        if self.sparse_retriever and hasattr(self.sparse_retriever, "encode"):
            try:
                body["sparse_embedding"] = self.sparse_retriever.encode(chunk)
            except Exception as e:
                logger.error(f"[ChunkIndexer] Sparse embedding failed for '{chunk_id}': {e}")

        if self.dense_retriever and hasattr(self.dense_retriever, "encode"):
            try:
                body["dense_embedding"] = self.dense_retriever.encode(chunk)
            except Exception as e:
                logger.error(f"[ChunkIndexer] Dense embedding failed for '{chunk_id}': {e}")

    def _index_chunk(self, chunk_id: str, body: dict[str, Any]) -> bool:
        """Index a single chunk. Returns True if successful."""
        try:
            if self.db is None:
                logger.warning(f"[ChunkIndexer] Skipped indexing {chunk_id}: db_client is None!")
            else:
                self.embedding_store.add([chunk_id], [body])
            return True
        except Exception as e:
            logger.error(f"[ChunkIndexer] Failed to index chunk '{chunk_id}': {e}")
            return False

    def run(self, source_type: str | None = None) -> None:
        """Run the ChunkIndexer."""
        docs = (
            self.metadata_store.get_documents_by_source(source_type)
            if source_type
            else self.metadata_store.get_all_documents()
        )

        # Precompile metadata extraction regexes
        ver_rx = re.compile(r"Softwareversion\s*([12])", re.IGNORECASE)
        title_rx = re.compile(r"<header[^>]*>(.*?)</header>", re.DOTALL | re.IGNORECASE)

        for doc_id, meta in docs.items():
            page_title, full_html, version, already_chunked = self._extract_metadata(
                doc_id, meta, ver_rx, title_rx
            )

            logger.debug(f"[ChunkIndexer] Doc={doc_id}: HTML len={len(full_html)}")

            chunks = [full_html] if already_chunked else self.chunker.chunk(full_html)
            if not chunks:
                logger.warning(f"[ChunkIndexer] No chunks for doc '{doc_id}', skipping")
                continue

            indexed, skipped = 0, 0
            url = meta.get("URL", "")

            for i, chunk in enumerate(chunks):
                chunk_id = f"{doc_id}_chunk{i}"
                body: dict[str, Any] = {
                    "content": chunk,
                    "page_title": page_title,
                    "software_version": version,
                    "url": url,
                    "is_snippet": (meta.get("source_type") == "snippet"),
                }

                self._add_embeddings(chunk_id, chunk, body)

                if self._index_chunk(chunk_id, body):
                    indexed += 1
                else:
                    skipped += 1

            logger.info(f"[ChunkIndexer] Indexed {indexed} chunks for {doc_id}")


class AtlassianChunker(HtmlChunker):
    """Class for Atlassian chunker.

    Atlassian chunker:
    - Grabs <div class="doc-title"> for the page_title
    - Grabs <div class="doc-body"> as the HTML to chunk
    - Splits on <h2> headings (which your sample uses).
    """

    def __init__(self):
        """Initialize the AtlassianChunker."""
        super().__init__(
            headers_to_split_on=[],
            denylist_tags=None,
        )

    def split_title_and_body(self, full_html: str) -> tuple[str, str]:
        """Split the title and body of the Atlassian document."""
        soup = BeautifulSoup(full_html, "html.parser")
        # extract title
        title_el = soup.select_one("div.doc-title")
        title = title_el.get_text(" ", strip=True) if title_el else ""
        # extract body HTML
        body_el = soup.select_one("div.doc-body")
        body_html = body_el.decode_contents() if body_el else full_html

        return title, body_html


class BlogChunker(HtmlChunker):
    """Class for Blog chunker."""

    def __init__(self):
        """Initialize the BlogChunker."""
        super().__init__(
            headers_to_split_on=[("h2", "section"), ("h3", "subsection")],
            max_chunk_size=2000,
            allowlist_tags=["h2", "h3"],
            denylist_tags=None,
        )

    def split_title_and_body(self, full_html: str) -> tuple[str, str]:
        """Split the title and body of the Blog document."""
        soup = BeautifulSoup(full_html, "html.parser")
        article = soup.select_one("article.c-layout")

        # 1) extract the <h1> title
        if article:
            h1 = article.select_one("div.cc-article_2col-heading h1")
            title = h1.get_text(" ", strip=True) if h1 else ""
        else:
            title = ""

        # 2) extract intro + rich-text sections
        parts = []
        selectors = [
            "div.c-rt[schema-field='article-intro']",
            "div.c-rt[schema-field='article-rich-text']",
        ]
        for sel in selectors:
            # always define el, even if article is None
            el = article.select_one(sel) if article else None
            if el:
                parts.append(el.decode_contents())

        # if we found any parts, join them; otherwise fall back to full_html
        body_html = "\n".join(parts) if parts else full_html
        return title, body_html


def build_indexers_for_sources(
    metadata_store: MetadataStore,
    embedding_store: EmbeddingStore,
    db_client: Elasticsearch | OpenSearch,
    index: str,
    dense_retriever: DenseRetriever,
    sparse_retriever: SparseRetriever | None = None,
) -> dict[str, ChunkIndexer]:
    """Create one ChunkIndexer per source_type: 'help', 'atlassian', 'faq'.

    - Help pages and Atlassian docs use HtmlChunker with different header/tag rules.
    - FAQ docs are pre-loaded so that meta['Text'] == "Question: ... Answer: ..."
      and we just wrap that into a single chunk.
    """
    # 1) Help pages
    help_chunker = HtmlChunker(
        headers_to_split_on=[("h1", "section"), ("h2", "subsection")],
        max_chunk_size=2000,
        denylist_tags=["header"],
    )
    help_indexer = ChunkIndexer(
        metadata_store=metadata_store,
        embedding_store=embedding_store,
        db_client=db_client,
        index=index,
        chunker=help_chunker,
        dense_retriever=dense_retriever,
        sparse_retriever=sparse_retriever,
    )

    # 2) Atlassian docs
    atlassian_chunker = AtlassianChunker()

    atlassian_indexer = ChunkIndexer(
        metadata_store=metadata_store,
        embedding_store=embedding_store,
        db_client=db_client,
        index=index,
        chunker=atlassian_chunker,
        dense_retriever=dense_retriever,
        sparse_retriever=sparse_retriever,
    )

    # 3) Blog posts
    blog_chunker = BlogChunker()
    blog_indexer = ChunkIndexer(
        metadata_store=metadata_store,
        embedding_store=embedding_store,
        db_client=db_client,
        index=index,
        chunker=blog_chunker,
        dense_retriever=dense_retriever,
        sparse_retriever=sparse_retriever,
    )

    # 3) FAQ docs (assuming loaded meta['Text'] = "Question: ... Answer: ...")
    class FAQChunker(Chunker):
        def chunk(self, text: str) -> list[str]:
            # text here is already "Question: ... Answer: ..."
            return [text]

    faq_chunker = FAQChunker()
    faq_indexer = ChunkIndexer(
        metadata_store=metadata_store,
        embedding_store=embedding_store,
        db_client=db_client,
        index=index,
        chunker=faq_chunker,
        dense_retriever=dense_retriever,
        sparse_retriever=None,  # typically no sparse embedding for FAQ
    )

    # 4) Snippets (similar to FAQs)
    class SnippetChunker(Chunker):
        def chunk(self, text: str) -> list[str]:
            return [text]

    snippet_chunker = SnippetChunker()
    snippet_indexer = ChunkIndexer(
        metadata_store=metadata_store,
        embedding_store=embedding_store,
        db_client=db_client,
        index=index,
        chunker=snippet_chunker,
        dense_retriever=dense_retriever,
        sparse_retriever=None,
    )

    return {
        "help": help_indexer,
        "atlassian": atlassian_indexer,
        "blog": blog_indexer,
        "faq": faq_indexer,
        "snippet": snippet_indexer,
    }
