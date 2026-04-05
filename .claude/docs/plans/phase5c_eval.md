# Plan: Phase 5c — Eval Harness
Date: 2026-04-05
Predecessor: Phase 5b (intent routing)
Next: Phase 6 (Spotify recommendations API)

---

## Context & What Exists

The `evals/` directory was built for a Danish customer support assistant.
Reusable as-is:
- `evals/tasks/models.py` — `EvalRunConfig`, `GoldenSample`, `RetrievalMetrics`
- `evals/tasks/tracing.py` — `PipelineTracer`, `FailureClusterer`, `PipelineTrace`
- `evals/graders/answer_eval.py` — `AnswerJudge`, `ClosedBookBaseline` (needs music system prompt)

Needs adaptation:
- `evals/run_local_eval.py` — hard-coded to OpenSearch + Danish golden JSONL
- `evals/tasks/extract_golden.py`, `generate_synthetic.py` — not implemented
- `evals/trials/` — empty
- Golden datasets — none exist yet
- `evals/metrics/retrieval_eval.py` — uses `expected_doc_url`, not meaningful for music

**Goal**: Working eval harness covering:
1. **Smoke dataset** — 10-15 examples, manually written, covers all intent types
2. **RAG eval** — keyword hit rate (no LLM) + optional LLM judge
3. **Tool selection eval** — did the agent pick the right tool?
4. **Eval runner** — single `python -m evals.run_eval` entry point
5. **Notebook** — `notebooks/eda/09_eval.ipynb` for interactive exploration

**Note on dataset size**: Smoke dataset is intentionally small (10-15 samples).
The harness is more important than volume at this stage. Document clearly where
to add examples as new intents / edge cases are discovered.

---

## Out of Scope

- Automated dataset generation from real user traffic (needs production data first)
- LangFuse custom score logging (Phase 6+ once production traffic exists)
- Trajectory eval / loop detection (useful later, not blocking now)
- CI integration (Phase 6+)
- RAGAS integration (revisit when dataset grows to 50+ samples)

---

## Steps

### Step 1: Music-specific sample schemas + smoke datasets

**Files**:
- `evals/tasks/models.py` (extend — add `MusicGoldenSample`, `ToolSelectionSample`)
- `evals/datasets/smoke_rag.jsonl` (new — 10 RAG samples)
- `evals/datasets/smoke_tool_selection.jsonl` (new — 15 tool selection samples)
- `tests/unit/eval/test_models.py` (new)

**New models**:
```python
# evals/tasks/models.py — add:

class MusicGoldenSample(BaseModel):
    """RAG eval sample for listen-wiseer artist/genre queries."""
    query_id: str
    query: str
    expected_answer_contains: list[str]  # key terms that must appear in the answer
    intent: str       # "artist_info" | "genre_info" | "history" | "recommendation"
    subject: str      # artist or genre name to look up
    difficulty: str = "easy"   # easy | medium | hard
    notes: str = ""


class ToolSelectionSample(BaseModel):
    """Tool selection eval sample."""
    query_id: str
    query: str
    expected_tool: str    # exact tool name, or "none" if no tool expected
    expected_params: dict = {}
    intent: str = ""      # expected intent from classify_intent node
    notes: str = ""
```

