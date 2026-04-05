"""Golden dataset extraction from resolved support ticket JSONL.

Tier semantics:
    gold   — hand-curated; requires resolved_chunk_ids
    silver — CES-validated; requires resolved_doc_url + ces_rating
    bronze — any resolved ticket with a first_message
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

from evals.tasks.models import GoldenSample
from utils.logging import get_logger

log = get_logger(__name__)


def extract_golden_dataset(
    tickets_path: Path,
    output_path: Path,
    tier: str = "silver",  # "gold" | "silver" | "bronze"
) -> list[GoldenSample]:
    """Parse resolved ticket JSONL into a tiered golden dataset.

    Expected ticket fields:
        id                  — ticket identifier
        first_message       — customer's opening message (used as query)
        resolved_doc_url    — URL of the help article that resolved the ticket
        resolved_chunk_ids  — list of specific chunk IDs (gold tier only)
        category            — ticket category label
        language            — ISO code, defaults to "da"
        ces_rating          — customer effort score (silver tier filter)
        raptor_answer       — agent's final answer (not used here, for future eval)

    Args:
        tickets_path: Path to JSONL file with one ticket per line.
        output_path:  Path to write output JSONL (one GoldenSample per line).
        tier:         Extraction tier — "gold", "silver", or "bronze".

    Returns:
        List of extracted GoldenSample instances.
    """
    samples: list[GoldenSample] = []
    seen: set[tuple[str, str]] = set()

    with tickets_path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            ticket = json.loads(line)

            query = ticket.get("first_message", "").strip()
            if not query:
                continue

            doc_url = ticket.get("resolved_doc_url", "")
            chunk_ids: list[str] = ticket.get("resolved_chunk_ids", [])

            # Tier filters
            if tier == "gold" and not chunk_ids:
                continue
            if tier == "silver" and (not doc_url or not ticket.get("ces_rating")):
                continue

            # Deduplication by (query, doc_url) pair
            key = (query, doc_url)
            if key in seen:
                continue
            seen.add(key)

            ticket_id = ticket.get("id", uuid.uuid4().hex[:8])
            samples.append(
                GoldenSample(
                    query_id=f"ticket_{ticket_id}",
                    query=query,
                    expected_doc_url=doc_url,
                    relevant_chunk_ids=chunk_ids,
                    category=ticket.get("category", ""),
                    language=ticket.get("language", "da"),
                    difficulty="easy",
                    validation_level=tier,
                    source_ticket_id=str(ticket_id),
                )
            )

    log.info("eval.extract_golden.done", n_samples=len(samples), tier=tier)

    with output_path.open("w") as f:
        for sample in samples:
            f.write(sample.model_dump_json() + "\n")

    return samples


def _main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Extract golden dataset from ticket JSONL")
    parser.add_argument("--tickets", type=Path, required=True, help="Input JSONL path")
    parser.add_argument("--output", type=Path, required=True, help="Output JSONL path")
    parser.add_argument(
        "--tier",
        choices=["gold", "silver", "bronze"],
        default="silver",
        help="Extraction tier (default: silver)",
    )
    args = parser.parse_args()
    extract_golden_dataset(args.tickets, args.output, args.tier)


if __name__ == "__main__":
    _main()
