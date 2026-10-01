"""Stable, secret-free error types for the identity/workspace foundation.

Every error carries only a fixed machine-readable ``code``. Messages never
contain tokens, claims, connection strings, or database error text.
"""
from __future__ import annotations


class IdentityFoundationError(Exception):
    status_code = 500
    code = "identity_error"

    def __init__(self, code: str | None = None) -> None:
        if code is not None:
            self.code = code
        super().__init__(self.code)


class IdentityError(IdentityFoundationError):
    """Missing or invalid identity (HTTP 401)."""

    status_code = 401
    code = "invalid_credentials"


class WorkspaceSelectionRequired(IdentityFoundationError):
    """The principal belongs to several workspaces and named none (HTTP 400)."""

    status_code = 400
    code = "workspace_selection_required"


class WorkspaceAccessDenied(IdentityFoundationError):
    """Authenticated, but not authorized for the workspace (HTTP 403)."""

    status_code = 403
    code = "workspace_not_authorized"


class ProfileNotFound(IdentityFoundationError):
    """The workspace has no client profile yet (HTTP 404)."""

    status_code = 404
    code = "profile_not_found"


class ProfileExportRejected(IdentityFoundationError):
    """A stored profile failed the TrustOS client-workspace leakage check (HTTP 500, fail closed)."""

    status_code = 500
    code = "profile_export_rejected"


class StorageConflict(IdentityFoundationError):
    """A database constraint rejected the write (HTTP 409)."""

    status_code = 409
    code = "constraint_violation"


class IdentityProviderUnavailable(IdentityFoundationError):
    """No verifier is configured, or key material could not be obtained (HTTP 503)."""

    status_code = 503
    code = "identity_provider_unavailable"


class StorageUnavailable(IdentityFoundationError):
    """The durable store cannot be reached or is not ready (HTTP 503)."""

    status_code = 503
    code = "storage_unavailable"
