"""core.playbooks.store — in-memory playbook store."""
from __future__ import annotations

from typing import Any

_PLAYBOOKS: list[dict[str, Any]] = []


def save(playbook: dict[str, Any]) -> None:
    """Append *playbook* to the store."""
    _PLAYBOOKS.append(playbook)


def get_all() -> list[dict[str, Any]]:
    """Return all stored playbooks."""
    return list(_PLAYBOOKS)


def clear() -> None:
    """Clear all stored playbooks (useful in tests)."""
    _PLAYBOOKS.clear()