**Smoke RAG dataset** (`evals/datasets/smoke_rag.jsonl` — 10 samples):
```jsonl
{"query_id": "rag_001", "query": "Who is Aphex Twin?", "expected_answer_contains": ["electronic", "Richard"], "intent": "artist_info", "subject": "Aphex Twin", "difficulty": "easy"}
{"query_id": "rag_002", "query": "What is zouk music?", "expected_answer_contains": ["Brazilian", "dance"], "intent": "genre_info", "subject": "zouk", "difficulty": "easy"}
{"query_id": "rag_003", "query": "Tell me about Radiohead", "expected_answer_contains": ["British", "rock"], "intent": "artist_info", "subject": "Radiohead", "difficulty": "easy"}
{"query_id": "rag_004", "query": "What is bossa nova?", "expected_answer_contains": ["Brazilian", "jazz"], "intent": "genre_info", "subject": "bossa nova", "difficulty": "easy"}
{"query_id": "rag_005", "query": "What are the origins of afrobeats?", "expected_answer_contains": ["Nigeria", "Africa"], "intent": "genre_info", "subject": "afrobeats", "difficulty": "medium"}
{"query_id": "rag_006", "query": "Who influenced Boards of Canada?", "expected_answer_contains": ["electronic", "ambient"], "intent": "artist_info", "subject": "Boards of Canada", "difficulty": "medium"}
{"query_id": "rag_007", "query": "What style of music does Flying Lotus make?", "expected_answer_contains": ["hip-hop", "electronic"], "intent": "artist_info", "subject": "Flying Lotus", "difficulty": "easy"}
{"query_id": "rag_008", "query": "What is ambient music?", "expected_answer_contains": ["Brian Eno", "atmosphere"], "intent": "genre_info", "subject": "ambient music", "difficulty": "easy"}
{"query_id": "rag_009", "query": "Tell me something about John Coltrane", "expected_answer_contains": ["jazz", "saxophone"], "intent": "artist_info", "subject": "John Coltrane", "difficulty": "easy"}
{"query_id": "rag_010", "query": "What is the difference between house and techno?", "expected_answer_contains": ["tempo", "Detroit"], "intent": "genre_info", "subject": "house music", "difficulty": "medium", "notes": "multi-genre query — tests subject selection"}
```

**Smoke tool selection dataset** (`evals/datasets/smoke_tool_selection.jsonl` — 15 samples):
```jsonl
{"query_id": "tool_001", "query": "recommend me zouk tracks", "expected_tool": "recommend_by_genre", "intent": "recommendation"}
{"query_id": "tool_002", "query": "find tracks similar to this song", "expected_tool": "recommend_similar_tracks", "intent": "recommendation"}
{"query_id": "tool_003", "query": "who is Aphex Twin?", "expected_tool": "get_artist_context", "intent": "artist_info"}
{"query_id": "tool_004", "query": "what have I been listening to recently?", "expected_tool": "get_recently_played", "intent": "history"}
{"query_id": "tool_005", "query": "recommend tracks for this artist", "expected_tool": "recommend_for_artist", "intent": "recommendation"}
{"query_id": "tool_006", "query": "what is bossa nova?", "expected_tool": "get_artist_context", "intent": "genre_info"}
{"query_id": "tool_007", "query": "who sounds like Radiohead?", "expected_tool": "get_related_artists", "intent": "artist_info"}
{"query_id": "tool_008", "query": "suggest tracks from my saved playlists", "expected_tool": "recommend_for_playlist", "intent": "recommendation"}
{"query_id": "tool_009", "query": "hello, what can you do?", "expected_tool": "none", "intent": "chit_chat"}
{"query_id": "tool_010", "query": "find me something chill to listen to", "expected_tool": "recommend_by_genre", "intent": "recommendation"}
{"query_id": "tool_011", "query": "tell me about the history of jazz", "expected_tool": "get_artist_context", "intent": "genre_info"}
{"query_id": "tool_012", "query": "remember that I like melancholic music", "expected_tool": "manage_taste_memory", "intent": "history"}
{"query_id": "tool_013", "query": "what are my music preferences?", "expected_tool": "search_taste_memory", "intent": "history"}
{"query_id": "tool_014", "query": "find tracks by Floating Points", "expected_tool": "search_tracks", "intent": "recommendation"}
{"query_id": "tool_015", "query": "recommend based on my listening history", "expected_tool": "get_recently_played", "intent": "history"}
```

**Tests**:
```python
# tests/unit/eval/test_models.py
def test_music_golden_sample_loads():
    import json
    from pathlib import Path
    from evals.tasks.models import MusicGoldenSample
    path = Path("evals/datasets/smoke_rag.jsonl")
    samples = [MusicGoldenSample.model_validate(json.loads(l)) for l in path.read_text().splitlines() if l.strip()]
    assert len(samples) == 10
    intents = {s.intent for s in samples}
    assert "artist_info" in intents and "genre_info" in intents

def test_tool_selection_sample_loads():
    import json
    from pathlib import Path
    from evals.tasks.models import ToolSelectionSample
    path = Path("evals/datasets/smoke_tool_selection.jsonl")
    samples = [ToolSelectionSample.model_validate(json.loads(l)) for l in path.read_text().splitlines() if l.strip()]
    assert len(samples) == 15
    assert any(s.expected_tool == "none" for s in samples)  # chit_chat case
```

