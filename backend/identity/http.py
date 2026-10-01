"""backend.identity.http -- FastAPI dependencies for verified identity.

Nothing here mounts routes or reads configuration. Deployment wiring supplies
the two providers via ``app.dependency_overrides`` (or by replacing them); until
it does, both fail closed with HTTP 503 and no request is served.

Contract for route authors: identity comes only from ``require_principal`` and
workspace access only from ``resolve_workspace_access``. Do not read a workspace
id, name, or user id from the query string, body, or other headers to decide who
the caller is or what they may see.
"""
from __future__ import annotations

import logging
import re
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse

from .errors import (
    IdentityError,
    IdentityFoundationError,
    IdentityProviderUnavailable,
    StorageUnavailable,
    WorkspaceAccessDenied,
)
from .principal import MAX_TOKEN_LENGTH, TokenVerifier, VerifiedPrincipal
from .roles import role_grants
from .workspaces import WorkspaceAccess, WorkspaceRepository, resolve_sole_workspace, resolve_workspace

WORKSPACE_HEADER = "X-MarketOS-Workspace"

_log = logging.getLogger("marketos.identity")
_BEARER = re.compile(r"^bearer[ \t]+([A-Za-z0-9\-._~+/]+=*)$", re.IGNORECASE)


def _headers_for(exc: IdentityFoundationError) -> dict[str, str] | None:
    return {"WWW-Authenticate": "Bearer"} if exc.status_code == 401 else None


def http_exception(exc: IdentityFoundationError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail={"code": exc.code}, headers=_headers_for(exc))


async def identity_error_handler(_request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, IdentityFoundationError)
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": {"code": exc.code}},
        headers=_headers_for(exc),
    )


def install_identity_error_handlers(app: FastAPI) -> None:
    """Map errors raised inside route handlers (e.g. ``StorageUnavailable``) to HTTP."""
    app.add_exception_handler(IdentityFoundationError, identity_error_handler)


def bearer_token(authorization: str | None) -> str:
    if not authorization:
        raise IdentityError("missing_credentials")
    match = _BEARER.fullmatch(authorization.strip())
    if match is None or len(match.group(1)) > MAX_TOKEN_LENGTH:
        raise IdentityError()
    return match.group(1)


def get_token_verifier() -> TokenVerifier:
    """Override in deployment wiring. Unconfigured -> 503 (never anonymous access)."""
    raise http_exception(IdentityProviderUnavailable())


def get_workspace_repository() -> WorkspaceRepository:
    """Override in deployment wiring. Unconfigured -> 503 (no file/JSON fallback)."""
    raise http_exception(StorageUnavailable())


def require_principal(
    authorization: Annotated[str | None, Header()] = None,
    verifier: TokenVerifier = Depends(get_token_verifier),
) -> VerifiedPrincipal:
    try:
        return verifier.verify(bearer_token(authorization))
    except IdentityFoundationError as exc:
        raise http_exception(exc) from None
    except Exception as exc:
        _log.warning("identity verifier raised unexpectedly: %s", type(exc).__name__)
        raise http_exception(IdentityError()) from None


def resolve_workspace_access(
    principal: VerifiedPrincipal = Depends(require_principal),
    repository: WorkspaceRepository = Depends(get_workspace_repository),
    requested_workspace: Annotated[str | None, Header(alias=WORKSPACE_HEADER)] = None,
) -> WorkspaceAccess:
    try:
        return resolve_workspace(principal, requested_workspace, repository)
    except IdentityFoundationError as exc:
        raise http_exception(exc) from None


def require_workspace_permission(workspace_type: str, permission: str):
    """Dependency factory: the principal's sole ``workspace_type`` membership, if its role grants ``permission``.

    Unlike ``resolve_workspace_access`` this path reads no workspace selector at all
    (no header, query or body): the workspace comes from registered memberships only.
    A missing or unknown role fails closed with 403, and any unexpected repository
    failure is reported as 503 without detail.
    """

    def dependency(
        principal: VerifiedPrincipal = Depends(require_principal),
        repository: WorkspaceRepository = Depends(get_workspace_repository),
    ) -> WorkspaceAccess:
        try:
            access = resolve_sole_workspace(principal, repository, workspace_type)
            if not role_grants(access.role, permission):
                raise WorkspaceAccessDenied("role_not_authorized")
            return access
        except IdentityFoundationError as exc:
            raise http_exception(exc) from None
        except Exception as exc:
            _log.warning("workspace membership lookup failed: %s", type(exc).__name__)
            raise http_exception(StorageUnavailable()) from None

    return dependency
