# Plan: Phase 5b — Intent Routing + Query Understanding
Date: 2026-04-05
Predecessor: Phase 5a (RAG core adaptation)
Next: Phase 5c (eval harness)

---

## Context & What Exists

`rag_core/orchestration/query_understanding.py` exists but is built for Danish
customer support (Danish keywords, intents: factual/procedural/exploratory/troubleshooting).
`rag_core/orchestration/router.py` has a `QueryAnalyzer` + `RoutingDecision` structure.

The current agent (`src/agent/nodes.py`) relies entirely on the LLM to pick the
right tool via ReAct reasoning — no explicit intent classification. This works for
simple queries but is unreliable for multi-step or ambiguous requests.

**Goal**: Add a lightweight intent router to the agent. Before the ReAct loop,
classify the user's query into a `MusicIntent` and inject it into the agent's
context so it can make better tool choices. Also adapt `query_understanding.py`
for music-specific query expansion and entity extraction.

**Design principle**: The router is **a node in the agent graph**, not a separate
sub-graph. It runs before the ReAct `agent` node and adds `intent` + `entities`
to agent state. The agent still makes the final tool choice — the intent is a
hint, not a hard route.

---

## Out of Scope

- Spotify `/recommendations` API — Phase 6
- Eval harness — Phase 5c
- Streaming / token-by-token responses — later
- Full CRAG retry loop in production agent — Phase 5c eval will determine if needed

---

## Steps

### Step 1: Music query understanding — adapt `query_understanding.py`

**Files**:
- `src/rag_core/orchestration/query_understanding.py` (replace Danish patterns with music patterns)
- `tests/unit/rag/test_query_understanding.py` (new)

**What**: Replace Danish customer-support intent keywords with music-domain patterns.
Keep `QueryAnalysis` dataclass and `QueryAnalyzer` class — adapt internals.

**New intent patterns** (replace existing `INTENT_PATTERNS`):
```python
INTENT_PATTERNS = {
    "artist_info": {
        "keywords": [
            "who is", "tell me about", "what do you know about", "biography",
            "history of", "background on", "artist info", "about the band",
            "when did", "where is", "discography", "influences", "style of",
        ],
    },
    "genre_info": {
        "keywords": [
            "what is", "explain", "describe", "genre", "subgenre", "music style",
            "what does", "sounds like", "characteristics of", "origins of",
            "bossa nova", "zouk", "afrobeats", "electronic", "jazz",
        ],
    },
    "recommendation": {
        "keywords": [
            "recommend", "suggest", "find me", "similar to", "like", "sounds like",
            "more of", "playlist", "tracks like", "what should i listen to",
            "based on", "fans of", "if i like",
        ],
    },
    "history": {
        "keywords": [
            "recently played", "what have i been", "my listening", "my history",
            "i've been listening", "last week", "my taste", "my playlists",
            "what did i listen", "my spotify",
        ],
    },
}
```

**Entity extraction** — update `extract_entities()` to extract music entities:
```python
# entity types: artists, genres, tracks, moods, time_periods
ENTITY_PATTERNS = {
    "mood": ["happy", "sad", "energetic", "chill", "melancholic", "upbeat", "dark", "romantic"],
    "time_period": ["70s", "80s", "90s", "2000s", "recent", "classic", "vintage", "new"],
    "context": ["workout", "study", "party", "sleep", "focus", "driving", "dinner"],
}
```

**Query expansion** — `expand_query()` adds music synonyms:
```python
MUSIC_SYNONYMS = {
    "track": ["song", "tune", "record"],
    "artist": ["musician", "band", "singer", "performer"],
    "similar": ["like", "sounds like", "in the style of", "reminiscent of"],
}
```

