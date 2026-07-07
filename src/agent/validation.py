"""Post-tool output validation — checks tool results against classified intent.

No LLM call. Runs after every ToolNode invocation in the graph loop.
"""

from __future__ import annotations

from langchain_core.messages import SystemMessage

from agent.state import AgentState
from utils.config import settings
from utils.logging import get_logger

log = get_logger(__name__)

TOOL_INTENT_MAP: dict[str, set[str]] = {
    "artist_info": {"get_artist_context"},
    "genre_info": {"get_genre_context", "get_artist_context", "recommend_by_genre"},
    "recommendation": {
        "recommend_similar_tracks",
        "recommend_for_artist",
        "recommend_by_genre",
        "recommend_for_playlist",
        "get_related_artists",
        "search_tracks",
    },
    "history": {"get_recently_played", "get_top_tracks", "get_top_artists"},
    "explore_my_taste": {
        "get_top_artists",
        "get_top_tracks",
        "get_taste_analysis",
        "search_taste_memory",
        "manage_taste_memory",
    },
    "discover": {
        "get_spotify_recommendations",
        "get_related_artists",
        "get_top_artists",
    },
}

ERROR_SIGNALS = [
    "failed to fetch",
    "not found",
    "not available",
    "engine not available",
    "no results",
    "no recently played",
    "no tracks found",
]


async def validate_tool_output(state: AgentState) -> dict:
    """Validate tool output against query intent. No LLM call.

    Checks:
    1. Tool returned non-empty, non-error content
    2. Tool aligns with classified intent
    3. Extracted entities appear in output (soft check — log only)

    On failure: injects corrective hint, increments retry counter.
    On success or retry exhausted: passes through.
    """
    messages = state.get("messages", [])
    intent = state.get("intent", "")
    entities = state.get("entities", {})
    retries = state.get("tool_validation_retries", 0)
    max_retries = settings.max_tool_validation_retries

    # Find the most recent ToolMessage(s)
    tool_messages = []
    for msg in reversed(messages):
        if hasattr(msg, "type") and msg.type == "tool":
            tool_messages.append(msg)
        elif tool_messages:
            break  # stop at first non-tool message after collecting tools

    if not tool_messages:
        return {}  # no tool output to validate

    issues: list[str] = []

    # Check 1: Empty or error output
    for tool_msg in tool_messages:
        content = str(tool_msg.content).lower()
        if not content.strip():
            issues.append("Tool returned empty output.")
        elif any(signal in content for signal in ERROR_SIGNALS):
            issues.append(f"Tool may have failed: {str(tool_msg.content)[:100]}")

        # Web-search tools (get_artist_context/get_genre_context) return a
        # confidence tier via response_format="content_and_artifact" — low
        # confidence means don't let the answer stand as stated fact.
        artifact = getattr(tool_msg, "artifact", None)
        if isinstance(artifact, dict) and artifact.get("confidence") == "low":
            issues.append(
                "Web search found low-confidence/no grounded results. "
                "Say so explicitly rather than stating the answer as fact."
            )

    # Check 2: Intent-tool alignment
    expected_tools = TOOL_INTENT_MAP.get(intent, set())
    if expected_tools:
        used_tools = {tool_msg.name for tool_msg in tool_messages if hasattr(tool_msg, "name")}
        if used_tools and not used_tools & expected_tools:
            issues.append(
                f"Intent was '{intent}' but tools used were {used_tools}. "
                f"Expected one of: {expected_tools}."
            )

    # Check 3: Entity coverage (soft — only log, don't fail)
    if entities and not issues:
        all_output = " ".join(str(tool_msg.content).lower() for tool_msg in tool_messages)
        missing_entities = []
        for entity_type, values in entities.items():
            for val in values:
                if val.lower() not in all_output:
                    missing_entities.append(f"{entity_type}:{val}")
        if missing_entities:
            log.debug(
                "agent.validate.entity_gap",
                missing=missing_entities,
                intent=intent,
            )

    if not issues or retries >= max_retries:
        if issues:
            log.warning(
                "agent.validate.issues_exhausted",
                issues=issues,
                retries=retries,
            )
        return {}  # pass through

    # Inject corrective hint
    hint = (
        f"[Validation] The previous tool output may not fully address the query. "
        f"Issues: {'; '.join(issues)} "
        f"Consider using a different tool or approach."
    )
    log.info("agent.validate.retry", issues=issues, retry=retries + 1)
    return {
        "messages": [SystemMessage(content=hint)],
        "tool_validation_retries": retries + 1,
    }
