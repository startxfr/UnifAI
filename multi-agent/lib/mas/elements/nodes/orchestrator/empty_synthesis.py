"""An orchestrator whose own final message is empty answers with what the delegated agents returned.

A model that ends its last turn with no text (reasoning only, or a cut generation) gave a delegating turn an EMPTY
reply on demo333 although the delegation had succeeded (zuno-demo-da, 0.1.54, about 1 delegating turn in 5).
"""

from typing import Iterable, Optional

EMPTY_VALUES = ("", "none", "null")


def is_empty_answer(content: Optional[str]) -> bool:
    return content is None or content.strip().lower() in EMPTY_VALUES


def delegated_answers(items: Iterable) -> Optional[str]:
    """The answers the delegated agents returned for the work items, joined, or None when there is none."""
    parts = []
    for item in items:
        result = getattr(item, "result", None)
        for exchange in getattr(result, "delegations", None) or []:
            text = (getattr(exchange, "response_content", None) or "").strip()
            if text and text not in parts:
                parts.append(text)
    return "\n\n".join(parts) if parts else None
