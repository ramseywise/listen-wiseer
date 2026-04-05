"""Unit tests for golden dataset extraction.

Fixtures are synthetic in-memory JSONL; no real ticket data is loaded.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).parents[2]))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_tickets(tmp_path: Path, tickets: list[dict]) -> Path:
    p = tmp_path / "tickets.jsonl"
    p.write_text("\n".join(json.dumps(t) for t in tickets))
    return p


def _make_ticket(
    ticket_id: str = "t1",
    first_message: str = "Hvordan nulstiller jeg min adgangskode?",
    resolved_doc_url: str = "https://help.example.com/reset",
    resolved_chunk_ids: list[str] | None = None,
    category: str = "account",
    language: str = "da",
    ces_rating: int | None = 4,
) -> dict:
    t: dict = {
        "id": ticket_id,
        "first_message": first_message,
        "resolved_doc_url": resolved_doc_url,
        "category": category,
        "language": language,
    }
    if resolved_chunk_ids is not None:
        t["resolved_chunk_ids"] = resolved_chunk_ids
    if ces_rating is not None:
        t["ces_rating"] = ces_rating
    return t


# ---------------------------------------------------------------------------
# Bronze tier (any resolved ticket)
# ---------------------------------------------------------------------------


def test_bronze_extracts_all_resolved(tmp_path: Path) -> None:
    """Bronze tier returns all tickets that have a first_message."""
    from evals.tasks.extract_golden import extract_golden_dataset

    tickets = [
        _make_ticket("t1", first_message="Spørgsmål A"),
        _make_ticket("t2", first_message="Spørgsmål B", ces_rating=None),
    ]
    path = _write_tickets(tmp_path, tickets)
    out = tmp_path / "out.jsonl"

    samples = extract_golden_dataset(path, out, tier="bronze")

    assert len(samples) == 2


def test_bronze_skips_empty_first_message(tmp_path: Path) -> None:
    """Tickets with no first_message are always skipped."""
    from evals.tasks.extract_golden import extract_golden_dataset

    tickets = [
        _make_ticket("t1"),
        {"id": "t2", "first_message": "", "resolved_doc_url": "https://x.com"},
        {"id": "t3"},  # no first_message key
    ]
    path = _write_tickets(tmp_path, tickets)
    out = tmp_path / "out.jsonl"

    samples = extract_golden_dataset(path, out, tier="bronze")

    assert len(samples) == 1
    assert samples[0].source_ticket_id == "t1"


# ---------------------------------------------------------------------------
# Silver tier
# ---------------------------------------------------------------------------


def test_silver_requires_doc_url_and_ces_rating(tmp_path: Path) -> None:
    """Silver tier drops tickets without doc_url or ces_rating."""
    from evals.tasks.extract_golden import extract_golden_dataset

    tickets = [
        _make_ticket("t1"),  # passes silver
        _make_ticket("t2", resolved_doc_url="", ces_rating=5),  # no url → dropped
        _make_ticket("t3", ces_rating=None),  # no rating → dropped
    ]
    path = _write_tickets(tmp_path, tickets)
    out = tmp_path / "out.jsonl"

    samples = extract_golden_dataset(path, out, tier="silver")

    assert len(samples) == 1
    assert samples[0].source_ticket_id == "t1"


def test_silver_sets_validation_level(tmp_path: Path) -> None:
    """validation_level matches the requested tier."""
    from evals.tasks.extract_golden import extract_golden_dataset

    path = _write_tickets(tmp_path, [_make_ticket("t1")])
    out = tmp_path / "out.jsonl"

    samples = extract_golden_dataset(path, out, tier="silver")

    assert samples[0].validation_level == "silver"


# ---------------------------------------------------------------------------
# Gold tier
# ---------------------------------------------------------------------------


def test_gold_requires_chunk_ids(tmp_path: Path) -> None:
    """Gold tier drops tickets that have no resolved_chunk_ids."""
    from evals.tasks.extract_golden import extract_golden_dataset

    tickets = [
        _make_ticket("t1", resolved_chunk_ids=["chunk_a", "chunk_b"]),  # passes
        _make_ticket("t2"),  # no chunk_ids → dropped
        _make_ticket("t3", resolved_chunk_ids=[]),  # empty list → dropped
    ]
    path = _write_tickets(tmp_path, tickets)
    out = tmp_path / "out.jsonl"

    samples = extract_golden_dataset(path, out, tier="gold")

    assert len(samples) == 1
    assert samples[0].relevant_chunk_ids == ["chunk_a", "chunk_b"]


def test_gold_sets_validation_level(tmp_path: Path) -> None:
    from evals.tasks.extract_golden import extract_golden_dataset

    path = _write_tickets(tmp_path, [_make_ticket("t1", resolved_chunk_ids=["c1"])])
    out = tmp_path / "out.jsonl"

    samples = extract_golden_dataset(path, out, tier="gold")

    assert samples[0].validation_level == "gold"


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------


def test_deduplication_drops_same_query_url_pair(tmp_path: Path) -> None:
    """Duplicate (query, doc_url) pairs are counted only once."""
    from evals.tasks.extract_golden import extract_golden_dataset

    base = _make_ticket("t1")
    duplicate = {**base, "id": "t2"}  # same query + url, different id
    path = _write_tickets(tmp_path, [base, duplicate])
    out = tmp_path / "out.jsonl"

    samples = extract_golden_dataset(path, out, tier="silver")

    assert len(samples) == 1


def test_same_query_different_url_is_not_duplicate(tmp_path: Path) -> None:
    """Same query text with different doc URLs produces two samples."""
    from evals.tasks.extract_golden import extract_golden_dataset

    t1 = _make_ticket("t1", resolved_doc_url="https://help.example.com/a")
    t2 = _make_ticket("t2", resolved_doc_url="https://help.example.com/b")
    path = _write_tickets(tmp_path, [t1, t2])
    out = tmp_path / "out.jsonl"

    samples = extract_golden_dataset(path, out, tier="silver")

    assert len(samples) == 2


# ---------------------------------------------------------------------------
# Output file
# ---------------------------------------------------------------------------


def test_output_file_is_valid_jsonl(tmp_path: Path) -> None:
    """Output file contains one valid JSON object per line."""
    from evals.tasks.extract_golden import extract_golden_dataset

    path = _write_tickets(
        tmp_path,
        [
            _make_ticket("t1", first_message="Spørgsmål A"),
            _make_ticket("t2", first_message="Spørgsmål B"),
        ],
    )
    out = tmp_path / "out.jsonl"

    extract_golden_dataset(path, out, tier="silver")

    lines = out.read_text().strip().split("\n")
    assert len(lines) == 2
    for line in lines:
        obj = json.loads(line)
        assert "query_id" in obj
        assert "query" in obj


def test_query_id_uses_ticket_id(tmp_path: Path) -> None:
    """query_id is prefixed with 'ticket_' followed by the ticket's id."""
    from evals.tasks.extract_golden import extract_golden_dataset

    path = _write_tickets(tmp_path, [_make_ticket("abc123")])
    out = tmp_path / "out.jsonl"

    samples = extract_golden_dataset(path, out, tier="bronze")

    assert samples[0].query_id == "ticket_abc123"


def test_missing_language_defaults_to_da(tmp_path: Path) -> None:
    """Tickets without a language field default to 'da'."""
    from evals.tasks.extract_golden import extract_golden_dataset

    ticket = {
        "id": "t1",
        "first_message": "Test spørgsmål",
        "resolved_doc_url": "https://x.com",
        "ces_rating": 3,
    }
    path = _write_tickets(tmp_path, [ticket])
    out = tmp_path / "out.jsonl"

    samples = extract_golden_dataset(path, out, tier="silver")

    assert samples[0].language == "da"