**Run**: `uv run pytest tests/unit/eval/test_models.py -v`

**Done when**: Both JSONL files load and validate; `MusicGoldenSample` fields correct.

---

### Step 2: RAG eval — keyword hit rate + optional LLM judge

**Files**:
- `evals/metrics/music_rag_eval.py` (new)
- `evals/graders/answer_eval.py` (update `_JUDGE_SYSTEM` to music context)
- `tests/unit/eval/test_music_rag_eval.py` (new)

**What**: Two-tier RAG evaluation:
1. **Keyword hit rate** — no LLM, always runs. Checks `expected_answer_contains` in answer.
2. **LLM judge** — gated by `CONFIRM_EXPENSIVE_OPS`. Uses `AnswerJudge` with music prompt.

```python
# evals/metrics/music_rag_eval.py
from __future__ import annotations

from dataclasses import dataclass
from evals.tasks.models import MusicGoldenSample
from evals.graders.answer_eval import AnswerJudge, JudgeResult, CONFIRM_EXPENSIVE_OPS
from utils.logging import get_logger

log = get_logger(__name__)


@dataclass
class RAGEvalResult:
    query_id: str
    query: str
    subject: str
    answer: str
    keyword_hit_rate: float
    keywords_found: list[str]
    keywords_missing: list[str]
    judge_result: JudgeResult | None = None


def evaluate_rag_sample(
    sample: MusicGoldenSample,
    get_context_fn,   # callable(subject: str, top_k: int) -> str
    judge: AnswerJudge | None = None,
) -> RAGEvalResult:
    """Evaluate a single RAG sample. get_context_fn is MusicRAG.get_context."""
    answer = get_context_fn(sample.subject, 3)
    answer_lower = answer.lower()

    found = [kw for kw in sample.expected_answer_contains if kw.lower() in answer_lower]
    missing = [kw for kw in sample.expected_answer_contains if kw.lower() not in answer_lower]
    hit_rate = len(found) / len(sample.expected_answer_contains) if sample.expected_answer_contains else 1.0

    judge_result = None
    if judge and CONFIRM_EXPENSIVE_OPS:
        judge_result = judge.evaluate(
            query_id=sample.query_id,
            question=sample.query,
            context_chunks=[answer],
            answer=answer,
        )

    log.info("eval.rag.sample", query_id=sample.query_id, hit_rate=hit_rate,
             n_found=len(found), n_missing=len(missing))
    return RAGEvalResult(
        query_id=sample.query_id, query=sample.query, subject=sample.subject,
        answer=answer, keyword_hit_rate=hit_rate,
        keywords_found=found, keywords_missing=missing, judge_result=judge_result,
    )


def evaluate_rag_dataset(
    samples: list[MusicGoldenSample],
    get_context_fn,
    judge: AnswerJudge | None = None,
) -> list[RAGEvalResult]:
    return [evaluate_rag_sample(s, get_context_fn, judge) for s in samples]


def summarize_rag(results: list[RAGEvalResult]) -> dict:
    n = len(results)
    avg_hit_rate = sum(r.keyword_hit_rate for r in results) / n if n else 0.0
    return {
        "n_samples": n,
        "avg_keyword_hit_rate": avg_hit_rate,
        "pass": avg_hit_rate >= 0.8,
        "failures": [
            {"query_id": r.query_id, "missing": r.keywords_missing}
            for r in results if r.keyword_hit_rate < 1.0
        ],
    }
```

