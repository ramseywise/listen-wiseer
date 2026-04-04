"""LangGraph node functions for the listen-wiseer ReAct agent."""

from __future__ import annotations

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import SystemMessage

from agent.state import AgentState
from agent.tools import ALL_TOOLS
from utils.config import settings
from utils.logging import get_logger

log = get_logger(__name__)

# ---------------------------------------------------------------------------
# LLM — shared across nodes, instantiated once at module load
# ---------------------------------------------------------------------------

_llm = ChatAnthropic(
    model=settings.anthropic_model,
    api_key=settings.anthropic_api_key,
)
_llm_with_tools = _llm.bind_tools(ALL_TOOLS)

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """\
You are listen-wiseer, a personal music assistant.

You help users explore their Spotify listening history, discover new music
through content-based recommendations, and learn about artists.

## Tool usage

- **recommend_similar_tracks** — "find tracks like X" (needs a Spotify track ID)
- **recommend_for_artist** — "recommend tracks by/like artist X" (needs a Spotify artist ID)
- **recommend_by_genre** — genre-based requests, e.g. "zouk", "bossa nova", "house" (pass the genre name)
- **recommend_for_playlist** — playlist-based recommendations (needs a Spotify playlist ID)
- **get_recently_played** — see what the user has been listening to
- **search_tracks** — find a specific track or artist on Spotify (returns track IDs you can feed into other tools)

If the user gives you an artist/track *name* instead of a Spotify ID, use
**search_tracks** first to resolve the ID, then call the appropriate recommend tool.

## Response style

- Present recommendations as a numbered list with brief notes
- Be concise — 3-5 sentences unless the user asks for detail
- If a tool returns no results, explain why and suggest alternatives
"""


# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------


def agent_node(state: AgentState) -> AgentState:
    """Core agent node — call the LLM with tools bound.

    The LLM decides whether to call a tool or produce a final answer.
    """
    messages = [SystemMessage(content=SYSTEM_PROMPT)] + state["messages"]
    response = _llm_with_tools.invoke(messages)
    return {"messages": [response]}


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------


def route_after_agent(state: AgentState) -> str:
    """Route after the agent node: tools if tool_calls present, else END."""
    last = state["messages"][-1]
    if hasattr(last, "tool_calls") and last.tool_calls:
        return "call_tools"
    return "__end__"
