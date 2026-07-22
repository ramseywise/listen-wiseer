"""Unit tests for the agent memory store and memory helpers.

Tests episodic, semantic (taste), and procedural memory roundtrips
using a plain InMemoryStore (no embeddings needed for put/get).
"""

from __future__ import annotations

import pytest
from langgraph.store.memory import InMemoryStore

from agent.memory_store import (
    get_procedural_prompt,
    update_procedural_prompt,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def store() -> InMemoryStore:
    """Plain InMemoryStore — no embedding index (faster, sufficient for put/get)."""
    return InMemoryStore()


# ---------------------------------------------------------------------------
# Episodic memory
# ---------------------------------------------------------------------------


async def test_episodic_roundtrip(store: InMemoryStore) -> None:
    """Put a session, search with similar query, assert it's retrieved."""
    await store.aput(
        ("enoa", "user1", "sessions"),
        "s1",
        {"request": "recommend me some zouk", "tracks": "1. Zouk Night 2. Zouk Dawn"},
    )

    items = await store.asearch(("enoa", "user1", "sessions"), limit=5)
    assert len(items) == 1
    assert items[0].value["request"] == "recommend me some zouk"


async def test_episodic_multiple_sessions(store: InMemoryStore) -> None:
    """Multiple sessions stored and retrievable."""
    for i in range(3):
        await store.aput(
            ("enoa", "user1", "sessions"),
            f"s{i}",
            {"request": f"request {i}", "tracks": f"track {i}"},
        )

    items = await store.asearch(("enoa", "user1", "sessions"), limit=10)
    assert len(items) == 3


async def test_episodic_user_isolation(store: InMemoryStore) -> None:
    """Sessions are scoped per user."""
    await store.aput(
        ("enoa", "alice", "sessions"),
        "s1",
        {"request": "zouk", "tracks": "track1"},
    )
    await store.aput(
        ("enoa", "bob", "sessions"),
        "s2",
        {"request": "bossa nova", "tracks": "track2"},
    )

    alice_items = await store.asearch(("enoa", "alice", "sessions"), limit=10)
    bob_items = await store.asearch(("enoa", "bob", "sessions"), limit=10)

    assert len(alice_items) == 1
    assert len(bob_items) == 1
    assert alice_items[0].value["request"] == "zouk"
    assert bob_items[0].value["request"] == "bossa nova"


# ---------------------------------------------------------------------------
# Taste profile (semantic)
# ---------------------------------------------------------------------------


async def test_taste_profile_roundtrip(store: InMemoryStore) -> None:
    """Store a taste fact, retrieve it by search."""
    await store.aput(
        ("enoa", "user1", "taste"),
        "t1",
        {"fact": "prefers zouk over kizomba"},
    )

    items = await store.asearch(("enoa", "user1", "taste"), limit=5)
    assert len(items) == 1
    assert "zouk" in items[0].value["fact"]


async def test_taste_profile_multiple_facts(store: InMemoryStore) -> None:
    """Multiple taste facts stored and retrievable."""
    facts = [
        "loves acoustic guitar",
        "dislikes BPM > 140",
        "prefers female vocals",
    ]
    for i, fact in enumerate(facts):
        await store.aput(("enoa", "user1", "taste"), f"t{i}", {"fact": fact})

    items = await store.asearch(("enoa", "user1", "taste"), limit=10)
    assert len(items) == 3


# ---------------------------------------------------------------------------
# Procedural memory
# ---------------------------------------------------------------------------


async def test_procedural_fallback(store: InMemoryStore) -> None:
    """Empty store returns None (caller uses default prompt)."""
    result = await get_procedural_prompt("user1", store)
    assert result is None


async def test_procedural_roundtrip(store: InMemoryStore) -> None:
    """Store instructions, retrieve them."""
    instructions = "Always explain why each track matches the user's ENOA zone."
    await update_procedural_prompt("user1", instructions, store)

    result = await get_procedural_prompt("user1", store)
    assert result == instructions


async def test_procedural_overwrite(store: InMemoryStore) -> None:
    """Updating instructions overwrites the previous value."""
    await update_procedural_prompt("user1", "version 1", store)
    await update_procedural_prompt("user1", "version 2", store)

    result = await get_procedural_prompt("user1", store)
    assert result == "version 2"


async def test_procedural_user_isolation(store: InMemoryStore) -> None:
    """Procedural instructions are scoped per user."""
    await update_procedural_prompt("alice", "alice instructions", store)
    await update_procedural_prompt("bob", "bob instructions", store)

    assert await get_procedural_prompt("alice", store) == "alice instructions"
    assert await get_procedural_prompt("bob", store) == "bob instructions"