**Tests**:
```python
def test_classify_intent_artist():
    from rag_core.orchestration.query_understanding import QueryAnalyzer
    analyzer = QueryAnalyzer()
    result = analyzer.analyze("who is Aphex Twin?")
    assert result.intent == "artist_info"

def test_classify_intent_recommendation():
    from rag_core.orchestration.query_understanding import QueryAnalyzer
    analyzer = QueryAnalyzer()
    result = analyzer.analyze("recommend me tracks similar to Boards of Canada")
    assert result.intent == "recommendation"

def test_extract_entities_mood():
    from rag_core.orchestration.query_understanding import QueryAnalyzer
    analyzer = QueryAnalyzer()
    result = analyzer.analyze("suggest some chill tracks for studying")
    assert "mood" in result.entities
    assert "chill" in result.entities["mood"]

def test_expand_query_adds_synonyms():
    from rag_core.orchestration.query_understanding import QueryAnalyzer
    analyzer = QueryAnalyzer()
    result = analyzer.analyze("find me songs similar to Radiohead")
    assert result.expanded_query  # not empty
```

**Run**: `uv run pytest tests/unit/rag/test_query_understanding.py -v`

**Done when**: Intent classification correctly routes artist/genre/rec/history queries.

---

### Step 2: Intent router node — add to agent graph

**Files**:
- `src/agent/state.py` (add `intent`, `entities`, `query_variants` fields to `AgentState`)
- `src/agent/nodes.py` (add `classify_intent_node`, update system prompt injection)
- `src/agent/graph.py` (insert `classify_intent` node before `agent` node)
- `tests/unit/agent/test_graph.py` (extend)

**What**: Add a pre-agent classification step. Classifies intent + extracts entities
using `QueryAnalyzer` (no LLM call — pure regex/keyword, fast).
Injects classification result into the agent's system prompt context.

**AgentState additions**:
```python
# src/agent/state.py — add to AgentState TypedDict:
intent: str           # classified intent ("artist_info", "recommendation", etc.)
entities: dict        # extracted entities {"mood": [...], "time_period": [...]}
query_variants: list[str]  # expanded query variants
```

**New node** (`nodes.py`):
```python
# src/agent/nodes.py — add:
from rag_core.orchestration.query_understanding import QueryAnalyzer

_query_analyzer = QueryAnalyzer()

# Intent → tool hint mapping for system prompt injection
_INTENT_TOOL_HINTS: dict[str, str] = {
    "artist_info": "Use get_artist_context to answer questions about this artist.",
    "genre_info": "Use get_artist_context with the genre name to get genre info.",
    "recommendation": "Use recommend_* tools based on the type of recommendation requested.",
    "history": "Use get_recently_played to fetch the user's listening history.",
    "chit_chat": "Respond directly without using tools.",
}


async def classify_intent(state: AgentState) -> dict:
    """Classify query intent and extract entities. No LLM call."""
    messages = state.get("messages", [])
    query = ""
    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            query = str(msg.content)
            break

    analysis = _query_analyzer.analyze(query)
    log.info(
        "agent.classify_intent",
        intent=analysis.intent,
        entities=analysis.entities,
        complexity=analysis.complexity,
    )
    return {
        "intent": analysis.intent,
        "entities": analysis.entities,
        "query_variants": analysis.sub_queries[:2],
    }
```

**System prompt update** — inject intent hint into agent context (`nodes.py`):
```python
# In the agent node (before LLM call), inject intent context:
intent = state.get("intent", "")
entities = state.get("entities", {})
intent_hint = _INTENT_TOOL_HINTS.get(intent, "")
if intent_hint:
    # Prepend to system prompt or inject as context message
    system = SYSTEM_PROMPT + f"\n\nQuery classification: {intent}\n{intent_hint}"
```

**Graph update** (`graph.py`):
```python
# Add before agent node:
graph.add_node("classify_intent", classify_intent)
graph.set_entry_point("classify_intent")
graph.add_edge("classify_intent", "agent")
# Remove: graph.set_entry_point("agent")
```

**Tests**:
```python
def test_classify_intent_node_adds_fields():
    """classify_intent returns intent + entities."""
    state = {"messages": [HumanMessage(content="who is Aphex Twin?")]}
    result = asyncio.run(classify_intent(state))
    assert result["intent"] == "artist_info"
    assert "query_variants" in result

def test_graph_entry_is_classify_intent():
    from agent.graph import graph
    # Verify the compiled graph starts at classify_intent
    assert "classify_intent" in graph.get_graph().nodes
```

