"""Background prompt optimizer for per-user procedural memory.

After a conversation ends, this module reviews the trajectory and
optionally updates the user's system-prompt strategy in the store.

Uses langmem's ``create_multi_prompt_optimizer`` with the ``metaprompt``
strategy to review conversation trajectories and evolve per-user prompts.
"""

from __future__ import annotations

import asyncio

from langchain_core.messages import BaseMessage
from langgraph.store.memory import InMemoryStore
from langmem import Prompt, create_multi_prompt_optimizer

from agent.memory_store import get_procedural_prompt, update_procedural_prompt
from utils.config import settings
from utils.logging import get_logger

log = get_logger(__name__)

_DEFAULT_INSTRUCTIONS = "No user-specific instructions yet."

# Lazy singleton — created on first use to avoid import-time LLM instantiation
_optimizer = None


def _get_optimizer():
    global _optimizer  # noqa: PLW0603
    if _optimizer is None:
        _optimizer = create_multi_prompt_optimizer(
            f"anthropic:{settings.anthropic_model}",
            kind="metaprompt",
        )
    return _optimizer


async def optimize_prompt(
    user_id: str,
    messages: list[BaseMessage],
    store: InMemoryStore,
) -> None:
    """Review a conversation and update procedural memory if warranted.

    Runs langmem's multi-prompt optimizer to analyze the trajectory.
    Intended to be called as a fire-and-forget background task.
    """
    if len(messages) < 4:
        # Too short to learn from
        return

    current = await get_procedural_prompt(user_id, store) or _DEFAULT_INSTRUCTIONS

    # Filter to content-bearing messages for the trajectory
    trajectory_messages = [msg for msg in messages if getattr(msg, "content", "")]

    try:
        optimizer = _get_optimizer()
        result = await optimizer.ainvoke(
            {
                "trajectories": [{"messages": trajectory_messages}],
                "prompts": [
                    Prompt(
                        name="user_strategy",
                        prompt=current,
                        when_to_update=(
                            "Update when the user expresses genre/mood preferences, "
                            "communication style preferences, recommendation format preferences, "
                            "or explicitly asks the agent to remember or change something."
                        ),
                        update_instructions=(
                            "Keep instructions concise (under 200 words). Focus only on "
                            "user-specific observations from conversations. Do not include "
                            "generic advice."
                        ),
                    ),
                ],
            }
        )

        if result and result[0]["prompt"] != current:
            new_instructions = result[0]["prompt"]
            await update_procedural_prompt(user_id, new_instructions, store)
            log.info(
                "agent.optimizer.updated",
                user_id=user_id,
                instruction_len=len(new_instructions),
            )
        else:
            log.debug("agent.optimizer.no_change", user_id=user_id)
    except Exception as exc:
        log.error("agent.optimizer.failed", error=str(exc), user_id=user_id)


def schedule_optimization(
    user_id: str,
    messages: list[BaseMessage],
    store: InMemoryStore,
) -> asyncio.Task | None:
    """Fire-and-forget the optimizer as a background task.

    Returns the task handle (for testing), or None if no event loop is running.
    """
    try:
        loop = asyncio.get_running_loop()
        task = loop.create_task(
            optimize_prompt(user_id, messages, store),
            name=f"optimizer-{user_id}",
        )
        log.debug("agent.optimizer.scheduled", user_id=user_id)
        return task
    except RuntimeError:
        log.warning("agent.optimizer.no_loop", user_id=user_id)
        return None
