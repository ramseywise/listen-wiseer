from __future__ import annotations

from langmem import create_manage_memory_tool, create_search_memory_tool

_TASTE_NAMESPACE = ("enoa", "{langgraph_user_id}", "taste")

manage_taste_memory = create_manage_memory_tool(
    _TASTE_NAMESPACE,
    name="manage_taste_memory",
    instructions=(
        "Proactively call this tool when you identify a user's musical taste preference, "
        "genre affinity, or explicit request to remember something about their listening habits. "
        "Examples: 'prefers acoustic over electronic', 'loves zouk', 'dislikes BPM > 140'."
    ),
)

search_taste_memory = create_search_memory_tool(
    _TASTE_NAMESPACE,
    name="search_taste_memory",
    instructions=(
        "Search stored facts about the user's musical taste. "
        "Use this to recall user preferences before making recommendations."
    ),
)
