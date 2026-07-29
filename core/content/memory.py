"""core.content.memory — in-memory store for content performance history."""
from __future__ import annotations

from typing import Any

CONTENT_MEMORY: list[dict[str, Any]] = []


def store(entry: dict[str, Any]) -> None:
    """Append *entry* to the content performance memory."""
    CONTENT_MEMORY.append(entry)


def get_all() -> list[dict[str, Any]]:
    """Return all stored content performance entries."""
    return list(CONTENT_MEMORY)


def clear() -> None:
    """Clear the in-memory store (useful in tests)."""
    CONTENT_MEMORY.clear()