**Run**: `uv run pytest tests/unit/agent/ -v`

**Done when**: Graph starts at `classify_intent`; intent field populated in state.

---

### Step 3: Query rewriting for multi-turn context

**Files**:
- `src/agent/nodes.py` (add `rewrite_query_node` for coreference resolution)
- `tests/unit/agent/test_graph_nodes.py` (extend)

**What**: On multi-turn conversations, rewrite the query to be standalone
(resolve "it", "them", "that artist"). Single-turn queries pass through unchanged.
Uses Haiku (cheap). Runs after `classify_intent`, before `agent` node.

**Node**:
```python
async def rewrite_query(state: AgentState) -> dict:
    """Rewrite query as standalone if multi-turn conversation."""
    messages = state.get("messages", [])
    if len(messages) <= 1:
        return {}  # single turn — no rewrite needed

    query = ""
    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            query = str(msg.content)
            break

    # Only rewrite if query contains pronouns suggesting coreference
    coreference_signals = ["it", "they", "them", "that", "this", "the artist", "the band", "their"]
    if not any(s in query.lower() for s in coreference_signals):
        return {}  # no rewrite needed

    history = "\n".join(
        f"{'User' if isinstance(m, HumanMessage) else 'Assistant'}: {m.content}"
        for m in messages[-5:-1]
    )
    prompt = (
        f"Rewrite the following question as a standalone question that doesn't require "
        f"the conversation history to understand. Only output the rewritten question, "
        f"nothing else.\n\n"
        f"History:\n{history}\n\n"
        f"Question: {query}\n\n"
        f"Standalone question:"
    )
    response = await _haiku.ainvoke([HumanMessage(content=prompt)])
    rewritten = str(response.content).strip()
    log.info("agent.rewrite_query", original=query, rewritten=rewritten)

    # Inject rewritten query as new HumanMessage at end of messages
    new_messages = list(messages[:-1]) + [HumanMessage(content=rewritten)]
    return {"messages": new_messages}
```

**Updated graph** (`graph.py`):
```
classify_intent → rewrite_query → agent → tools → agent → ... → synthesize → END
```

**Tests**:
```python
def test_rewrite_query_single_turn_passthrough():
    state = {"messages": [HumanMessage(content="who is Aphex Twin?")]}
    result = asyncio.run(rewrite_query(state))
    assert result == {}  # no rewrite for single turn

def test_rewrite_query_skips_without_coreference():
    state = {"messages": [
        HumanMessage(content="who is Aphex Twin?"),
        AIMessage(content="Aphex Twin is..."),
        HumanMessage(content="what genre is zouk?"),  # no coreference
    ]}
    result = asyncio.run(rewrite_query(state))
    assert result == {}
```

**Run**: `uv run pytest tests/unit/agent/test_graph_nodes.py -v`

**Done when**: Rewrite fires on pronoun-bearing multi-turn; single-turn is unchanged.

---

### Step 4: Related artists tool

**Files**:
- `src/spotify/fetch.py` (add `fetch_related_artists`)
- `src/agent/tools.py` (add `get_related_artists_tool`)
- `tests/unit/test_spotify_client.py` (extend)
- `tests/unit/agent/test_tools.py` (extend)

**What**: "Who sounds like Radiohead?" → `search_tracks` (get artist ID) →
`get_related_artists` → list of similar artists.