**AnswerJudge music prompt** (update `evals/graders/answer_eval.py`):
```python
_JUDGE_SYSTEM = """\
You are an expert evaluator for a music information RAG system.
Evaluate the generated answer on three dimensions:
1. faithfulness — does it only claim what the retrieved context supports?
2. relevance — does it address the user's music question?
3. completeness — are the key facts about the artist or genre present?

Return ONLY a JSON object:
{
  "is_correct": <true if faithful and relevant>,
  "score": <float 0.0-1.0>,
  "faithfulness": <float 0.0-1.0>,
  "relevance": <float 0.0-1.0>,
  "completeness": <float 0.0-1.0>,
  "reasoning": <one sentence>
}
No other text."""
```

**Tests**:
```python
def test_evaluate_rag_sample_full_hit():
    sample = MusicGoldenSample(
        query_id="rag_001", query="Who is Aphex Twin?",
        expected_answer_contains=["electronic", "Richard"],
        intent="artist_info", subject="Aphex Twin"
    )
    get_context = lambda subject, top_k: "Aphex Twin is a British electronic musician named Richard"
    result = evaluate_rag_sample(sample, get_context)
    assert result.keyword_hit_rate == 1.0
    assert result.keywords_missing == []

def test_evaluate_rag_sample_partial_miss():
    sample = MusicGoldenSample(
        query_id="rag_001", query="Who is Aphex Twin?",
        expected_answer_contains=["electronic", "Richard", "ambient"],
        intent="artist_info", subject="Aphex Twin"
    )
    get_context = lambda subject, top_k: "Aphex Twin makes electronic music"
    result = evaluate_rag_sample(sample, get_context)
    assert result.keyword_hit_rate < 1.0
    assert "ambient" in result.keywords_missing

def test_summarize_rag_pass():
    from evals.metrics.music_rag_eval import RAGEvalResult, summarize_rag
    results = [
        RAGEvalResult("q1", "q", "s", "a", 1.0, ["electronic"], [], None),
        RAGEvalResult("q2", "q", "s", "a", 0.9, ["jazz"], ["piano"], None),
    ]
    summary = summarize_rag(results)
    assert summary["pass"] is True
```

**Run**: `uv run pytest tests/unit/eval/test_music_rag_eval.py -v`

**Done when**: Keyword eval works without LLM; `summarize_rag` reports pass/fail.

---

### Step 3: Tool selection eval

**Files**:
- `evals/metrics/tool_selection_eval.py` (new)
- `tests/unit/eval/test_tool_selection_eval.py` (new)

**What**: Run agent on each `ToolSelectionSample`, extract first tool called from
message trace, check against `expected_tool`. Gated by `CONFIRM_EXPENSIVE_OPS`.

```python
# evals/metrics/tool_selection_eval.py
from __future__ import annotations

from dataclasses import dataclass
from evals.tasks.models import ToolSelectionSample
from evals.graders.answer_eval import CONFIRM_EXPENSIVE_OPS
from utils.logging import get_logger

log = get_logger(__name__)


@dataclass
class ToolSelectionResult:
    query_id: str
    query: str
    expected_tool: str
    actual_tool: str | None
    correct: bool
    intent_correct: bool
    actual_intent: str = ""


def extract_first_tool_call(messages: list) -> str | None:
    """Extract the name of the first tool called from an agent message list."""
    for msg in messages:
        if hasattr(msg, "tool_calls") and msg.tool_calls:
            return msg.tool_calls[0].get("name")
        if hasattr(msg, "additional_kwargs"):
            calls = msg.additional_kwargs.get("tool_calls", [])
            if calls:
                return calls[0].get("function", {}).get("name")
    return None


async def evaluate_tool_selection(
    samples: list[ToolSelectionSample],
    graph,  # compiled LangGraph agent
) -> list[ToolSelectionResult]:
    """Run agent on each sample. Requires CONFIRM_EXPENSIVE_OPS=True."""
    if not CONFIRM_EXPENSIVE_OPS:
        raise RuntimeError(
            "Set CONFIRM_EXPENSIVE_OPS=True to run tool selection eval. "
            "Estimated cost: ~$0.01-0.05 per sample."
        )

    import uuid
    from langchain_core.messages import HumanMessage

    results = []
    for sample in samples:
        config = {"configurable": {"thread_id": str(uuid.uuid4())}}
        state = {"messages": [HumanMessage(content=sample.query)]}
        try:
            result_state = await graph.ainvoke(state, config=config)
            actual_tool = extract_first_tool_call(result_state.get("messages", []))
            actual_intent = result_state.get("intent", "")
        except Exception as exc:
            log.error("eval.tool_selection.error", query_id=sample.query_id, error=str(exc))
            actual_tool = None
            actual_intent = ""

        expected = sample.expected_tool
        correct = (expected == "none" and actual_tool is None) or (actual_tool == expected)
        intent_correct = (actual_intent == sample.intent) if sample.intent else True

        log.info("eval.tool_selection.sample", query_id=sample.query_id,
                 expected=expected, actual=actual_tool, correct=correct)
        results.append(ToolSelectionResult(
            query_id=sample.query_id, query=sample.query,
            expected_tool=expected, actual_tool=actual_tool,
            correct=correct, intent_correct=intent_correct, actual_intent=actual_intent,
        ))
    return results


def summarize_tool_selection(results: list[ToolSelectionResult]) -> dict:
    n = len(results)
    n_correct = sum(r.correct for r in results)
    n_intent_correct = sum(r.intent_correct for r in results)
    return {
        "n_samples": n,
        "tool_accuracy": n_correct / n if n else 0.0,
        "intent_accuracy": n_intent_correct / n if n else 0.0,
        "pass": (n_correct / n if n else 0.0) >= 0.80,
        "failures": [
            {"query_id": r.query_id, "query": r.query[:60],
             "expected": r.expected_tool, "actual": r.actual_tool}
            for r in results if not r.correct
        ],
    }
```

