"""backend.workspaces.artifact_store — local artifact store for run
envelopes, reports, and evidence.

Wrapper over backend/core/persistence.py's state_path — no database or
parallel workspace authority. An instance is bound
to an already registered ClientWorkspace. Path convention:

    state/workspaces/{workspace_id}/experiments/{experiment_id}/{filename}

Atomic-write pattern uses unique temporary files (tempfile.mkstemp) +
os.replace with exclusive creation (O_CREAT | O_EXCL), fsync, and automatic
cleanup on failure. Concurrent writes to the same or distinct artifacts
never collide or leave dangling temporary files.

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
import tempfile
import unicodedata
from typing import Any

from backend.core.persistence import state_path
from backend.workspaces.client_workspace import ClientWorkspace
from backend.workspaces.registry import WorkspaceRegistry, get_workspace_registry

_log = logging.getLogger(__name__)

MAX_ARTIFACT_BYTES: int = int(os.getenv("MARKETOS_MAX_ARTIFACT_BYTES", 10 * 1024 * 1024))

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

_RESERVED_DEVICE_NAMES = frozenset(
    {"con", "prn", "aux", "nul"}
    | {f"com{i}" for i in range(1, 10)}
    | {f"lpt{i}" for i in range(1, 10)}
)


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
    stem = segments[0].split(".")[0].lower()
    if stem in _RESERVED_DEVICE_NAMES:
        raise ValueError(f"invalid {field}")
    if _SECRET_SHAPED_VALUE.search(value):
        raise ValueError(f"invalid {field}")


def _strip_extended_prefix(path: str) -> str:
    norm = os.path.normpath(path)
    if norm.startswith(("\\\\?\\UNC\\", "\\\\?\\unc\\")):
        return "\\\\" + norm[8:]
    if norm.startswith("\\\\?\\"):
        return norm[4:]
    return norm


def _normalize_path(path: str) -> str:
    return os.path.normcase(_strip_extended_prefix(path))


def _is_within(child: str, parent: str) -> bool:
    parent_n = _normalize_path(parent)
    child_n = _normalize_path(child)
    try:
        return os.path.commonpath([parent_n, child_n]) == parent_n
    except ValueError:
        return False


def _resolve_within_workspaces(rel: str, workspace_id: str | None = None) -> str:
    """Resolve existing links before checking the canonical workspace jail."""
    workspaces_base = _strip_extended_prefix(os.path.realpath(state_path("workspaces")))
    target_base = (
        _strip_extended_prefix(os.path.realpath(state_path(os.path.join("workspaces", workspace_id))))
        if workspace_id
        else workspaces_base
    )
    resolved = _strip_extended_prefix(os.path.realpath(state_path(rel)))
    if not _is_within(resolved, workspaces_base) and _normalize_path(resolved) != _normalize_path(workspaces_base):
        raise ValueError("artifact path is outside the workspace boundary")
    if not _is_within(resolved, target_base) and _normalize_path(resolved) != _normalize_path(target_base):
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
    if isinstance(data, tuple):
        return tuple(_redact_secret_shaped(item) for item in data)
    if isinstance(data, str) and _SECRET_SHAPED_VALUE.search(data):
        return _REDACTED
    return data


def _atomic_write_text(
    path: str,
    text: str,
    *,
    workspace_jail: str | None = None,
    max_bytes: int | None = None,
) -> bool:
    """Atomically write text to path using an exclusive temporary file + os.replace."""
    if not isinstance(text, str):
        return False
    effective_max_bytes = MAX_ARTIFACT_BYTES if max_bytes is None else max_bytes
    if len(text.encode("utf-8")) > effective_max_bytes:
        _log.debug("artifact_store_save_oversized")
        return False

    tmp_path: str | None = None
    try:
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
            if os.path.islink(parent):
                _log.debug("artifact_store_save_parent_symlink_rejected")
                return False
            if workspace_jail:
                resolved_parent = _strip_extended_prefix(os.path.realpath(parent))
                if not _is_within(resolved_parent, workspace_jail) and _normalize_path(resolved_parent) != _normalize_path(workspace_jail):
                    _log.debug("artifact_store_save_parent_outside_jail")
                    return False

        if os.path.islink(path):
            _log.debug("artifact_store_save_symlink_rejected")
            return False
        if os.path.isdir(path):
            _log.debug("artifact_store_save_target_is_directory")
            return False

        fd, tmp_path = tempfile.mkstemp(
            dir=parent or ".",
            prefix=f".{os.path.basename(path)}.",
            suffix=".tmp",
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(text)
                handle.flush()
                try:
                    os.fsync(handle.fileno())
                except OSError:
                    pass
        except Exception:
            try:
                os.close(fd)
            except OSError:
                pass
            raise

        if os.path.islink(path):
            _log.debug("artifact_store_save_symlink_rejected")
            return False
        if os.path.isdir(path):
            _log.debug("artifact_store_save_target_is_directory")
            return False

        os.replace(tmp_path, path)
        tmp_path = None
        return True
    except Exception:  # noqa: BLE001 — persistence is deliberately fail-soft
        _log.debug("artifact_store_save_failed")
        return False
    finally:
        if tmp_path is not None:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


def _save_json(
    path: str,
    data: Any,
    workspace_jail: str | None = None,
    max_bytes: int | None = None,
) -> bool:
    """Atomically persist an already-authorized JSON artifact without path logs."""
    try:
        serialized = json.dumps(data, ensure_ascii=False, indent=2, default=str)
    except Exception:  # noqa: BLE001
        _log.debug("artifact_store_save_json_failed")
        return False
    success = _atomic_write_text(path, serialized, workspace_jail=workspace_jail, max_bytes=max_bytes)
    if not success:
        _log.debug("artifact_store_save_json_failed")
    return success


def _load_json(path: str, default: Any, max_bytes: int | None = None) -> Any:
    """Load an already-authorized JSON artifact without reflecting path errors."""
    if not os.path.exists(path):
        return default
    if os.path.islink(path):
        _log.debug("artifact_store_load_symlink_rejected")
        return default
    if not os.path.isfile(path):
        _log.debug("artifact_store_load_non_regular_file")
        return default
    effective_max_bytes = MAX_ARTIFACT_BYTES if max_bytes is None else max_bytes
    try:
        if os.path.getsize(path) > effective_max_bytes:
            _log.debug("artifact_store_load_oversized")
            return default
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except Exception:  # noqa: BLE001 — malformed or inaccessible artifacts are absent
        _log.debug("artifact_store_load_json_failed")
        return default


def _load_text(path: str, default: str = "", max_bytes: int | None = None) -> str:
    """Load an already-authorized text artifact without reflecting path errors."""
    if not os.path.exists(path):
        return default
    if os.path.islink(path):
        _log.debug("artifact_store_load_symlink_rejected")
        return default
    if not os.path.isfile(path):
        _log.debug("artifact_store_load_non_regular_file")
        return default
    effective_max_bytes = MAX_ARTIFACT_BYTES if max_bytes is None else max_bytes
    try:
        if os.path.getsize(path) > effective_max_bytes:
            _log.debug("artifact_store_load_oversized")
            return default
        with open(path, encoding="utf-8") as f:
            content = f.read(effective_max_bytes + 1)
            if len(content.encode("utf-8")) > effective_max_bytes:
                _log.debug("artifact_store_load_oversized")
                return default
            return content
    except Exception:  # noqa: BLE001
        _log.debug("artifact_store_load_text_failed")
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
        self._canonical_workspace()

    @property
    def workspace(self) -> ClientWorkspace:
        return self._workspace

    def _workspace_jail(self) -> str:
        return _strip_extended_prefix(
            os.path.realpath(state_path(os.path.join("workspaces", self._workspace.workspace_id)))
        )

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
        return _resolve_within_workspaces(rel, self._workspace.workspace_id)

    def save(self, experiment_id: str, filename: str, data: Any) -> bool:
        self._assert_payload_workspace(data)
        return _save_json(
            self.path_for(experiment_id, filename),
            _redact_secret_shaped(data),
            workspace_jail=self._workspace_jail(),
        )

    def load(self, experiment_id: str, filename: str, default: Any = None) -> Any:
        path = self.path_for(experiment_id, filename)
        data = _load_json(path, default)
        if isinstance(data, dict):
            for field in ("workspace_id", "workspace"):
                claimed = data.get(field)
                if claimed is not None and claimed != self._workspace.workspace_id:
                    _log.debug("artifact_store_load_workspace_mismatch")
                    return default
        return data

    def save_text(self, experiment_id: str, filename: str, text: str) -> bool:
        path = self.path_for(experiment_id, filename)
        if not isinstance(text, str):
            _log.debug("artifact_store_save_text_failed")
            return False
        if _SECRET_SHAPED_VALUE.search(text):
            text = _SECRET_SHAPED_VALUE.sub(_REDACTED, text)
        workspace_jail = self._workspace_jail()
        success = _atomic_write_text(path, text, workspace_jail=workspace_jail)
        if not success:
            _log.debug("artifact_store_save_text_failed")
        return success

    def load_text(self, experiment_id: str, filename: str, default: str = "") -> str:
        path = self.path_for(experiment_id, filename)
        return _load_text(path, default)

    def list_experiments(self) -> list[str]:
        try:
            self._canonical_workspace()
            base = _resolve_within_workspaces(
                os.path.join("workspaces", self._workspace.workspace_id, "experiments"),
                self._workspace.workspace_id,
            )
            experiments: list[str] = []
            if os.path.isdir(base):
                workspace_jail = self._workspace_jail()
                for name in os.listdir(base):
                    if name.startswith("."):
                        continue
                    exp_path = os.path.join(base, name)
                    if not os.path.isdir(exp_path):
                        continue
                    if os.path.islink(exp_path):
                        resolved = _strip_extended_prefix(os.path.realpath(exp_path))
                        if not _is_within(resolved, workspace_jail) and _normalize_path(resolved) != _normalize_path(workspace_jail):
                            continue
                    experiments.append(name)
            return sorted(experiments)
        except Exception:  # noqa: BLE001 — fail-silent listing, including rejected identities
            _log.debug("artifact_store_list_experiments_failed")
            return []
