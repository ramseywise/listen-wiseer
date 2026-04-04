---
name: langfuse_langgraph_tracing
description: LangFuse with LangGraph only gets full LLM spans when using LangChain model wrappers, not raw SDK clients
type: feedback
---

Use `langchain-anthropic` (`ChatAnthropic`) instead of raw `anthropic.AsyncAnthropic` when LangFuse tracing is a requirement.

**Why:** LangFuse's `CallbackHandler` hooks into LangChain's callback system. With raw Anthropic SDK calls inside LangGraph nodes, LangFuse only captures node-level spans (timing, inputs/outputs). Switching to `ChatAnthropic.ainvoke()` gives full LLM generation spans: model name, input/output token counts, latency per call, prompt+completion.

**How to apply:** Any project using LangGraph + LangFuse should default to `langchain-anthropic` (or `langchain-openai` etc.) from the start. Retrofitting later requires updating all node function signatures, closures in `build_graph`, mock patterns in tests (`messages.create` → `ainvoke`, response type `MagicMock` → `AIMessage`).
