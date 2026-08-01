"""backend.workspaces — ClientWorkspace, CredentialScope, LiveModeChecklist,
ArtifactStore: the multi-tenant isolation foundations service modules build on.

Public surface:
    ClientWorkspace       — dataclass: name/type/mode/budget ceilings/etc.
    WorkspaceRegistry      — durable catalog (state/workspaces.json)
    get_workspace_registry — singleton accessor
    scope_for              — CredentialScope: which integrations are configured
    check                  — LiveModeChecklist: gate before any live mutation/spend
    ArtifactStore          — per-workspace/per-experiment artifact persistence
"""
from . import live_mode_checklist as live_mode
from .artifact_store import ArtifactStore
from .client_workspace import ClientWorkspace
from .credential_scope import scope_for
from .registry import WorkspaceRegistry, get_workspace_registry

check = live_mode.check

__all__ = [
    "ClientWorkspace",
    "WorkspaceRegistry",
    "get_workspace_registry",
    "scope_for",
    "check",
    "ArtifactStore",
]
