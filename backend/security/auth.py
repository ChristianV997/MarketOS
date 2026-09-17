"""Server-side authentication and workspace-scoped authorization boundary."""
from __future__ import annotations

import hmac
import json
import logging
import os
import re
from dataclasses import dataclass
from typing import Any, Mapping

from fastapi import Depends, Header, HTTPException, Request, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

_log = logging.getLogger("marketos.security.auth")
_bearer_security = HTTPBearer(auto_error=False)

_SAFE_TOKEN_RE = re.compile(r"^[A-Za-z0-9._~+/-]{8,256}$")

# Test-override token store for reproducible tests
_test_tokens: dict[str, dict[str, Any]] = {}


@dataclass(frozen=True)
class AuthenticatedActor:
    """Represents an authenticated actor with workspace authorization context."""

    actor_id: str
    role: str  # "operator" | "client"
    workspaces: frozenset[str]
    is_active: bool = True

    @property
    def is_operator(self) -> bool:
        return self.role == "operator"

    def can_access_workspace(self, workspace_id: str | None) -> bool:
        if not workspace_id:
            return True
        if self.is_operator or "*" in self.workspaces:
            return True
        return workspace_id in self.workspaces


def register_test_token(
    token: str,
    *,
    actor_id: str,
    role: str = "client",
    workspaces: set[str] | list[str] | None = None,
) -> None:
    """Register a deterministic token for unit and integration testing."""
    _test_tokens[token] = {
        "actor_id": actor_id,
        "role": role,
        "workspaces": set(workspaces or ({"*"} if role == "operator" else {"test-workspace"})),
    }


def clear_test_tokens() -> None:
    """Clear registered test tokens."""
    _test_tokens.clear()


def is_production_mode(environ: Mapping[str, str] | None = None) -> bool:
    """Check if runtime is in production/hosted/staging mode requiring strict security."""
    env = os.environ if environ is None else environ
    env_name = env.get("MARKETOS_ENVIRONMENT", "").strip().lower()
    if env_name in {"production", "prod", "staging", "hosted"}:
        return True
    if env.get("RENDER", "").strip().lower() == "true":
        return True
    if env.get("RAILWAY_ENVIRONMENT", "").strip():
        return True
    if env.get("MARKETOS_HOSTED", "0").strip().lower() in {"1", "true", "yes", "on"}:
        return True
    if env.get("MARKETOS_MVP_MODE", "0").strip().lower() in {"1", "true", "yes", "on"}:
        return True
    return False


def is_auth_disabled_in_dev(environ: Mapping[str, str] | None = None) -> bool:
    """Check if auth is explicitly disabled for local development only."""
    env = os.environ if environ is None else environ
    if is_production_mode(env):
        return False
    return env.get("MARKETOS_AUTH_DISABLED", "false").strip().lower() in {"1", "true", "yes", "on"}


def _get_configured_operator_token(environ: Mapping[str, str] | None = None) -> str | None:
    env = os.environ if environ is None else environ
    token: str | None = env.get("MARKETOS_OPERATOR_TOKEN") or env.get("MARKETOS_API_KEY")
    return token.strip() if token and token.strip() else None


def _get_configured_client_tokens(environ: Mapping[str, str] | None = None) -> dict[str, dict[str, Any]]:
    """Parse configured client tokens from environment."""
    env = os.environ if environ is None else environ
    tokens: dict[str, dict[str, Any]] = {}

    # Support single client token shorthand
    single_token: str = env.get("MARKETOS_CLIENT_TOKEN", "").strip()
    single_ws = env.get("MARKETOS_CLIENT_WORKSPACE", "default").strip()
    if single_token:
        tokens[single_token] = {
            "actor_id": "env-client",
            "role": "client",
            "workspaces": {single_ws},
        }

    # Support multi-client JSON dictionary
    raw_json = env.get("MARKETOS_CLIENT_TOKENS", "").strip()
    if raw_json:
        try:
            parsed = json.loads(raw_json)
            if isinstance(parsed, dict):
                for token, meta in parsed.items():
                    if isinstance(meta, dict) and isinstance(token, str):
                        workspaces = meta.get("workspaces")
                        if isinstance(workspaces, list):
                            ws_set = set(workspaces)
                        elif isinstance(workspaces, str):
                            ws_set = {workspaces}
                        elif meta.get("workspace_id"):
                            ws_set = {str(meta["workspace_id"])}
                        else:
                            ws_set = {"default"}
                        tokens[token] = {
                            "actor_id": str(meta.get("actor_id", f"client-{token[:8]}")),
                            "role": str(meta.get("role", "client")),
                            "workspaces": ws_set,
                        }
        except Exception as exc:
            _log.warning("failed_to_parse_client_tokens error=%s", exc)

    return tokens


def _extract_token_from_request(
    request: Request | None = None,
    bearer_creds: HTTPAuthorizationCredentials | None = None,
    header_api_key: str | None = None,
    header_token: str | None = None,
) -> str | None:
    """Extract raw token string from HTTP headers in constant time manner."""
    candidates: list[str] = []

    if bearer_creds and bearer_creds.credentials:
        candidates.append(bearer_creds.credentials.strip())

    if header_api_key and header_api_key.strip():
        candidates.append(header_api_key.strip())

    if header_token and header_token.strip():
        candidates.append(header_token.strip())

    if request:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.lower().startswith("bearer "):
            extracted: str = auth_header[7:].strip()
            if extracted:
                candidates.append(extracted)
        api_key_header_val: str = request.headers.get("X-API-Key", "").strip()
        if api_key_header_val:
            candidates.append(api_key_header_val)
        req_tok: str = request.headers.get("X-MarketOS-Token", "").strip()
        if req_tok:
            candidates.append(req_tok)

    for cand in candidates:
        if cand:
            return cand
    return None


