"""Client-profile API: ``/api/organization/client-profile`` (GET, POST, PATCH).

Authenticated, workspace-scoped and metadata-only. The caller's workspace is
resolved server-side from the verified principal's registered membership and its
role (``backend.identity.http.require_workspace_permission``); no query, header or
body value selects or names a workspace, and a body that tries is rejected.
Persistence is ``backend.identity.repository`` (``client_profiles`` /
``client_profile_entries``); this module adds no store and no auth system.

Social accounts are recorded handles only. The API reports them as
``not_connected``, and rejects credentials and any caller claim of a connection.
Requests and responses pass the TrustOS client-workspace leakage check
(``evaluation.trustos.client_workspace_isolation.check_workspace_leakage``).

Nothing here calls Clerk, Supabase, a social platform or any other external service.
"""
from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable
from typing import Any, TypeVar

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from starlette.concurrency import run_in_threadpool

from backend.identity.errors import IdentityFoundationError, ProfileExportRejected, ProfileNotFound, StorageUnavailable
from backend.identity.http import get_workspace_repository, http_exception, require_workspace_permission
from backend.identity.repository import (
    BUSINESS_TYPES,
    CLIENT_TYPE,
    ClientProfile,
    EntryInput,
    PostgresWorkspaceRepository,
)
from backend.identity.roles import PROFILE_CREATE, PROFILE_READ, PROFILE_UPDATE
from backend.identity.workspaces import WorkspaceAccess
from evaluation.trustos.client_workspace_isolation import SECRET_KEYS, check_workspace_leakage

_log = logging.getLogger("marketos.client_profile")
_T = TypeVar("_T")

router = APIRouter(prefix="/api/organization", tags=["client-profile"])

MAX_BODY_BYTES = 16 * 1024
MAX_COMPANY_NAME = 200
MAX_LABEL = 120
MAX_ENTRIES_PER_KIND = 25
SOCIAL_PLATFORMS = ("facebook", "instagram", "linkedin", "other", "pinterest", "threads", "tiktok", "x", "youtube")
HANDLE_PATTERN = re.compile(r"^@?[A-Za-z0-9._]{1,64}$")
NOT_CONNECTED = "not_connected"  # the repository stores this state as 'record_only'

_LIST_FIELDS = {"segments": "segment", "target_markets": "target_market", "offerings": "offering"}
_KNOWN_FIELDS = frozenset({"company_name", "business_type", "social_accounts", *_LIST_FIELDS})
_WORKSPACE_KEYS = frozenset(
    {"workspace_id", "workspace", "workspace_name", "tenant", "tenant_id", "org_id", "organization_id", "user_id", "subject", "issuer"}
)
_CONNECTION_KEYS = frozenset(
    {"connection_state", "connection_status", "connection", "connected", "is_connected", "status", "linked", "authorized", "oauth"}
)
_CREDENTIAL_MARKERS = ("token", "secret", "password", "credential", "api_key", "authorization", "cookie", "jwt", "bearer")
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")


class ProfileValidationError(Exception):
    """A rejected request. Carries a fixed code and a known field name, never caller input."""

    def __init__(self, code: str, field: str | None = None) -> None:
        self.code = code
        self.field = field
        super().__init__(code)


def _validation_http(exc: ProfileValidationError) -> HTTPException:
    return HTTPException(status_code=422, detail={"code": exc.code, "field": exc.field})


def _norm(key: Any) -> str:
    return str(key).strip().lower().replace("-", "_").replace(" ", "_")


