"""
Shared helper for restoring sanitized tool names on inbound LLM messages.

Both the OpenAI Responses API provider and the OpenAI-compatible (Chat
Completions) provider sanitize tool names before sending them to the
external API and need to map them back on the way in.
"""

from __future__ import annotations

import logging
from typing import Dict

from mas.elements.llms.common.chat.message import ChatMessage

logger = logging.getLogger(__name__)

# Some models served through vLLM leak a Harmony control token into the name of a tool call
# ("iem_delegate_task<|channel|>commentary"): the name then matches no tool and nothing is called.
_CONTROL_TOKEN = "<|"


def _restore_name(rev_names: Dict[str, str], name: str) -> str:
    if name in rev_names:
        return rev_names[name]
    if _CONTROL_TOKEN in name:
        base = name.split(_CONTROL_TOKEN, 1)[0]
        restored = rev_names.get(base) or (base if base in rev_names.values() else None)
        if restored:
            logger.warning("llm.tool_name_control_token", extra={"tool_name": name, "restored": restored})
            return restored
    return name


def restore_tool_names(rev_names: Dict[str, str], msg: ChatMessage) -> ChatMessage:
    """Map provider-safe names back to domain names on an inbound message.

    Args:
        rev_names: Reverse mapping from provider-safe name → original domain name.
        msg: The inbound ``ChatMessage`` whose tool_call names to restore.

    Returns the message unchanged when it carries no tool calls.

    A name with a control token appended by the model (``<|channel|>commentary``) is cut at the first ``<|`` and
    restored when what is left is a known tool, with a warning in the log.
    Unknown names (not present in ``rev_names``) are passed through as-is.
    Re-sanitizing them would silently corrupt names from providers that
    didn't go through the sanitizer, and makes the bug harder to detect.
    """
    if not msg.tool_calls:
        return msg
    restored = [
        tc.model_copy(update={"name": _restore_name(rev_names, tc.name)})
        for tc in msg.tool_calls
    ]
    return msg.model_copy(update={"tool_calls": restored})
