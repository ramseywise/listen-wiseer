"""Generate synthetic English golden dataset from German eval data.

Samples diverse rows from the German source JSONL, translates queries with
Claude Haiku, and emits GoldenSample JSONL tagged with expected failure mode.

Failure mode taxonomy (from failure_clusters.png):
    none             — happy-path regression baseline
    zero_retrieval   — query returns nothing (corpus gap / embedding failure)
    coverage_gap     — topic not in knowledge base (max_score < 0.45)
    low_confidence   — ambiguous query, scores clustered (variance < 0.02)
    complexity_failure — multi-part question, single retrieval won't suffice
    grounding_failure  — async-only: answer contains unsupported claims
    retrieval_failure  — async-only: wrong docs retrieved despite ok scores

CLI:
    PYTHONPATH=src uv run python -m evals.tasks.generate_synthetic \\
        --source ../../template/nbks/ramsey/killing-it/eval_data/eval_dataset.jsonl \\
        --output data/golden_synthetic_en.jsonl \\
        --n 100 --seed 42
"""

from __future__ import annotations

import argparse
import json
import random
import re
from pathlib import Path
from typing import Any

from evals.tasks.models import GoldenSample
from utils.logging import get_logger

log = get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Target distribution across failure modes for the synthetic set.
# Values are approximate fractions — sampled rows are assigned in order.
FAILURE_MODE_DISTRIBUTION: list[tuple[str, float]] = [
    ("none", 0.40),  # regression baseline: happy-path queries
    ("coverage_gap", 0.15),  # out-of-scope questions
    ("low_confidence", 0.15),  # short / ambiguous phrasing
    ("complexity_failure", 0.15),  # multi-part questions
    ("grounding_failure", 0.08),  # async-only: needs faithfulness eval
    ("retrieval_failure", 0.07),  # async-only: misleading retrieval scores
]

# ---------------------------------------------------------------------------
# Rule-based German → English conversion
# ---------------------------------------------------------------------------

# Common German SaaS/accounting verbs → English verb phrase
_VERB_MAP: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\bdurchf[üu]hren\b", re.I), "perform"),
    (re.compile(r"\bk[üu]ndigen\b", re.I), "cancel"),
    (re.compile(r"\bannullieren\b", re.I), "cancel"),
    (re.compile(r"\bstornieren\b", re.I), "void"),
    (re.compile(r"\bbuchen\b", re.I), "book"),
    (re.compile(r"\berstellen\b", re.I), "create"),
    (re.compile(r"\banlegen\b", re.I), "create"),
    (re.compile(r"\b[äa]ndern\b", re.I), "change"),
    (re.compile(r"\baktualisieren\b", re.I), "update"),
    (re.compile(r"\bhinzuf[üu]gen\b", re.I), "add"),
    (re.compile(r"\bl[öo]schen\b", re.I), "delete"),
    (re.compile(r"\bexportieren\b", re.I), "export"),
    (re.compile(r"\bimportieren\b", re.I), "import"),
    (re.compile(r"\beinstellen\b", re.I), "configure"),
    (re.compile(r"\bkonfigurieren\b", re.I), "configure"),
    (re.compile(r"\beinrichten\b", re.I), "set up"),
    (re.compile(r"\b[üu]bertragen\b", re.I), "transfer"),
    (re.compile(r"\b[üu]berpr[üu]fen\b", re.I), "check"),
    (re.compile(r"\bpr[üu]fen\b", re.I), "check"),
    (re.compile(r"\bsuchen\b", re.I), "find"),
    (re.compile(r"\bfinden\b", re.I), "find"),
    (re.compile(r"\banzeigen\b", re.I), "view"),
    (re.compile(r"\baufrufen\b", re.I), "open"),
    (re.compile(r"\bverbinden\b", re.I), "connect"),
    (re.compile(r"\bverwalten\b", re.I), "manage"),
    (re.compile(r"\bbearbeiten\b", re.I), "edit"),
    (re.compile(r"\bzuweisen\b", re.I), "assign"),
    (re.compile(r"\bsenden\b", re.I), "send"),
    (re.compile(r"\bdrucken\b", re.I), "print"),
    (re.compile(r"\bherunterladen\b", re.I), "download"),
    (re.compile(r"\bhochladen\b", re.I), "upload"),
    (re.compile(r"\babschlie[ßs]en\b", re.I), "close"),
    (re.compile(r"\b[öo]ffnen\b", re.I), "open"),
    (re.compile(r"\bzahlen\b", re.I), "pay"),
    (re.compile(r"\berstatten\b", re.I), "refund"),
    (re.compile(r"\brechnen\b", re.I), "calculate"),
    (re.compile(r"\babrechnen\b", re.I), "invoice"),
    (re.compile(r"\berfassen\b", re.I), "record"),
    (re.compile(r"\bfreischalten\b", re.I), "activate"),
    (re.compile(r"\bdeaktivieren\b", re.I), "deactivate"),
    (re.compile(r"\bwiederherstellen\b", re.I), "restore"),
    (re.compile(r"\bzur[üu]cksetzen\b", re.I), "reset"),
]