**Tests** (no LLM calls):
```python
def test_extract_first_tool_call():
    from evals.metrics.tool_selection_eval import extract_first_tool_call
    msg = MagicMock()
    msg.tool_calls = [{"name": "recommend_by_genre"}]
    assert extract_first_tool_call([msg]) == "recommend_by_genre"

def test_extract_no_tool_returns_none():
    from evals.metrics.tool_selection_eval import extract_first_tool_call
    msg = MagicMock(); msg.tool_calls = []
    assert extract_first_tool_call([msg]) is None

def test_summarize_tool_selection():
    from evals.metrics.tool_selection_eval import ToolSelectionResult, summarize_tool_selection
    results = [
        ToolSelectionResult("q1", "q", "recommend_by_genre", "recommend_by_genre", True, True),
        ToolSelectionResult("q2", "q", "get_artist_context", "recommend_by_genre", False, False),
    ]
    summary = summarize_tool_selection(results)
    assert summary["tool_accuracy"] == 0.5
    assert summary["pass"] is False
    assert len(summary["failures"]) == 1
```

**Run**: `uv run pytest tests/unit/eval/test_tool_selection_eval.py -v`

**Done when**: `extract_first_tool_call` works; `summarize_tool_selection` computes accuracy.

---

### Step 4: Eval runner — single CLI entry point

**Files**:
- `evals/run_eval.py` (replace/rewrite current `run_local_eval.py`)
- `tests/unit/eval/test_run_eval.py` (new — test loaders/printers only)

**What**: Single entry point running all evals. RAG eval always runs (no LLM).
Tool eval requires `CONFIRM_EXPENSIVE_OPS=True`.

```python
# evals/run_eval.py
"""
Listen-wiseer eval harness.

Usage:
    # RAG keyword eval (no LLM calls, always safe):
    PYTHONPATH=src uv run python -m evals.run_eval --eval rag

    # Tool selection eval (costs money — requires explicit opt-in):
    CONFIRM_EXPENSIVE_OPS=true PYTHONPATH=src uv run python -m evals.run_eval --eval tools

    # Both:
    PYTHONPATH=src uv run python -m evals.run_eval --eval all
"""
```

Loader functions:
```python
def load_rag_samples(path: Path = Path("evals/datasets/smoke_rag.jsonl")) -> list[MusicGoldenSample]:
    ...

def load_tool_samples(path: Path = Path("evals/datasets/smoke_tool_selection.jsonl")) -> list[ToolSelectionSample]:
    ...
```

