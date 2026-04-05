from __future__ import annotations

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from schemas.conversation import RAGState
from schemas.retrieval import GradedChunk, Intent

SONNET_MODEL = "claude-sonnet-4-6"

_DIRECT_INTENTS = {Intent.CHIT_CHAT, Intent.OUT_OF_SCOPE}

SYSTEM_PROMPTS: dict[Intent, str] = {
    Intent.HOW_TO: (
        "Du er en hjælpsom supportassistent. "
        "Giv tydelige, trin-for-trin instruktioner baseret på den medfølgende dokumentation."
    ),
    Intent.TROUBLESHOOT: (
        "Du er en teknisk supportassistent. "
        "Analyser problemet og giv løsningsforslag baseret på den medfølgende dokumentation."
    ),
    Intent.REFERENCE: (
        "Du er en informationsassistent. "
        "Giv præcise og faktuelle svar baseret på den medfølgende dokumentation."
    ),
    Intent.CHIT_CHAT: "Du er en venlig assistent. Svar kort og høfligt.",
    Intent.OUT_OF_SCOPE: (
        "Du er en supportassistent. "
        "Forklar venligt at spørgsmålet falder uden for dit vidensdomæne."
    ),
}


def build_prompt(
    state: RAGState,
    graded_chunks: list[GradedChunk],
) -> tuple[str, list[dict]]:
    """Build (system_prompt, messages) for the generation LLM call.

    Returns the system string and a single-element messages list.
    Direct intents (chit_chat, out_of_scope) use the raw query with no context.
    Retrieval intents inject the relevant chunk texts as context.
    """
    intent: Intent = state.get("intent", Intent.REFERENCE)
    query: str = state.get("standalone_query") or state.get("query", "")

    system_prompt = SYSTEM_PROMPTS.get(intent, SYSTEM_PROMPTS[Intent.REFERENCE])

    if intent in _DIRECT_INTENTS or not graded_chunks:
        user_prompt = query
    else:
        relevant = [g for g in graded_chunks if g.relevant] or graded_chunks
        context = "\n\n---\n\n".join(g.chunk.text for g in relevant[:5])
        user_prompt = f"Dokumentation:\n{context}\n\nSpørgsmål: {query}"

    return system_prompt, [{"role": "user", "content": user_prompt}]


async def call_llm(
    llm: ChatAnthropic,
    system: str,
    messages: list[dict],
) -> str:
    """Send messages to Claude and return the response text.

    Converts the (system, messages) pair into LangChain message objects so the
    CallbackHandler captures the LLM span (model, tokens, latency) in LangFuse.
    """
    if not messages:
        raise ValueError("call_llm requires at least one message")
    lc_messages = [
        SystemMessage(content=system),
        HumanMessage(content=messages[0]["content"]),
    ]
    response: AIMessage = await llm.ainvoke(lc_messages)
    return str(response.content).strip()