# Common German nouns → English
_NOUN_MAP: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\bVertrag\b", re.I), "contract"),
    (re.compile(r"\bRechnung\b", re.I), "invoice"),
    (re.compile(r"\bKunde[ns]?\b", re.I), "customer"),
    (re.compile(r"\bGutschrift\b", re.I), "credit note"),
    (re.compile(r"\bZahlung\b", re.I), "payment"),
    (re.compile(r"\bAbonnement\b", re.I), "subscription"),
    (re.compile(r"\bAbo\b", re.I), "subscription"),
    (re.compile(r"\bAdd-on\b", re.I), "add-on"),
    (re.compile(r"\bProdukt\b", re.I), "product"),
    (re.compile(r"\bArtikel\b", re.I), "product"),
    (re.compile(r"\bKonto\b", re.I), "account"),
    (re.compile(r"\bBenutzer\b", re.I), "user"),
    (re.compile(r"\bPasswort\b", re.I), "password"),
    (re.compile(r"\bBericht\b", re.I), "report"),
    (re.compile(r"\bExport\b", re.I), "export"),
    (re.compile(r"\bImport\b", re.I), "import"),
    (re.compile(r"\bDaten\b", re.I), "data"),
    (re.compile(r"\bDokument\b", re.I), "document"),
    (re.compile(r"\bVorlage\b", re.I), "template"),
    (re.compile(r"\bEinstellung(?:en)?\b", re.I), "settings"),
    (re.compile(r"\bIntegration\b", re.I), "integration"),
    (re.compile(r"\bSchnittstelle\b", re.I), "interface"),
    (re.compile(r"\bBank(?:konto)?\b", re.I), "bank account"),
    (re.compile(r"\bBuchung\b", re.I), "booking"),
    (re.compile(r"\bBuchhaltung\b", re.I), "accounting"),
    (re.compile(r"\bMahnung\b", re.I), "reminder"),
    (re.compile(r"\bAngebot\b", re.I), "quote"),
    (re.compile(r"\bAuftrag\b", re.I), "order"),
    (re.compile(r"\bLieferant\b", re.I), "supplier"),
    (re.compile(r"\bSteuer\b", re.I), "tax"),
    (re.compile(r"\bMwSt\b", re.I), "VAT"),
    (re.compile(r"\bUmsatzsteuer\b", re.I), "VAT"),
    (re.compile(r"\bGutschein\b", re.I), "voucher"),
    (re.compile(r"\bRabatt\b", re.I), "discount"),
    (re.compile(r"\bPlan\b", re.I), "plan"),
    (re.compile(r"\bTarif\b", re.I), "plan"),
    (re.compile(r"\bKategorie\b", re.I), "category"),
    (re.compile(r"\bKostenst(?:elle)?\b", re.I), "cost centre"),
    (re.compile(r"\bZeitraum\b", re.I), "period"),
    (re.compile(r"\bDatum\b", re.I), "date"),
    (re.compile(r"\bF[äa]lligkeit\b", re.I), "due date"),
    (re.compile(r"\bGuthabens?\b", re.I), "credit balance"),
    (re.compile(r"\bOffene Posten\b", re.I), "open items"),
    (re.compile(r"\bMahnwesen\b", re.I), "dunning"),
    (re.compile(r"\bDebitor(?:en)?\b", re.I), "debtor"),
    (re.compile(r"\bKreditor(?:en)?\b", re.I), "creditor"),
]

# Mode-specific query transformers applied after base translation
_MODE_TRANSFORMS: dict[str, Any] = {
    "low_confidence": lambda q: " ".join(q.split()[:3]),  # truncate to 3 words
    "complexity_failure": lambda q: (
        f"{q} — and also, how do I reconcile this with my existing records "
        f"and what are the tax implications?"
    ),
    "coverage_gap": lambda q: q.replace("invoice", "payroll")
    .replace("contract", "employment contract")
    .replace("customer", "employee"),
}


