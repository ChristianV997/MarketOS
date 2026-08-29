"""backend.workspaces.artifact_store — local artifact store for run
envelopes, reports, and evidence.

Pure wrapper over backend/core/persistence.py's state_path/save_json_atomic/
load_json — no database, no new persistence primitive. Path convention:

    state/workspaces/{workspace_id}/experiments/{experiment_id}/{filename}

save_text() duplicates save_json_atomic's atomic-write *pattern* (temp file
+ os.replace) for non-JSON payloads (markdown reports), since
save_json_atomic is JSON-only.

Path components are validated before join. A joined-path prefix check is
not sufficient: ``..`` inside experiment_id or filename can normalize to a
sibling workspace while remaining under state/workspaces/.
"""
from __future__ import annotations

import logging
import os
import re
from typing import Any

from backend.core.persistence import load_json, save_json_atomic, state_path

_log = logging.getLogger(__name__)

_SECRET_KEY_NAMES = frozenset(
    {
        "api_key",
        "apikey",
        "access_token",
        "authorization",
        "auth_token",
        "password",
        "private_key",
        "secret",
        "secret_key",
        "token",
    }
)
_SECRET_SHAPED_VALUE = re.compile(
    r"(?is)("
    r"-----begin (?:rsa |ec |dsa |openssh )?private key-----"
    r"|ghp_[A-Za-z0-9_]{20,}"
    r"|github_pat_[A-Za-z0-9_]{20,}"
    r"|sk-(?:live|test)?-[A-Za-z0-9]{16,}"
    r"|AKIA[0-9A-Z]{16}"
    r")"
)
_REDACTED = "[redacted]"


def _reject_unsafe_component(value: str, field: str, *, allow_empty: bool = False) -> None:
    """Reject path components that can leave the caller's workspace directory."""
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    if not value:
        if allow_empty:
            return
        raise ValueError(f"{field} must not be empty")
    if value.strip() != value or not value.strip():
        raise ValueError(f"{field} must not include leading/trailing whitespace: {value!r}")
    normalized = value.replace("\\", "/")
    if normalized.startswith("/") or normalized.startswith("//") or (
        len(normalized) > 1 and normalized[1] == ":"
    ):
        raise ValueError(f"{field} must not be an absolute path: {value!r}")
    segments = normalized.split("/")
    if ".." in segments:
        raise ValueError(
            f"{field} must not contain a parent-directory traversal ('..'): {value!r}"
        )
    if field in {"workspace_id", "experiment_id"} and len(segments) != 1:
        raise ValueError(f"{field} must be a single path segment: {value!r}")
    if _SECRET_SHAPED_VALUE.search(value):
        raise ValueError(f"{field} must not contain a credential-shaped value")


def _is_within(child: str, parent: str) -> bool:
    parent_n = os.path.normpath(parent)
    child_n = os.path.normpath(child)
    try:
        return os.path.commonpath([parent_n, child_n]) == parent_n
    except ValueError:
        return False


def _reject_symlink_escape(resolved: str, base: str) -> None:
    """Fail closed if an existing symlink would resolve outside the workspace root."""
    real_base = os.path.realpath(base) if os.path.lexists(base) else os.path.normpath(base)
    cursor = resolved
    while True:
        if os.path.lexists(cursor) and os.path.islink(cursor):
            target = os.path.realpath(cursor)
            if not _is_within(target, real_base) and target != real_base:
                raise ValueError("artifact path must not escape the workspace via symlink")
        parent = os.path.dirname(cursor)
        if not parent or parent == cursor:
            break
        if not _is_within(parent, base) and parent != os.path.normpath(base):
            break
        cursor = parent


def _resolve_within_workspaces(rel: str) -> str:
    base = os.path.normpath(state_path("workspaces"))
    resolved = os.path.normpath(state_path(rel))
    if not _is_within(resolved, base) and resolved != base:
        raise ValueError(
            "workspace_id, experiment_id, and filename must stay within the workspace state directory"
        )
    _reject_symlink_escape(resolved, base)
    return resolved


def _redact_secret_shaped(data: Any) -> Any:
    """Redact credential-shaped keys/values in JSON payloads. Non-dict data is unchanged."""
    if isinstance(data, dict):
        redacted: dict[str, Any] = {}
        for key, value in data.items():
            key_l = key.lower() if isinstance(key, str) else ""
            if key_l in _SECRET_KEY_NAMES:
                redacted[key] = _REDACTED
            else:
                redacted[key] = _redact_secret_shaped(value)
        return redacted
    if isinstance(data, list):
        return [_redact_secret_shaped(item) for item in data]
    if isinstance(data, str) and _SECRET_SHAPED_VALUE.search(data):
        return _REDACTED
    return data


class ArtifactStore:
    def path_for(self, workspace_id: str, experiment_id: str, filename: str = "") -> str:
        _reject_unsafe_component(workspace_id, "workspace_id")
        _reject_unsafe_component(experiment_id, "experiment_id")
        _reject_unsafe_component(filename, "filename", allow_empty=True)
        rel = os.path.join("workspaces", workspace_id, "experiments", experiment_id, filename)
        return _resolve_within_workspaces(rel)

    def save(self, workspace_id: str, experiment_id: str, filename: str, data: Any) -> bool:
        return save_json_atomic(
            self.path_for(workspace_id, experiment_id, filename),
            _redact_secret_shaped(data),
        )

    def load(self, workspace_id: str, experiment_id: str, filename: str, default: Any = None) -> Any:
        return load_json(self.path_for(workspace_id, experiment_id, filename), default)

    def save_text(self, workspace_id: str, experiment_id: str, filename: str, text: str) -> bool:
        path = self.path_for(workspace_id, experiment_id, filename)
        if not path:
            return False
        try:
            if _SECRET_SHAPED_VALUE.search(text):
                text = _SECRET_SHAPED_VALUE.sub(_REDACTED, text)
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
        except Exception as exc:  # noqa: BLE001 — fail-silent listing, including a rejected traversal attempt
            _log.debug("artifact_store_list_experiments_failed workspace=%s error=%s", workspace_id, exc)
            return []
