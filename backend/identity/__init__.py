"""backend.identity -- verified principal, workspace resolution, durable store.

Foundation only: it mounts no routes, configures no provider, and never handles
credentials. See ``docs/IDENTITY_WORKSPACE_FOUNDATION.md``.
"""
from .errors import (
    IdentityError,
    IdentityFoundationError,
    IdentityProviderUnavailable,
    StorageConflict,
    StorageUnavailable,
    WorkspaceAccessDenied,
    WorkspaceSelectionRequired,
)
from .principal import ClerkSessionTokenVerifier, TokenVerifier, VerifiedPrincipal
from .repository import PostgresWorkspaceRepository
from .workspaces import WorkspaceAccess, WorkspaceRepository, resolve_workspace

__all__ = [
    "ClerkSessionTokenVerifier",
    "IdentityError",
    "IdentityFoundationError",
    "IdentityProviderUnavailable",
    "PostgresWorkspaceRepository",
    "StorageConflict",
    "StorageUnavailable",
    "TokenVerifier",
    "VerifiedPrincipal",
    "WorkspaceAccess",
    "WorkspaceAccessDenied",
    "WorkspaceRepository",
    "WorkspaceSelectionRequired",
    "resolve_workspace",
]