def _rule_based_translate(german: str, mode: str) -> tuple[str, str]:
    """Convert a German query to approximate English using token substitution.

    Not a real translator — good enough for retrieval eval where the query
    exercises the pipeline, not human readability.
    """
    result = german

    for pattern, replacement in _VERB_MAP:
        result = pattern.sub(replacement, result)
    for pattern, replacement in _NOUN_MAP:
        result = pattern.sub(replacement, result)

    # Wrap bare phrases as a question if it doesn't already look like one
    result = result.strip().rstrip("?")
    if not result.lower().startswith(("how", "what", "where", "why", "can", "is", "do")):
        result = f"How do I {result.lower()}?"
    else:
        result = result + "?"

    # Apply mode-specific transform
    transform = _MODE_TRANSFORMS.get(mode)
    if transform:
        result = transform(result)

    notes = f"Rule-based conversion from German. Original: '{german[:80]}'. Mode: {mode}."
    return result, notes


# Hand-crafted hard queries covering Danish-specific context the German corpus
# won't include. These are capability-test canaries.
DANISH_SPECIFIC_HARD: list[dict[str, Any]] = [
    {
        "query": "How do I connect my e-conomic account to NemHandel for e-invoicing?",
        "failure_mode": "coverage_gap",
        "category": "integration",
        "difficulty": "hard",
        "notes": "NemHandel is Danish public e-invoice infrastructure — unlikely in German corpus.",
    },
    {
        "query": "Can I import transactions directly from MobilePay into the accounting system?",
        "failure_mode": "coverage_gap",
        "category": "integration",
        "difficulty": "hard",
        "notes": "MobilePay is a Danish/Nordic payment app — corpus gap expected.",
    },
    {
        "query": "How do I handle moms (VAT) for EU cross-border services sold to Danish B2C customers?",
        "failure_mode": "complexity_failure",
        "category": "tax",
        "difficulty": "hard",
        "notes": "Multi-step VAT question with Danish-specific terminology.",
    },
    {
        "query": "What is the correct SKATs reporting period for quarterly VAT returns?",
        "failure_mode": "coverage_gap",
        "category": "tax",
        "difficulty": "hard",
        "notes": "SKAT is the Danish tax authority — likely absent from German help content.",
    },
    {
        "query": "reconcile bank statement",
        "failure_mode": "low_confidence",
        "category": "banking",
        "difficulty": "medium",
        "notes": "Deliberately vague — tests score-variance signal.",
    },
    {
        "query": "invoice",
        "failure_mode": "low_confidence",
        "category": "invoicing",
        "difficulty": "easy",
        "notes": "Single-word query — extreme ambiguity case.",
    },
    {
        "query": "How do I set up automatic bank feed from Danske Bank, reconcile imported transactions, handle duplicates, and then close the accounting period — all before the 15th?",
        "failure_mode": "complexity_failure",
        "category": "banking",
        "difficulty": "hard",
        "notes": "Four sub-questions in one — classic complexity_failure trigger.",
    },
    {
        "query": "Why is my trial balance not matching my bank balance, and could it be related to the way I set up my opening balances when I migrated from my previous system last year?",
        "failure_mode": "complexity_failure",
        "category": "accounting",
        "difficulty": "hard",
        "notes": "Diagnostic + historical root-cause — requires multi-hop retrieval.",
    },
    {
        "query": "How do I issue a credit note for a paid invoice that was sent three months ago to a customer in Germany with reverse-charge VAT applied?",
        "failure_mode": "grounding_failure",
        "category": "invoicing",
        "difficulty": "hard",
        "notes": "Edge case — thin doc coverage likely causes hallucinated steps.",
    },
    {
        "query": "What happens to my subscription if I downgrade my plan mid-month and I've already sent 40 invoices?",
        "failure_mode": "grounding_failure",
        "category": "billing",
        "difficulty": "medium",
        "notes": "Billing edge case — model may confabulate plan limits.",
    },
    {
        "query": "How do I record a transaction where I paid a supplier partially in cash and partially via bank transfer?",
        "failure_mode": "retrieval_failure",
        "category": "accounting",
        "difficulty": "medium",
        "notes": "Indirect phrasing — 'split payment' docs may not surface.",
    },
    {
        "query": "My customer paid more than the invoice amount — what journal entry corrects the overpayment?",
        "failure_mode": "retrieval_failure",
        "category": "accounting",
        "difficulty": "medium",
        "notes": "Overpayment described as a journal correction — surface-form divergence.",
    },
    {
        "query": "How do I cancel a subscription for a customer who is unhappy with the service?",
        "failure_mode": "none",
        "category": "billing",
        "difficulty": "easy",
        "notes": "Happy-path regression: maps to cancellation workflow docs.",
    },
    {
        "query": "How do I add a new product to my invoice template?",
        "failure_mode": "none",
        "category": "invoicing",
        "difficulty": "easy",
        "notes": "Happy-path regression: standard invoicing question.",
    },
    {
        "query": "Where can I find my monthly invoice from the software provider?",
        "failure_mode": "none",
        "category": "billing",
        "difficulty": "easy",
        "notes": "Happy-path regression: account/billing section question.",
    },
    {
        "query": "How do I invite a colleague to access my account?",
        "failure_mode": "none",
        "category": "account",
        "difficulty": "easy",
        "notes": "Happy-path regression: user management.",
    },
    {
        "query": "Can I export my data if I decide to stop using the service?",
        "failure_mode": "coverage_gap",
        "category": "account",
        "difficulty": "medium",
        "notes": "Data portability / GDPR — may not be in help corpus.",
    },
    {
        "query": "Does your system comply with GDPR and where is my data stored?",
        "failure_mode": "coverage_gap",
        "category": "compliance",
        "difficulty": "medium",
        "notes": "Compliance/legal — typically thin in product help centers.",
    },
    {
        "query": "How do I set up automatic payment reminders for overdue invoices?",
        "failure_mode": "none",
        "category": "invoicing",
        "difficulty": "easy",
        "notes": "Happy-path regression: dunning/reminder feature.",
    },
    {
        "query": "I need to change my company's VAT number — how do I update it across all documents?",
        "failure_mode": "complexity_failure",
        "category": "account",
        "difficulty": "medium",
        "notes": "Cascading update question — multiple document types involved.",
    },
]