```python
# src/spotify/fetch.py — add:
def fetch_related_artists(client: SpotifyClient, artist_id: str) -> list[dict]:
    """Fetch up to 20 related artists for artist_id."""
    response = client.get(f"artists/{artist_id}/related-artists")
    artists = response.get("artists", [])
    log.info("spotify.fetch_related_artists", artist_id=artist_id, n=len(artists))
    return [
        {"id": a["id"], "name": a["name"], "genres": a.get("genres", [])[:3]}
        for a in artists
    ]

# src/agent/tools.py — add:
def _get_related_artists(artist_id: str) -> str:
    """Find artists similar to a given Spotify artist ID."""
    try:
        artists = fetch_related_artists(_get_client(), artist_id)
        if not artists:
            return f"No related artists found for {artist_id}"
        return "\n".join(
            f"- {a['name']} ({', '.join(a['genres']) or 'unknown genre'})"
            for a in artists
        )
    except Exception as exc:
        log.warning("tool.get_related_artists.failed", error=str(exc))
        return f"Failed to fetch related artists: {exc}"

get_related_artists_tool = StructuredTool.from_function(
    _get_related_artists,
    name="get_related_artists",
    description=(
        "Find artists that sound similar to a given Spotify artist ID. "
        "Use for 'who sounds like X?' or 'artists similar to X' queries. "
        "Requires a Spotify artist ID — use search_tracks first to find the ID."
    ),
)
ALL_TOOLS.append(get_related_artists_tool)  # now 10 tools
```

**Tests**:
```python
def test_fetch_related_artists_empty():
    mock_client = MagicMock()
    mock_client.get.return_value = {"artists": []}
    assert fetch_related_artists(mock_client, "some_id") == []

def test_fetch_related_artists_formats_genres():
    mock_client = MagicMock()
    mock_client.get.return_value = {"artists": [
        {"id": "x", "name": "Boards of Canada", "genres": ["ambient", "electronic"]}
    ]}
    result = fetch_related_artists(mock_client, "some_id")
    assert result[0]["name"] == "Boards of Canada"
```

**Run**: `uv run pytest tests/unit/agent/test_tools.py tests/unit/test_spotify_client.py -v`

**Done when**: `ALL_TOOLS` has 10 tools; `fetch_related_artists` tested.

---

### Step 5: End-to-end validation

**Manual smoke** (run `make app`):
1. `"who is Aphex Twin?"` → `classify_intent` → `artist_info` → `get_artist_context` → bio
2. `"recommend me something similar"` (after above) → `rewrite_query` → `"recommend something similar to Aphex Twin"` → `recommend_for_artist`
3. `"who sounds like Radiohead?"` → `get_related_artists`
4. `"recommend zouk tracks"` → `recommend_by_genre` (regression — still works)

**Done when**: All 4 smoke queries produce useful responses.

---

## Test Plan

| Step | Command | Verifies |
|------|---------|----------|
| 1 | `uv run pytest tests/unit/rag/test_query_understanding.py -v` | Music intent classification |
| 2 | `uv run pytest tests/unit/agent/test_graph.py -v` | Graph has classify_intent node |
| 3 | `uv run pytest tests/unit/agent/test_graph_nodes.py -v` | Rewrite logic |
| 4 | `uv run pytest tests/unit/agent/test_tools.py tests/unit/test_spotify_client.py -v` | Related artists |
| 5 | `uv run pytest tests/unit/ --tb=short -q` | Full regression |

---

## Dependency Map

```
Step 1 (query_understanding) ← independent of 5a, but benefits from new Intent enum
  ↓
Step 2 (intent node + graph) ← needs Step 1 + 5a agent state
  ↓
Step 3 (rewrite node) ← needs Step 2 (graph already updated)
  ↓
Step 4 (related artists) ← independent of Steps 1-3; needs 5a tools.py
  ↓
Step 5 (smoke) ← needs all steps
```

---

## Risks & Rollback

### Intent classification noise (Step 2)
- **Risk**: Keyword-based classification misroutes "what does zouk sound like?" as `artist_info`
- **Mitigation**: Hint injection is advisory — ReAct agent still makes final tool choice
- **Rollback**: Remove `classify_intent` node from graph; revert `set_entry_point`

### Query rewrite adds latency (Step 3)
- **Risk**: Every multi-turn query now adds 1 Haiku call (~200ms)
- **Mitigation**: Coreference signal check before calling LLM; single-turn skips entirely
- **Rollback**: Remove `rewrite_query` from graph

### `ALL_TOOLS` count grows (Steps 4)
- **Risk**: More tools → more tokens in system prompt → LLM confused about which to pick
- **Mitigation**: Tool descriptions are precise and non-overlapping; intent hint focuses selection
- **Rollback**: Remove tool from `ALL_TOOLS`
