"""backend.workspaces.artifact_store — local artifact store for run
envelopes, reports, and evidence.

Wrapper over backend/core/persistence.py's state_path — no database or
parallel workspace authority. An instance is bound
to an already registered ClientWorkspace. Path convention:

    state/workspaces/{workspace_id}/experiments/{experiment_id}/{filename}

save_text() duplicates save_json_atomic's atomic-write *pattern* (temp file
+ os.replace) for non-JSON payloads (markdown reports), since
save_json_atomic is JSON-only.

Path components are validated before join. A joined-path prefix check is
not sufficient: ``..`` inside experiment_id or filename can normalize to a
sibling workspace while remaining under state/workspaces/.
"""
from __future__ import annotations

import json
import logging
import ntpath
import os
import re
import unicodedata
from typing import Any

from backend.core.persistence import state_path
from backend.workspaces.client_workspace import ClientWorkspace
from backend.workspaces.registry import WorkspaceRegistry, get_workspace_registry

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


def _reject_unsafe_component(value: str, field: str) -> None:
    """Reject path components that can leave the caller's workspace directory."""
    if not isinstance(value, str):
        raise ValueError(f"invalid {field}")
    if not value:
        raise ValueError(f"invalid {field}")
    if value.strip() != value or not value.strip():
        raise ValueError(f"invalid {field}")
    if any(unicodedata.category(char).startswith("C") for char in value):
        raise ValueError(f"invalid {field}")
    normalized = value.replace("\\", "/")
    if os.path.isabs(value) or ntpath.isabs(value) or normalized.startswith("/") or ntpath.splitdrive(value)[0]:
        raise ValueError(f"invalid {field}")
    segments = normalized.split("/")
    if len(segments) != 1 or any(segment in {"", ".", ".."} for segment in segments):
        raise ValueError(f"invalid {field}")
    if _SECRET_SHAPED_VALUE.search(value):
        raise ValueError(f"invalid {field}")


def _is_within(child: str, parent: str) -> bool:
    parent_n = os.path.normpath(parent)
    child_n = os.path.normpath(child)
    try:
        return os.path.commonpath([parent_n, child_n]) == parent_n
    except ValueError:
        return False


def _resolve_within_workspaces(rel: str) -> str:
    """Resolve existing links before checking the canonical workspace jail."""
    base = os.path.realpath(state_path("workspaces"))
    resolved = os.path.realpath(state_path(rel))
    if not _is_within(resolved, base) and resolved != base:
        raise ValueError("artifact path is outside the workspace boundary")
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


def _save_json(path: str, data: Any) -> bool:
    """Atomically persist an already-authorized JSON artifact without path logs."""
    try:
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        tmp = f"{path}.tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2, default=str)
        os.replace(tmp, path)
        return True
    except Exception:  # noqa: BLE001 — persistence is deliberately fail-soft
        _log.debug("artifact_store_save_json_failed")
        return False


def _load_json(path: str, default: Any) -> Any:
    """Load an already-authorized JSON artifact without reflecting path errors."""
    if not os.path.exists(path):
        return default
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except Exception:  # noqa: BLE001 — malformed or inaccessible artifacts are absent
        _log.debug("artifact_store_load_json_failed")
        return default


class ArtifactStore:
    """Workspace-bound artifact access.

    Callers must supply a ClientWorkspace that exactly matches the durable
    WorkspaceRegistry entry. This is an identity boundary, not an
    authorization system; authorization remains the responsibility of the
    caller that selected the registered workspace principal.
    """

    def __init__(self, workspace: ClientWorkspace, registry: WorkspaceRegistry | None = None) -> None:
        if not isinstance(workspace, ClientWorkspace):
            raise ValueError("invalid workspace identity")
        _reject_unsafe_component(workspace.workspace_id, "workspace_id")
        self._workspace = workspace
        self._registry = registry or get_workspace_registry()

    @property
    def workspace(self) -> ClientWorkspace:
        return self._workspace

    def _canonical_workspace(self) -> ClientWorkspace:
        registered = self._registry.get(self._workspace.workspace_id)
        if registered is None or registered.to_dict() != self._workspace.to_dict():
            raise ValueError("workspace identity is not registered")
        return registered

    def _assert_payload_workspace(self, data: Any) -> None:
        if not isinstance(data, dict):
            return
        for field in ("workspace_id", "workspace"):
            claimed = data.get(field)
            if claimed is not None and claimed != self._workspace.workspace_id:
                raise ValueError("artifact workspace identity does not match the bound workspace")

    def path_for(self, experiment_id: str, filename: str) -> str:
        self._canonical_workspace()
        _reject_unsafe_component(experiment_id, "experiment_id")
        _reject_unsafe_component(filename, "filename")
        rel = os.path.join(
            "workspaces", self._workspace.workspace_id, "experiments", experiment_id, filename,
        )
        return _resolve_within_workspaces(rel)

    def save(self, experiment_id: str, filename: str, data: Any) -> bool:
        self._assert_payload_workspace(data)
        return _save_json(
            self.path_for(experiment_id, filename),
            _redact_secret_shaped(data),
        )

    def load(self, experiment_id: str, filename: str, default: Any = None) -> Any:
        return _load_json(self.path_for(experiment_id, filename), default)

    def save_text(self, experiment_id: str, filename: str, text: str) -> bool:
        path = self.path_for(experiment_id, filename)
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
        except Exception:  # noqa: BLE001 — best-effort persistence
            _log.debug("artifact_store_save_text_failed")
            return False

    def load_text(self, experiment_id: str, filename: str, default: str = "") -> str:
        path = self.path_for(experiment_id, filename)
        if not os.path.exists(path):
            return default
        try:
            with open(path, encoding="utf-8") as f:
                return f.read()
        except Exception:  # noqa: BLE001
            _log.debug("artifact_store_load_text_failed")
            return default

    def list_experiments(self) -> list[str]:
        try:
            self._canonical_workspace()
            base = _resolve_within_workspaces(
                os.path.join("workspaces", self._workspace.workspace_id, "experiments")
            )
            return sorted(os.listdir(base)) if os.path.isdir(base) else []
        except Exception:  # noqa: BLE001 — fail-silent listing, including rejected identities
            _log.debug("artifact_store_list_experiments_failed")
            return []