# ---------------------------------------------------------------------------
# Sampling helpers
# ---------------------------------------------------------------------------


def _load_source(path: Path) -> list[dict[str, Any]]:
    rows = []
    with path.open() as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _stratified_sample(
    rows: list[dict[str, Any]],
    n: int,
    seed: int,
) -> list[dict[str, Any]]:
    """Sample n rows stratified by source_type + category."""
    rng = random.Random(seed)  # noqa: S311
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        key = f"{row.get('source_type', 'unknown')}:{row.get('category', 'unknown')}"
        groups.setdefault(key, []).append(row)

    sampled: list[dict[str, Any]] = []
    keys = sorted(groups)
    per_group = max(1, n // len(keys))

    for key in keys:
        pool = groups[key]
        rng.shuffle(pool)
        sampled.extend(pool[:per_group])

    rng.shuffle(sampled)
    return sampled[:n]


def _assign_failure_modes(n: int, seed: int) -> list[str]:
    """Return a list of n failure mode labels matching FAILURE_MODE_DISTRIBUTION."""
    rng = random.Random(seed + 1)  # noqa: S311
    modes: list[str] = []
    for mode, frac in FAILURE_MODE_DISTRIBUTION:
        modes.extend([mode] * round(frac * n))
    # pad or trim to exactly n
    while len(modes) < n:
        modes.append("none")
    modes = modes[:n]
    rng.shuffle(modes)
    return modes


# ---------------------------------------------------------------------------
# Translation
# ---------------------------------------------------------------------------


def _translate_batch(
    rows: list[dict[str, Any]],
    failure_modes: list[str],
) -> list[tuple[str, str]]:
    """Convert German queries to English using rule-based substitution."""
    results: list[tuple[str, str]] = []
    for row, mode in zip(rows, failure_modes, strict=True):
        german = row.get("query", "").strip()
        if not german:
            results.append(("", ""))
            continue
        results.append(_rule_based_translate(german, mode))
    log.info("generate_synthetic.translated", n=len(results))
    return results


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------


def _source_type_to_doc_url(row: dict[str, Any]) -> str:
    """Derive a placeholder expected_doc_url from source metadata."""
    source_doc_id = row.get("source_doc_id", "")
    source_type = row.get("source_type", "unknown")
    # Placeholder URL — replace with real base URL when corpus is wired up
    return f"https://help.example.com/{source_type}/{source_doc_id}"


def _difficulty_for_mode(mode: str) -> str:
    easy_modes = {"none"}
    hard_modes = {"complexity_failure", "grounding_failure", "retrieval_failure"}
    if mode in easy_modes:
        return "easy"
    if mode in hard_modes:
        return "hard"
    return "medium"


def build_golden_samples(
    rows: list[dict[str, Any]],
    translated: list[tuple[str, str]],
    failure_modes: list[str],
) -> list[GoldenSample]:
    samples: list[GoldenSample] = []
    for i, (row, (query, notes), mode) in enumerate(
        zip(rows, translated, failure_modes, strict=True)
    ):
        if not query:
            continue
        sample = GoldenSample(
            query_id=f"synthetic_en_{i:04d}",
            query=query,
            expected_doc_url=_source_type_to_doc_url(row),
            relevant_chunk_ids=row.get("relevant_chunks", []),
            category=row.get("category", ""),
            language="en",
            difficulty=_difficulty_for_mode(mode),
            validation_level="synthetic",
            source_ticket_id=row.get("query_id", ""),
        )
        # Attach failure_mode + notes as extra fields via model_extra
        # (GoldenSample has model_config allowing extras if needed — stored inline)
        samples.append(sample)
        # We'll serialise failure_mode + notes alongside the GoldenSample fields
        # by building a merged dict at write time.
        sample.__dict__["_failure_mode"] = mode
        sample.__dict__["_notes"] = notes

    return samples


def _to_output_dict(sample: GoldenSample) -> dict[str, Any]:
    d = sample.model_dump()
    d["failure_mode"] = sample.__dict__.get("_failure_mode", "none")
    d["notes"] = sample.__dict__.get("_notes", "")
    return d


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate synthetic English golden dataset from German eval JSONL"
    )
    parser.add_argument(
        "--source",
        type=Path,
        required=True,
        help="Path to German eval JSONL (e.g. eval_dataset.jsonl)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Output path for golden_synthetic_en.jsonl",
    )
    parser.add_argument(
        "--n",
        type=int,
        default=80,
        help="Number of translated samples to generate (default: 80)",
    )
    parser.add_argument("--seed", type=int, default=42, help="Random seed (default: 42)")
    args = parser.parse_args()

    log.info("generate_synthetic.start", n=args.n, seed=args.seed, source=str(args.source))

    # 1. Load + sample source data
    source_rows = _load_source(args.source)
    log.info("generate_synthetic.loaded", total_rows=len(source_rows))

    sampled = _stratified_sample(source_rows, args.n, args.seed)
    failure_modes = _assign_failure_modes(len(sampled), args.seed)
    log.info("generate_synthetic.sampled", n=len(sampled))

    # 2. Rule-based German → English conversion
    translated = _translate_batch(sampled, failure_modes)

    # 3. Build GoldenSample objects
    samples = build_golden_samples(sampled, translated, failure_modes)

    # 4. Append hand-crafted Danish-specific hard queries
    for i, spec in enumerate(DANISH_SPECIFIC_HARD):
        sample = GoldenSample(
            query_id=f"synthetic_da_{i:03d}",
            query=spec["query"],
            expected_doc_url=f"https://help.example.com/da/{spec['category']}/unknown",
            relevant_chunk_ids=[],
            category=spec["category"],
            language="en",
            difficulty=spec["difficulty"],
            validation_level="synthetic",
            source_ticket_id="",
        )
        sample.__dict__["_failure_mode"] = spec["failure_mode"]
        sample.__dict__["_notes"] = spec["notes"]
        samples.append(sample)

    log.info(
        "generate_synthetic.assembled",
        n_translated=len(sampled),
        n_handcrafted=len(DANISH_SPECIFIC_HARD),
        n_total=len(samples),
    )

    # 5. Write output
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w") as f:
        for sample in samples:
            f.write(json.dumps(_to_output_dict(sample)) + "\n")

    log.info("generate_synthetic.done", output=str(args.output), n=len(samples))

    # 6. Print distribution summary
    from collections import Counter

    mode_counts = Counter(s.__dict__.get("_failure_mode", "none") for s in samples)
    print("\nFailure mode distribution:")
    for mode, count in sorted(mode_counts.items(), key=lambda x: -x[1]):
        print(f"  {mode:<22} {count:>4} ({count / len(samples):.0%})")
    print(f"\nTotal: {len(samples)} samples → {args.output}")


if __name__ == "__main__":
    _main()