Pass thresholds: RAG keyword hit rate ≥ 0.8 = PASS; tool accuracy ≥ 0.8 = PASS.

**Tests**:
```python
def test_load_rag_samples():
    from evals.run_eval import load_rag_samples
    samples = load_rag_samples()
    assert len(samples) >= 10

def test_load_tool_samples():
    from evals.run_eval import load_tool_samples
    samples = load_tool_samples()
    assert len(samples) >= 15
```

**Run**: `uv run pytest tests/unit/eval/test_run_eval.py -v`

**CLI smoke**: `PYTHONPATH=src uv run python -m evals.run_eval --eval rag`

**Done when**: Runner prints per-sample results + aggregate PASS/FAIL for RAG eval.

---

### Step 5: Eval notebook

**Files**:
- `notebooks/eda/09_eval.ipynb` (new)

**Sections**:
1. Setup — imports, `configure_logging()`, `MusicRAG()` init
2. Load smoke RAG dataset — print sample count + intent distribution
3. Run RAG keyword eval — per-sample table: query / hit_rate / missing keywords
4. Aggregate: avg hit rate, PASS/FAIL
5. (Commented out) LLM judge — how to enable, estimated cost
6. Load tool selection dataset — show intent distribution
7. Notes: how to add new eval examples, when to graduate from smoke to full dataset

**Commit clean** (no output cells).

**Done when**: Notebook runs clean end-to-end.

---

### Step 6: Regression

```bash
uv run pytest tests/unit/ --tb=short -q
PYTHONPATH=src uv run python -m evals.run_eval --eval rag
```

**Pass**:
- ≥ 280 unit tests pass
- RAG keyword hit rate ≥ 0.8 on smoke dataset

---

## Test Plan

| Step | Command | Verifies |
|------|---------|----------|
| 1 | `uv run pytest tests/unit/eval/test_models.py -v` | Schema + JSONL loading |
| 2 | `uv run pytest tests/unit/eval/test_music_rag_eval.py -v` | Keyword eval logic |
| 3 | `uv run pytest tests/unit/eval/test_tool_selection_eval.py -v` | Tool extraction + accuracy |
| 4 | `uv run pytest tests/unit/eval/test_run_eval.py -v` | Dataset loaders |
| 5 | `uv run pytest tests/unit/ --tb=short -q` | Full regression |
| 6 | `PYTHONPATH=src uv run python -m evals.run_eval --eval rag` | End-to-end RAG eval |

---

## Dependency Map

```
Step 1 (schemas + datasets) ← independent
  ↓
Step 2 (RAG eval) ← needs Step 1 + Phase 5a MusicRAG
  ↓
Step 3 (tool eval) ← needs Step 1 + Phase 5b intent graph
  ↓
Step 4 (runner) ← needs Steps 2 + 3
  ↓
Step 5 (notebook) ← needs Steps 1-4
  ↓
Step 6 (regression) ← needs all
```

---

## Risks & Rollback

### Dataset keyword quality (Step 1)
- **Risk**: Keywords too specific — Wikipedia doesn't use exact term
- **Mitigation**: Broad genre-defining terms only; adjust if first run fails
- **Rollback**: Edit JSONL — no code changes

### LLM cost gate (Step 3)
- **Risk**: `CONFIRM_EXPENSIVE_OPS=True` committed accidentally
- **Mitigation**: Hardcoded `False` in source; env var must be explicitly set in shell
- **Rollback**: Not applicable — gate prevents spend

### Pass threshold (Step 6)
- **Risk**: 0.8 keyword hit rate fails (Wikipedia text varies by subject)
- **Mitigation**: 0.8 is intentionally lenient; adjust threshold if legitimately borderline
- **Rollback**: Lower threshold, not a code issue

---

## Future extensions (not in scope)

- Generate 100+ samples from real conversation logs (once production traffic exists)
- `difficulty: hard` samples — niche artists, multi-hop genre questions
- Trajectory eval — loop detection (add when loop failures are observed)
- LangFuse custom score logging — Phase 6+ once production monitoring is set up
- RAGAS integration — if dataset grows to 50+ samples
