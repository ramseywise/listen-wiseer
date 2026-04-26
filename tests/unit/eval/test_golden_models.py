from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest

from evals.tasks.models import AgentGoldenSample

GOLDEN_PATH = Path(__file__).resolve().parents[3] / "evals" / "datasets" / "golden_intent.jsonl"

EXPECTED_INTENTS = {"artist_info", "genre_info", "recommendation", "history", "chit_chat"}
NEW_INTENTS = {"explore_my_taste", "discover"}
MIN_SAMPLES_PER_INTENT = 8
MIN_SAMPLES_NEW_INTENTS = 2
EXPECTED_TOTAL = 55


@pytest.fixture()
def golden_samples() -> list[AgentGoldenSample]:
    """Load and validate all golden samples from JSONL."""
    assert GOLDEN_PATH.exists(), f"Golden file not found: {GOLDEN_PATH}"
    samples = []
    with GOLDEN_PATH.open() as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            data = json.loads(line)
            samples.append(AgentGoldenSample(**data))
    return samples


def test_golden_samples_load_and_validate(golden_samples: list[AgentGoldenSample]) -> None:
    assert len(golden_samples) == EXPECTED_TOTAL


def test_all_intents_covered(golden_samples: list[AgentGoldenSample]) -> None:
    intent_counts = Counter(s.expected_intent for s in golden_samples)
    for intent in EXPECTED_INTENTS:
        assert intent_counts.get(intent, 0) >= MIN_SAMPLES_PER_INTENT, (
            f"Intent '{intent}' has {intent_counts.get(intent, 0)} samples, "
            f"need >= {MIN_SAMPLES_PER_INTENT}"
        )
    for intent in NEW_INTENTS:
        assert intent_counts.get(intent, 0) >= MIN_SAMPLES_NEW_INTENTS, (
            f"Intent '{intent}' has {intent_counts.get(intent, 0)} samples, "
            f"need >= {MIN_SAMPLES_NEW_INTENTS}"
        )


def test_sample_ids_unique(golden_samples: list[AgentGoldenSample]) -> None:
    ids = [s.sample_id for s in golden_samples]
    assert len(ids) == len(set(ids)), "Duplicate sample_id found"


def test_adversarial_samples_exist(golden_samples: list[AgentGoldenSample]) -> None:
    hard = [s for s in golden_samples if s.difficulty == "hard"]
    assert len(hard) >= 3, f"Expected >= 3 hard samples, got {len(hard)}"


def test_routes_are_valid(golden_samples: list[AgentGoldenSample]) -> None:
    valid_routes = {"rewrite_query", "clarify_or_proceed"}
    for sample in golden_samples:
        assert sample.expected_route in valid_routes, (
            f"{sample.sample_id}: invalid route '{sample.expected_route}'"
        )
