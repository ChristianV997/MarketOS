"""FastAPI dependency for membership-backed workspace selection."""
from __future__ import annotations

from fastapi import Depends, HTTPException, Request

from backend.workspaces.postgres_repository import (
    PostgresRepositoryUnavailable,
    PostgresWorkspaceRepository,
    WorkspaceAccessDenied,
    WorkspaceRepository,
    WorkspaceSelectionRequired,
)

from .principal import VerifiedPrincipal, require_verified_principal


def get_workspace_repository() -> WorkspaceRepository:
    """Return the explicit server repository; there is no file fallback."""

    return PostgresWorkspaceRepository()


def require_workspace(
    request: Request,
    principal: VerifiedPrincipal = Depends(require_verified_principal),
    repository: WorkspaceRepository = Depends(get_workspace_repository),
):
    """Resolve a request selector only inside the authenticated membership set."""

    workspace_id = request.query_params.get("workspace_id") or request.headers.get("x-workspace-id")
    workspace_name = request.query_params.get("workspace_name")
    try:
        return repository.resolve_workspace(principal, workspace_id=workspace_id, workspace_name=workspace_name)
    except PostgresRepositoryUnavailable as exc:
        raise HTTPException(status_code=503, detail="workspace database unavailable") from exc
    except WorkspaceSelectionRequired as exc:
        raise HTTPException(status_code=400, detail="workspace selector is required") from exc
    except WorkspaceAccessDenied as exc:
        raise HTTPException(status_code=403, detail="workspace access denied") from exc


__all__ = ["get_workspace_repository", "require_workspace"]