def authenticate_token(token: str | None, environ: Mapping[str, str] | None = None) -> AuthenticatedActor | None:
    """Authenticate raw token using constant-time comparisons against configured identities."""
    if not token or not isinstance(token, str):
        return None

    # Check registered test tokens first
    for test_tok, meta in _test_tokens.items():
        if hmac.compare_digest(token, test_tok):
            return AuthenticatedActor(
                actor_id=meta["actor_id"],
                role=meta["role"],
                workspaces=frozenset(meta["workspaces"]),
            )

    # Check configured operator token
    op_token: str | None = _get_configured_operator_token(environ)
    if op_token and hmac.compare_digest(token, op_token):
        return AuthenticatedActor(
            actor_id="operator",
            role="operator",
            workspaces=frozenset({"*"}),
        )

    # Check configured client tokens
    client_tokens = _get_configured_client_tokens(environ)
    for c_token, meta in client_tokens.items():
        if hmac.compare_digest(token, c_token):
            return AuthenticatedActor(
                actor_id=meta["actor_id"],
                role=meta["role"],
                workspaces=frozenset(meta["workspaces"]),
            )

    return None


async def get_current_actor(
    request: Request,
    bearer_creds: HTTPAuthorizationCredentials | None = Security(_bearer_security),
    x_api_key: str | None = Header(None, alias="X-API-Key"),
    x_marketos_token: str | None = Header(None, alias="X-MarketOS-Token"),
) -> AuthenticatedActor:
    """FastAPI dependency to extract and authenticate current actor. Fails closed."""
    # Check if auth is disabled for local dev
    if is_auth_disabled_in_dev():
        return AuthenticatedActor(
            actor_id="dev-operator",
            role="operator",
            workspaces=frozenset({"*"}),
        )

    # Check if production environment lacks operator token configuration
    op_token: str | None = _get_configured_operator_token()
    client_tokens = _get_configured_client_tokens()
    has_test_tokens = bool(_test_tokens)

    if is_production_mode() and not op_token and not client_tokens and not has_test_tokens:
        _log.error("production_auth_unconfigured: neither operator token nor client tokens are set")
        raise HTTPException(
            status_code=503,
            detail="authentication_system_unconfigured",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token: str | None = _extract_token_from_request(
        request,
        bearer_creds,
        x_api_key,
        x_marketos_token,
    )

    if not token:
        raise HTTPException(
            status_code=401,
            detail="missing_credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    actor = authenticate_token(token)
    if actor is None:
        raise HTTPException(
            status_code=401,
            detail="invalid_credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return actor


def require_authenticated(
    actor: AuthenticatedActor = Depends(get_current_actor),
) -> AuthenticatedActor:
    """Require valid authenticated actor (operator or client)."""
    return actor


def require_operator(
    actor: AuthenticatedActor = Depends(get_current_actor),
) -> AuthenticatedActor:
    """Require operator role. Fails closed with 403 for client actors."""
    if not actor.is_operator:
        raise HTTPException(
            status_code=403,
            detail="operator_role_required",
        )
    return actor


def resolve_authorized_workspace(
    requested_workspace: str | None,
    actor: AuthenticatedActor,
) -> str:
    """Safely bind caller request to authorized workspace context without trusting arbitrary input."""
    # Operators can access any requested workspace or default
    if actor.is_operator or "*" in actor.workspaces:
        return (requested_workspace or "default").strip()

    # Clients must be strictly bounded to their authorized workspaces
    if requested_workspace:
        ws = requested_workspace.strip()
        if not actor.can_access_workspace(ws):
            _log.warning(
                "workspace_access_violation actor_id=%s requested=%s allowed=%s",
                actor.actor_id,
                ws,
                actor.workspaces,
            )
            raise HTTPException(
                status_code=403,
                detail=f"workspace_access_denied: not authorized for workspace '{ws}'",
            )
        return ws

    # If client did not specify, choose the single authorized workspace or default
    if len(actor.workspaces) == 1:
        return next(iter(actor.workspaces))

    return "default"


def explain_auth_status(environ: Mapping[str, str] | None = None) -> dict[str, Any]:
    """Safe configuration diagnostics that never leak secrets."""
    env = os.environ if environ is None else environ
    prod = is_production_mode(env)
    dev_disabled = is_auth_disabled_in_dev(env)
    op_token: str | None = _get_configured_operator_token(env)
    client_tokens = _get_configured_client_tokens(env)

    return {
        "production_mode": prod,
        "auth_disabled_in_dev": dev_disabled,
        "operator_configured": bool(op_token),
        "client_tokens_count": len(client_tokens),
        "status": "ready" if (op_token or client_tokens or dev_disabled) else "unconfigured",
        "fail_closed_enabled": prod,
    }


__all__ = [
    "AuthenticatedActor",
    "authenticate_token",
    "clear_test_tokens",
    "explain_auth_status",
    "get_current_actor",
    "is_auth_disabled_in_dev",
    "is_production_mode",
    "register_test_token",
    "require_authenticated",
    "require_operator",
    "resolve_authorized_workspace",
]
