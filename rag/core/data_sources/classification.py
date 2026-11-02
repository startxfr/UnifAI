"""Data classification a source may carry: stored on each chunk so a consumer can raise the level of a turn."""
from __future__ import annotations

from typing import Any

CLASSIFICATIONS = ("C1", "C2", "C3", "C4")


def source_classification(instance: dict[str, Any]) -> str:
    """The classification asked for by a registration ("" = none declared)."""
    return str(instance.get("classification") or "").strip()


def classification_error(value: str) -> str | None:
    """Why a classification is refused, None when it is empty or one of C1 to C4."""
    if value and value not in CLASSIFICATIONS:
        return f"classification must be one of {', '.join(CLASSIFICATIONS)}"
    return None


def chunk_classification(settings: dict[str, Any]) -> dict[str, str]:
    """The metadata entry put on every chunk of a source (nothing when the source declares none)."""
    value = str(settings.get("classification") or "")
    return {"classification": value} if value else {}


def classification_changed(settings: dict[str, Any]) -> bool:
    """True when the pages were ingested under another classification: every page must be embedded again."""
    return str(settings.get("ingested_classification") or "") != str(settings.get("classification") or "")
