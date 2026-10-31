"""Window over the conversation history an agent sends to its model.

A turn starts at a user message and runs up to the next one (the assistant answers and the tool messages that
follow). The window keeps the most recent turns, at most ``max_turns`` of them and at most ``token_budget``
tokens; the oldest turns are dropped whole, and the newest turn is always kept even when it alone exceeds the
budget. Tokens are estimated at four characters each: the budget bounds the prompt, it does not meter it.
"""
from __future__ import annotations

from typing import List, Optional

from mas.elements.llms.common.chat.message import ChatMessage, Role

CHARS_PER_TOKEN = 4


def estimate_tokens(message: ChatMessage) -> int:
    size = len(message.content or "")
    for call in message.tool_calls or []:
        size += len(str(call.args)) + len(getattr(call, "name", "") or "")
    return size // CHARS_PER_TOKEN + 1


def split_turns(messages: List[ChatMessage]) -> List[List[ChatMessage]]:
    turns: List[List[ChatMessage]] = []
    for message in messages:
        if message.role == Role.USER or not turns:
            turns.append([])
        turns[-1].append(message)
    return turns


def window_history(messages: List[ChatMessage], *, enabled: bool = True, max_turns: Optional[int] = None,
                   token_budget: Optional[int] = None) -> List[ChatMessage]:
    """The messages kept by the window; ``enabled`` False keeps none (the agent sees only the current prompt)."""
    if not enabled:
        return []
    if max_turns is None and token_budget is None:
        return list(messages)
    kept: List[List[ChatMessage]] = []
    used = 0
    for turn in reversed(split_turns(messages)):
        if max_turns is not None and len(kept) >= max_turns:
            break
        cost = sum(estimate_tokens(m) for m in turn)
        if token_budget is not None and kept and used + cost > token_budget:
            break
        kept.append(turn)
        used += cost
    return [m for turn in reversed(kept) for m in turn]


def window_results(results: list, *, token_budget: Optional[int] = None) -> list:
    """The most recent agent results that fit ``token_budget`` (estimated like the history); the newest is always kept.

    The workspace keeps every result of a thread and an agent's prompt lists them all, so without a bound the prompt
    grows with each turn. Results carry no turn marker: the budget is the only bound, ``max_turns`` does not apply.
    """
    if token_budget is None:
        return list(results)
    kept: list = []
    used = 0
    for result in reversed(results):
        cost = len(result.content or "") // CHARS_PER_TOKEN + 1
        if kept and used + cost > token_budget:
            break
        kept.append(result)
        used += cost
    return list(reversed(kept))
