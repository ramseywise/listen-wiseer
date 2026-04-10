from __future__ import annotations

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from schemas.conversation import RAGState
from schemas.retrieval import Intent, RankedChunk

SONNET_MODEL = "claude-sonnet-4-6"

_DIRECT_INTENTS = {Intent.CHIT_CHAT, Intent.OUT_OF_SCOPE}

SYSTEM_PROMPTS: dict[Intent, str] = {
    Intent.ARTIST_INFO: (
        "You are a knowledgeable music assistant. "
        "Provide clear, engaging answers about the artist based on the provided context. "
        "Include interesting facts about their career, discography, and musical style."
    ),
    Intent.GENRE_INFO: (
        "You are a knowledgeable music assistant. "
        "Explain the genre clearly based on the provided context. "
        "Cover its origins, key characteristics, notable artists, and evolution."
    ),
    Intent.RECOMMENDATION: (
        "You are a helpful music recommendation assistant. "
        "Suggest artists, albums, or tracks based on the context and the user's request. "
        "Explain why each recommendation fits."
    ),
    Intent.HISTORY: (
        "You are a personal music assistant. "
        "Summarize the user's listening history and highlight patterns or trends."
    ),
    Intent.CHIT_CHAT: ("You are a friendly music assistant. Reply briefly and warmly."),
    Intent.OUT_OF_SCOPE: (
        "You are a music assistant. "
        "Politely explain that the question is outside your area of expertise, "
        "and suggest asking about artists, genres, or music recommendations instead."
    ),
}


def build_prompt(
    state: RAGState,
    ranked_chunks: list[RankedChunk],
) -> tuple[str, list[dict]]:
    """Build (system_prompt, messages) for the generation LLM call.

    Direct intents (chit_chat, out_of_scope) return the full conversation
    history with no retrieval context injected.

    Retrieval intents replace the last HumanMessage with a grounded version
    that prepends ``[Source: url]\\ntext`` blocks, enabling the model to
    cite sources accurately.
    """
    intent: Intent = state.get("intent", Intent.ARTIST_INFO)
    messages = list(state.get("messages", []))
    query: str = state.get("query", "")

    system_prompt = SYSTEM_PROMPTS.get(intent, SYSTEM_PROMPTS[Intent.ARTIST_INFO])

    if intent in _DIRECT_INTENTS or not ranked_chunks:
        user_content = query
    else:
        context_blocks = "\n---\n".join(
            f"[Source: {rc.chunk.metadata.url}]\n{rc.chunk.text}" for rc in ranked_chunks
        )
        user_content = f"{context_blocks}\n\nQuestion: {query}"

    # Preserve conversation history; swap in the grounded user message at the end
    history = [m for m in messages if not isinstance(m, HumanMessage)]
    history.append(HumanMessage(content=user_content))

    return system_prompt, [{"role": "user", "content": user_content}]


async def call_llm(
    llm: ChatAnthropic,
    system: str,
    messages: list[dict],
) -> str:
    """Invoke Claude and return the response text.

    Converts (system, messages) into LangChain message objects so the
    CallbackHandler can capture LLM spans (model, tokens, latency).
    """
    if not messages:
        raise ValueError("call_llm requires at least one message")
    lc_messages = [
        SystemMessage(content=system),
        HumanMessage(content=messages[0]["content"]),
    ]
    response: AIMessage = await llm.ainvoke(lc_messages)
    return str(response.content).strip()


def extract_citations(ranked_chunks: list[RankedChunk]) -> list[dict]:
    """Deduplicate and return source citations from ranked chunks.

    Returns:
        List of ``{url, title}`` dicts, one per unique URL.
    """
    seen: set[str] = set()
    citations: list[dict] = []
    for rc in ranked_chunks:
        url = rc.chunk.metadata.url
        if url and url not in seen:
            seen.add(url)
            citations.append({"url": url, "title": rc.chunk.metadata.title})
    return citations
