"""backend.workspaces.registry — durable ClientWorkspace catalog.

Single JSON file under state/ (state_path/save_json_atomic/load_json — the
same idiom PatternStore/PlaybookMemory/CalibrationStore already use). No new
persistence primitive, no database.
"""
from __future__ import annotations

import threading
from typing import Any

from backend.core.persistence import load_json, save_json_atomic, state_path

from .client_workspace import ClientWorkspace

_DEFAULT_FILENAME = "workspaces.json"


class WorkspaceRegistry:
    def __init__(self, path: str | None = None) -> None:
        self._path = path or state_path(_DEFAULT_FILENAME)
        self._lock = threading.Lock()

    def _load(self) -> dict[str, dict]:
        return load_json(self._path, default={}) or {}

    def _persist(self, all_data: dict[str, dict]) -> bool:
        return save_json_atomic(self._path, all_data)

    def register(self, workspace: ClientWorkspace) -> ClientWorkspace:
        with self._lock:
            data = self._load()
            data[workspace.workspace_id] = workspace.to_dict()
            self._persist(data)
        return workspace

    def get(self, workspace_id: str) -> ClientWorkspace | None:
        data = self._load()
        row = data.get(workspace_id)
        return ClientWorkspace.from_dict(row) if row else None

    def by_name(self, name: str) -> ClientWorkspace | None:
        for row in self._load().values():
            if row.get("name") == name:
                return ClientWorkspace.from_dict(row)
        return None

    def list_all(self) -> list[ClientWorkspace]:
        return [ClientWorkspace.from_dict(row) for row in self._load().values()]

    def update(self, workspace: ClientWorkspace) -> ClientWorkspace:
        workspace.touch()
        return self.register(workspace)


_registry: WorkspaceRegistry | None = None
_registry_lock = threading.Lock()


def get_workspace_registry() -> WorkspaceRegistry:
    global _registry
    if _registry is None:
        with _registry_lock:
            if _registry is None:
                _registry = WorkspaceRegistry()
    return _registry
