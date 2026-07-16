"""Unit tests for the agent memory store and memory helpers.

Tests episodic, semantic (taste), and procedural memory roundtrips
using a plain InMemoryStore (no embeddings needed for put/get).
"""

from __future__ import annotations

import asyncio

import pytest
from agent.memory_store import (
    get_procedural_prompt,
    update_procedural_prompt,
)
from langgraph.store.memory import InMemoryStore

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def store() -> InMemoryStore:
    """Plain InMemoryStore — no embedding index (faster, sufficient for put/get)."""
    return InMemoryStore()


def _run(coro):
    """Helper to run async in sync tests."""
    return asyncio.get_event_loop().run_until_complete(coro)


# ---------------------------------------------------------------------------
# Episodic memory
# ---------------------------------------------------------------------------


def test_episodic_roundtrip(store: InMemoryStore) -> None:
    """Put a session, search with similar query, assert it's retrieved."""
    _run(
        store.aput(
            ("enoa", "user1", "sessions"),
            "s1",
            {"request": "recommend me some zouk", "tracks": "1. Zouk Night 2. Zouk Dawn"},
        )
    )

    items = _run(store.asearch(("enoa", "user1", "sessions"), limit=5))
    assert len(items) == 1
    assert items[0].value["request"] == "recommend me some zouk"


def test_episodic_multiple_sessions(store: InMemoryStore) -> None:
    """Multiple sessions stored and retrievable."""
    for i in range(3):
        _run(
            store.aput(
                ("enoa", "user1", "sessions"),
                f"s{i}",
                {"request": f"request {i}", "tracks": f"track {i}"},
            )
        )

    items = _run(store.asearch(("enoa", "user1", "sessions"), limit=10))
    assert len(items) == 3


def test_episodic_user_isolation(store: InMemoryStore) -> None:
    """Sessions are scoped per user."""
    _run(
        store.aput(
            ("enoa", "alice", "sessions"),
            "s1",
            {"request": "zouk", "tracks": "track1"},
        )
    )
    _run(
        store.aput(
            ("enoa", "bob", "sessions"),
            "s2",
            {"request": "bossa nova", "tracks": "track2"},
        )
    )

    alice_items = _run(store.asearch(("enoa", "alice", "sessions"), limit=10))
    bob_items = _run(store.asearch(("enoa", "bob", "sessions"), limit=10))

    assert len(alice_items) == 1
    assert len(bob_items) == 1
    assert alice_items[0].value["request"] == "zouk"
    assert bob_items[0].value["request"] == "bossa nova"


# ---------------------------------------------------------------------------
# Taste profile (semantic)
# ---------------------------------------------------------------------------


def test_taste_profile_roundtrip(store: InMemoryStore) -> None:
    """Store a taste fact, retrieve it by search."""
    _run(
        store.aput(
            ("enoa", "user1", "taste"),
            "t1",
            {"fact": "prefers zouk over kizomba"},
        )
    )

    items = _run(store.asearch(("enoa", "user1", "taste"), limit=5))
    assert len(items) == 1
    assert "zouk" in items[0].value["fact"]


def test_taste_profile_multiple_facts(store: InMemoryStore) -> None:
    """Multiple taste facts stored and retrievable."""
    facts = [
        "loves acoustic guitar",
        "dislikes BPM > 140",
        "prefers female vocals",
    ]
    for i, fact in enumerate(facts):
        _run(store.aput(("enoa", "user1", "taste"), f"t{i}", {"fact": fact}))

    items = _run(store.asearch(("enoa", "user1", "taste"), limit=10))
    assert len(items) == 3


# ---------------------------------------------------------------------------
# Procedural memory
# ---------------------------------------------------------------------------


def test_procedural_fallback(store: InMemoryStore) -> None:
    """Empty store returns None (caller uses default prompt)."""
    result = _run(get_procedural_prompt("user1", store))
    assert result is None


def test_procedural_roundtrip(store: InMemoryStore) -> None:
    """Store instructions, retrieve them."""
    instructions = "Always explain why each track matches the user's ENOA zone."
    _run(update_procedural_prompt("user1", instructions, store))

    result = _run(get_procedural_prompt("user1", store))
    assert result == instructions


def test_procedural_overwrite(store: InMemoryStore) -> None:
    """Updating instructions overwrites the previous value."""
    _run(update_procedural_prompt("user1", "version 1", store))
    _run(update_procedural_prompt("user1", "version 2", store))

    result = _run(get_procedural_prompt("user1", store))
    assert result == "version 2"


def test_procedural_user_isolation(store: InMemoryStore) -> None:
    """Procedural instructions are scoped per user."""
    _run(update_procedural_prompt("alice", "alice instructions", store))
    _run(update_procedural_prompt("bob", "bob instructions", store))

    assert _run(get_procedural_prompt("alice", store)) == "alice instructions"
    assert _run(get_procedural_prompt("bob", store)) == "bob instructions"
