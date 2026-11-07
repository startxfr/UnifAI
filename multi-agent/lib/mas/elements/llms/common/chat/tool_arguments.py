"""Tolerant parsing of tool-call argument strings assembled from a stream."""

from __future__ import annotations

import json
from typing import Any, Dict, List

ARGUMENTS_ERROR_KEY = "_arguments_error"


def is_complete_json(raw: str) -> bool:
    """True when *raw* is one complete JSON document."""
    try:
        json.loads(raw)
    except ValueError:
        return False
    return True


def split_json_objects(raw: str) -> List[Any]:
    """Split a string of back-to-back JSON documents (``{..}{..}``).

    Returns an empty list when the string is not made solely of JSON documents.
    """
    decoder = json.JSONDecoder()
    out: List[Any] = []
    pos, n = 0, len(raw)
    while pos < n:
        while pos < n and raw[pos].isspace():
            pos += 1
        if pos >= n:
            break
        try:
            obj, pos = decoder.raw_decode(raw, pos)
        except ValueError:
            return []
        out.append(obj)
    return out


def drop_blank_argument(args: Any) -> Any:
    """Remove the ``""`` key a model sends with an empty value (``{"": ""}``) for a tool that takes no argument.

    Seen with some models on parameterless tools (an A2A approval showed ``tool_args {"": ""}``): the call carries no
    information, but the stray key fails the argument validation of the tool or is shown to the human as an argument.
    A ``""`` key with a real value is kept, it is a model error that must surface.
    """
    if isinstance(args, dict) and "" in args and args[""] in ("", None):
        return {k: v for k, v in args.items() if k != ""}
    return args


def parse_tool_arguments(raw: str) -> Dict[str, Any]:
    """Parse *raw* into an argument dict without ever raising.

    Empty input gives ``{}``.  Invalid or non-object JSON gives a dict holding
    a single ``_arguments_error`` entry so the failure surfaces as a tool-call
    error instead of an unhandled exception in the agent loop.
    """
    if not raw or not raw.strip():
        return {}
    try:
        value = json.loads(raw)
    except ValueError as exc:
        return {ARGUMENTS_ERROR_KEY: f"tool call arguments are not valid JSON ({exc}): {raw[:200]!r}"}
    if not isinstance(value, dict):
        return {ARGUMENTS_ERROR_KEY: f"tool call arguments must be a JSON object, got {type(value).__name__}"}
    return drop_blank_argument(value)
