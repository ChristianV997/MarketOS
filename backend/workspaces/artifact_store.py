"""backend.workspaces.artifact_store — local artifact store for run
envelopes, reports, and evidence.

Pure wrapper over backend/core/persistence.py's state_path/save_json_atomic/
load_json — no database, no new persistence primitive. Path convention:

    state/workspaces/{workspace_id}/experiments/{experiment_id}/{filename}

save_text() duplicates save_json_atomic's atomic-write *pattern* (temp file
+ os.replace) for non-JSON payloads (markdown reports), since
save_json_atomic is JSON-only.
"""
from __future__ import annotations

import logging
import os
from typing import Any

from backend.core.persistence import load_json, save_json_atomic, state_path

_log = logging.getLogger(__name__)


def _reject_unsafe_component(value: str, field: str) -> None:
    """Reject path components that can leave the caller's workspace directory.

    Checking only the joined path is not enough: ``..`` inside experiment_id
    or filename can normalize to a sibling workspace while remaining under
    ``state/workspaces/``.
    """
    if not value:
        return
    normalized = value.replace("\\", "/")
    if normalized.startswith("/") or (len(normalized) > 1 and normalized[1] == ":"):
        raise ValueError(f"{field} must not be an absolute path: {value!r}")
    if ".." in normalized.split("/"):
        raise ValueError(
            f"{field} must not contain a parent-directory traversal ('..'): {value!r}"
        )


def _resolve_within_workspaces(rel: str) -> str:
    base = os.path.normpath(state_path("workspaces"))
    resolved = os.path.normpath(state_path(rel))
    if resolved != base and not resolved.startswith(base + os.sep):
        raise ValueError(
            "workspace_id, experiment_id, and filename must stay within the workspace state directory"
        )
    return resolved


class ArtifactStore:
    def path_for(self, workspace_id: str, experiment_id: str, filename: str = "") -> str:
        _reject_unsafe_component(workspace_id, "workspace_id")
        _reject_unsafe_component(experiment_id, "experiment_id")
        _reject_unsafe_component(filename, "filename")
        rel = os.path.join("workspaces", workspace_id, "experiments", experiment_id, filename)
        return _resolve_within_workspaces(rel)

    def save(self, workspace_id: str, experiment_id: str, filename: str, data: Any) -> bool:
        return save_json_atomic(self.path_for(workspace_id, experiment_id, filename), data)

    def load(self, workspace_id: str, experiment_id: str, filename: str, default: Any = None) -> Any:
        return load_json(self.path_for(workspace_id, experiment_id, filename), default)

    def save_text(self, workspace_id: str, experiment_id: str, filename: str, text: str) -> bool:
        path = self.path_for(workspace_id, experiment_id, filename)
        if not path:
            return False
        try:
            parent = os.path.dirname(path)
            if parent:
                os.makedirs(parent, exist_ok=True)
            tmp = f"{path}.tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(text)
            os.replace(tmp, path)
            return True
        except Exception as exc:  # noqa: BLE001 — best-effort persistence
            _log.debug("artifact_store_save_text_failed path=%s error=%s", path, exc)
            return False

    def load_text(self, workspace_id: str, experiment_id: str, filename: str, default: str = "") -> str:
        path = self.path_for(workspace_id, experiment_id, filename)
        if not path or not os.path.exists(path):
            return default
        try:
            with open(path, encoding="utf-8") as f:
                return f.read()
        except Exception as exc:  # noqa: BLE001
            _log.debug("artifact_store_load_text_failed path=%s error=%s", path, exc)
            return default

    def list_experiments(self, workspace_id: str) -> list[str]:
        try:
            _reject_unsafe_component(workspace_id, "workspace_id")
            base = _resolve_within_workspaces(os.path.join("workspaces", workspace_id, "experiments"))
            return sorted(os.listdir(base)) if os.path.isdir(base) else []
        except Exception as exc:  # noqa: BLE001 — fail-silent listing, including rejected traversal
            _log.debug("artifact_store_list_experiments_failed workspace=%s error=%s", workspace_id, exc)
            return []
