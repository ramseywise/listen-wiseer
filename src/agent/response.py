"""Final response formatting — extracts structured data from the last AI message."""

from __future__ import annotations

import re

from langchain_core.messages import AIMessage, HumanMessage

from agent.state import AgentState

_TRACK_LINE_RE = re.compile(
    r"^\d+\.\s+(.+?)(?:\s+\[(?:spotify:track:)?[A-Za-z0-9]+\])?$",
    re.MULTILINE,
)

_SUGGESTION_TEMPLATES: dict[str, list[str]] = {
    "recommendation": [
        "Want me to save these as a Spotify playlist?",
        "Should I find more tracks like one of these?",
        "Want to explore the artist behind any of these?",
    ],
    "history": [
        "Want recommendations based on your top tracks?",
        "Should I find artists similar to your top ones?",
        "Want to see how your taste has changed over time?",
    ],
    "explore_my_taste": [
        "Want recommendations based on these artists?",
        "Should I find artists you might not know yet?",
    ],
    "artist_info": [
        "Want to hear their top tracks?",
        "Should I find artists similar to them?",
        "Want recommendations in this style?",
    ],
    "discover": [
        "Want to save any of these to a playlist?",
        "Should I dig deeper into any of these artists?",
    ],
}


def format_response(state: AgentState) -> dict:
    """Extract structured data from the final AI message.

    Populates ``agent_response`` with:
    - ``message``: full text of the AI reply
    - ``track_list``: numbered track names parsed from the response (if any)
    - ``suggestions``: contextual follow-up prompts based on intent
    - ``sources``: cited URLs surfaced by web-search tools, if any (deduped)
    """
    messages = state.get("messages", [])
    last = next((m for m in reversed(messages) if isinstance(m, AIMessage)), None)
    if not last:
        return {}

    content = str(last.content)
    track_list = [m.group(1).strip() for m in _TRACK_LINE_RE.finditer(content)]
    intent = state.get("intent", "")
    suggestions = _SUGGESTION_TEMPLATES.get(intent, [])

    sources: list[dict] = []
    seen_urls: set[str] = set()
    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            break  # stop at the current turn's boundary — don't leak prior turns' citations
        if not (hasattr(msg, "type") and msg.type == "tool"):
            continue
        artifact = getattr(msg, "artifact", None)
        if not isinstance(artifact, dict):
            continue
        for source in artifact.get("sources") or []:
            url = source.get("url") if isinstance(source, dict) else None
            if url and url not in seen_urls:
                seen_urls.add(url)
                sources.append(source)

    return {
        "agent_response": {
            "message": content,
            "track_list": track_list[:20],
            "suggestions": suggestions,
            "sources": sources,
        }
    }
