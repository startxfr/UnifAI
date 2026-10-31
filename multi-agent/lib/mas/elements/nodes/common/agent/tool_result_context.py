"""What of a tool result enters the model's context.

A tool can return a rendered image (``data_base64`` / ``b64_json``): a 57 KB SVG is ~30k prompt tokens on every
following model call, for nothing the model can read. The full result stays in the observation step (the UI still
shows it); only the TOOL message sent to the model is slimmed: binary payloads become a short marker, and any
result over ``MAS_TOOL_RESULT_MAX_TOKENS`` (default 8000, 0 = no cap; tokens = chars / 4) is truncated.
"""
from __future__ import annotations

import json
import os
import re
from typing import Any

BINARY_KEYS = {"data_base64", "b64_json", "image_base64", "base64"}
MIN_BINARY_CHARS = 512
DEFAULT_MAX_TOKENS = 8000
_CHARS_PER_TOKEN = 4
_BASE64_RUN = re.compile(r"[A-Za-z0-9+/]{2000,}={0,2}")


def max_tool_result_tokens() -> int:
    try:
        return max(0, int(os.environ.get("MAS_TOOL_RESULT_MAX_TOKENS", DEFAULT_MAX_TOKENS)))
    except ValueError:
        return DEFAULT_MAX_TOKENS


def _marker(mime: Any, size: int, alt: Any) -> str:
    kind = str(mime) if mime else "binary"
    note = f", alt: {alt}" if alt else ""
    return f"[{kind} payload, {size // 1024 or 1} KB, shown to the user, not in your context{note}]"


def _slim(value: Any) -> Any:
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            if key in BINARY_KEYS and isinstance(item, str) and len(item) >= MIN_BINARY_CHARS:
                out[key] = _marker(value.get("mime_type") or value.get("mime"), len(item), value.get("alt"))
            else:
                out[key] = _slim(item)
        return out
    if isinstance(value, list):
        return [_slim(item) for item in value]
    return value


def tool_output_for_model(output: Any, max_tokens: int | None = None) -> str:
    """The text of ``output`` for the TOOL message: binary payloads replaced, then capped."""
    parsed: Any = output
    if isinstance(output, str):
        stripped = output.lstrip()
        if stripped[:1] in "{[":
            try:
                parsed = json.loads(stripped)
            except ValueError:
                parsed = output
    text = str(output)
    if isinstance(parsed, (dict, list)):
        slimmed = _slim(parsed)
        if slimmed != parsed:  # unchanged results keep their original rendering
            text = json.dumps(slimmed, ensure_ascii=False, default=str)
    # Not JSON (a Python repr, a log line): drop any long base64 run left.
    text = _BASE64_RUN.sub(lambda m: f"[base64 data, {len(m.group(0)) // 1024 or 1} KB, not in your context]", text)
    limit = max_tool_result_tokens() if max_tokens is None else max_tokens
    if limit and len(text) > limit * _CHARS_PER_TOKEN:
        kept = limit * _CHARS_PER_TOKEN
        text = text[:kept] + f"\n[tool result truncated: {len(text) - kept} more characters not shown]"
    return text
