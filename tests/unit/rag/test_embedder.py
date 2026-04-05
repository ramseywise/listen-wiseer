from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parents[2] / "src"))


def _make_embedder(dim: int = 1024):
    """Return a MultilingualEmbedder with SentenceTransformer mocked out."""
    import numpy as np
    from retrieval.embedder import EmbedderSettings, MultilingualEmbedder

    with patch("retrieval.embedder.SentenceTransformer") as mock_cls:
        mock_model = MagicMock()
        mock_cls.return_value = mock_model

        # encode returns a 2-D array for batch, 1-D for single string
        def fake_encode(input_, convert_to_numpy=True):
            if isinstance(input_, list):
                return np.zeros((len(input_), dim), dtype="float32")
            return np.zeros(dim, dtype="float32")

        mock_model.encode.side_effect = fake_encode

        embedder = MultilingualEmbedder(EmbedderSettings(model="mock-model"))
        embedder.model = mock_model  # keep reference for assertions
        return embedder, mock_model


# ---------------------------------------------------------------------------
# embed_passages — prefix and shape
# ---------------------------------------------------------------------------


def test_embed_passages_applies_passage_prefix():
    embedder, mock_model = _make_embedder()
    texts = ["How to reset your password.", "Export your data in CSV format."]
    embedder.embed_passages(texts)

    call_args = mock_model.encode.call_args
    sent_input = call_args.args[0] if call_args.args else call_args.kwargs["input_"]
    assert all(t.startswith("passage: ") for t in sent_input)
    assert sent_input[0] == "passage: How to reset your password."
    assert sent_input[1] == "passage: Export your data in CSV format."


def test_embed_passages_output_shape():
    embedder, _ = _make_embedder(dim=1024)
    results = embedder.embed_passages(["text one", "text two", "text three"])
    assert len(results) == 3
    assert all(len(v) == 1024 for v in results)


def test_embed_passages_returns_lists_of_floats():
    embedder, _ = _make_embedder()
    results = embedder.embed_passages(["some text"])
    assert isinstance(results[0], list)
    assert isinstance(results[0][0], float)


def test_embed_passages_empty_list():
    embedder, mock_model = _make_embedder()
    results = embedder.embed_passages([])
    assert results == []
    # encode still called with empty list — consistent behaviour
    mock_model.encode.assert_called_once()


# ---------------------------------------------------------------------------
# embed_query — prefix and shape
# ---------------------------------------------------------------------------


def test_embed_query_applies_query_prefix():
    embedder, mock_model = _make_embedder()
    embedder.embed_query("How do I cancel my subscription?")

    call_args = mock_model.encode.call_args
    sent_input = call_args.args[0] if call_args.args else call_args.kwargs["input_"]
    assert sent_input == "query: How do I cancel my subscription?"


def test_embed_query_output_shape():
    embedder, _ = _make_embedder(dim=1024)
    result = embedder.embed_query("test query")
    assert len(result) == 1024


def test_embed_query_returns_list_of_floats():
    embedder, _ = _make_embedder()
    result = embedder.embed_query("test")
    assert isinstance(result, list)
    assert isinstance(result[0], float)


# ---------------------------------------------------------------------------
# Prefix constants
# ---------------------------------------------------------------------------


def test_prefix_constants():
    from retrieval.embedder import MultilingualEmbedder

    assert MultilingualEmbedder.QUERY_PREFIX == "query: "
    assert MultilingualEmbedder.PASSAGE_PREFIX == "passage: "


def test_passage_and_query_prefixes_differ():
    from retrieval.embedder import MultilingualEmbedder

    assert MultilingualEmbedder.QUERY_PREFIX != MultilingualEmbedder.PASSAGE_PREFIX