def _walk_keys(value: Any):
    if isinstance(value, dict):
        for key, child in value.items():
            yield key
            yield from _walk_keys(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_keys(child)


def _text(value: Any, field: str, max_len: int) -> str:
    if not isinstance(value, str):
        raise ProfileValidationError("invalid_value", field)
    cleaned = value.strip()
    if not cleaned or len(cleaned) > max_len or _CONTROL_CHARS.search(cleaned):
        raise ProfileValidationError("invalid_value", field)
    return cleaned


def _screen(data: dict[str, Any]) -> None:
    """Reject selectors, connection claims, credentials and leaked content before any field parsing."""
    keys = [_norm(key) for key in _walk_keys(data)]
    if any(key in _WORKSPACE_KEYS for key in keys):
        raise ProfileValidationError("workspace_selector_rejected")
    if any(key in _CONNECTION_KEYS for key in keys):
        raise ProfileValidationError("connection_claim_rejected", "social_accounts")
    if any(key in SECRET_KEYS or any(marker in key for marker in _CREDENTIAL_MARKERS) for key in keys):
        raise ProfileValidationError("credentials_rejected")
    if check_workspace_leakage(data):
        raise ProfileValidationError("content_rejected")


def _entries_for(field: str, value: Any) -> list[EntryInput]:
    if not isinstance(value, list) or len(value) > MAX_ENTRIES_PER_KIND:
        raise ProfileValidationError("invalid_value", field)
    if field == "social_accounts":
        entries: list[EntryInput] = []
        for item in value:
            if not isinstance(item, dict) or set(item) != {"platform", "handle"}:
                raise ProfileValidationError("invalid_value", field)
            platform = _text(item["platform"], field, 64).lower()
            handle = _text(item["handle"], field, 65)
            if platform not in SOCIAL_PLATFORMS or not HANDLE_PATTERN.fullmatch(handle):
                raise ProfileValidationError("invalid_value", field)
            entries.append(("social_account", handle, platform))
        seen = {(label.lower(), platform) for _, label, platform in entries}
        if len(seen) != len(entries):
            raise ProfileValidationError("duplicate_entry", field)
        return entries
    kind = _LIST_FIELDS[field]
    labels = [_text(item, field, MAX_LABEL) for item in value]
    if len({label.lower() for label in labels}) != len(labels):
        raise ProfileValidationError("duplicate_entry", field)
    return [(kind, label, None) for label in labels]


def validate_profile(data: Any, *, partial: bool) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise ProfileValidationError("invalid_json")
    _screen(data)
    if any(key not in _KNOWN_FIELDS for key in data):
        raise ProfileValidationError("unknown_field")
    if partial and not data:
        raise ProfileValidationError("empty_update")
    if not partial:
        for required in ("company_name", "business_type"):
            if required not in data:
                raise ProfileValidationError("missing_field", required)
    result: dict[str, Any] = {"replace_entries": {}}
    if "company_name" in data:
        result["company_name"] = _text(data["company_name"], "company_name", MAX_COMPANY_NAME)
    if "business_type" in data:
        if data["business_type"] not in BUSINESS_TYPES:
            raise ProfileValidationError("invalid_value", "business_type")
        result["business_type"] = data["business_type"]
    for field in (*_LIST_FIELDS, "social_accounts"):
        if field in data:
            kind = "social_account" if field == "social_accounts" else _LIST_FIELDS[field]
            result["replace_entries"][kind] = _entries_for(field, data[field])
    return result


async def _read_object(request: Request) -> Any:
    if request.headers.get("content-type", "").split(";")[0].strip().lower() != "application/json":
        raise HTTPException(status_code=415, detail={"code": "unsupported_media_type"})
    declared = request.headers.get("content-length")
    if declared is not None and declared.isdigit() and int(declared) > MAX_BODY_BYTES:
        raise HTTPException(status_code=413, detail={"code": "payload_too_large"})
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > MAX_BODY_BYTES:
            raise HTTPException(status_code=413, detail={"code": "payload_too_large"})
        chunks.append(chunk)
    try:
        return json.loads(b"".join(chunks))
    except (ValueError, RecursionError):
        raise HTTPException(status_code=422, detail={"code": "invalid_json", "field": None}) from None


def _present(profile: ClientProfile) -> dict[str, Any]:
    body: dict[str, Any] = {
        "company_name": profile.company_name,
        "business_type": profile.business_type,
        "segments": [e.label for e in profile.entries if e.kind == "segment"],
        "target_markets": [e.label for e in profile.entries if e.kind == "target_market"],
        "offerings": [e.label for e in profile.entries if e.kind == "offering"],
        "social_accounts": [
            {"platform": e.platform, "handle": e.label, "connection_state": NOT_CONNECTED}
            for e in profile.entries
            if e.kind == "social_account"
        ],
    }
    if check_workspace_leakage(body):
        # Fail closed: a stored value that no longer passes the TrustOS boundary is never returned.
        raise http_exception(ProfileExportRejected())
    return body


async def _call(operation: Callable[[], _T]) -> _T:
    try:
        return await run_in_threadpool(operation)
    except IdentityFoundationError as exc:
        raise http_exception(exc) from None
    except ValueError:
        raise HTTPException(status_code=422, detail={"code": "invalid_value", "field": None}) from None
    except Exception as exc:
        _log.warning("client profile storage failed: %s", type(exc).__name__)
        raise http_exception(StorageUnavailable()) from None


def _no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"


@router.get("/client-profile")
async def get_client_profile(
    response: Response,
    access: WorkspaceAccess = Depends(require_workspace_permission(CLIENT_TYPE, PROFILE_READ)),
    repository: PostgresWorkspaceRepository = Depends(get_workspace_repository),
) -> dict[str, Any]:
    _no_store(response)
    profile = await _call(lambda: repository.get_client_profile(access, permission=PROFILE_READ))
    if profile is None:
        raise http_exception(ProfileNotFound())
    return _present(profile)


@router.post("/client-profile", status_code=201)
async def create_client_profile(
    request: Request,
    response: Response,
    access: WorkspaceAccess = Depends(require_workspace_permission(CLIENT_TYPE, PROFILE_CREATE)),
    repository: PostgresWorkspaceRepository = Depends(get_workspace_repository),
) -> dict[str, Any]:
    _no_store(response)
    try:
        fields = validate_profile(await _read_object(request), partial=False)
    except ProfileValidationError as exc:
        raise _validation_http(exc) from None
    entries = [e for kind in ("segment", "target_market", "offering", "social_account") for e in fields["replace_entries"].get(kind, [])]
    profile = await _call(
        lambda: repository.create_client_profile(
            access,
            company_name=fields["company_name"],
            business_type=fields["business_type"],
            entries=entries,
            permission=PROFILE_CREATE,
        )
    )
    return _present(profile)


@router.patch("/client-profile")
async def update_client_profile(
    request: Request,
    response: Response,
    access: WorkspaceAccess = Depends(require_workspace_permission(CLIENT_TYPE, PROFILE_UPDATE)),
    repository: PostgresWorkspaceRepository = Depends(get_workspace_repository),
) -> dict[str, Any]:
    _no_store(response)
    try:
        fields = validate_profile(await _read_object(request), partial=True)
    except ProfileValidationError as exc:
        raise _validation_http(exc) from None
    profile = await _call(
        lambda: repository.update_client_profile(
            access,
            company_name=fields.get("company_name"),
            business_type=fields.get("business_type"),
            replace_entries=fields["replace_entries"],
            permission=PROFILE_UPDATE,
        )
    )
    return _present(profile)
