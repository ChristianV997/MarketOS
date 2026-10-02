from __future__ import annotations

from typing import Annotated, Literal, NoReturn

from fastapi import APIRouter, Body, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError

from backend.organization.org_registry import get_organization_registry
from backend.security.principal import VerifiedPrincipal, require_verified_principal
from backend.security.workspace_access import get_workspace_repository
from backend.workspaces.postgres_repository import (
    ClientProfileAlreadyExists,
    ClientProfileRecord,
    PostgresWorkspaceRepositoryError,
    WorkspaceAccessDenied,
    WorkspaceRepository,
)
from evaluation.trustos.client_workspace_isolation import check_workspace_leakage

router = APIRouter(prefix="/api/organization", tags=["organization"])
CompanyName = Annotated[str, StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=120)]
ProfileLabel = Annotated[str, StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=120)]
SocialHandleText = Annotated[str, StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=64)]


class ClientOffering(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: ProfileLabel
    kind: Literal["product", "service"]
    category: ProfileLabel | None = None


class ClientSocialHandle(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    platform: Literal["facebook", "instagram", "linkedin", "pinterest", "tiktok", "x", "youtube", "other"]
    handle: SocialHandleText
    connection_status: Literal["unconnected"] = "unconnected"


class ClientProfileResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    company_name: CompanyName
    business_type: ProfileLabel | None = None
    segments: list[ProfileLabel] = Field(default_factory=list, max_length=32)
    target_markets: list[ProfileLabel] = Field(default_factory=list, max_length=32)
    products_services: list[ClientOffering] = Field(default_factory=list, max_length=32)
    social_accounts: list[ClientSocialHandle] = Field(default_factory=list, max_length=16)


class ClientProfileCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    company_name: CompanyName
    business_type: ProfileLabel | None = None
    segments: list[ProfileLabel] = Field(default_factory=list, max_length=32)
    target_markets: list[ProfileLabel] = Field(default_factory=list, max_length=32)
    products_services: list[ClientOffering] = Field(default_factory=list, max_length=32)
    social_accounts: list[ClientSocialHandle] = Field(default_factory=list, max_length=16)


class ClientProfilePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    company_name: CompanyName | None = None
    business_type: ProfileLabel | None = None
    segments: list[ProfileLabel] | None = Field(default=None, max_length=32)
    target_markets: list[ProfileLabel] | None = Field(default=None, max_length=32)
    products_services: list[ClientOffering] | None = Field(default=None, max_length=32)
    social_accounts: list[ClientSocialHandle] | None = Field(default=None, max_length=16)


def _reject_workspace_selector(request: Request) -> None:
    query_selectors = {"workspace_id", "workspace_name"}
    header_selectors = {
        "x-workspace-id",
        "x-workspace-name",
        "x-marketos-workspace-id",
        "x-marketos-workspace-name",
    }
    if any(key in request.query_params for key in query_selectors) or any(
        key in request.headers for key in header_selectors
    ):
        raise HTTPException(status_code=400, detail="workspace selectors are not accepted")


def _profile_response(record: ClientProfileRecord) -> ClientProfileResponse:
    profile = {
        "company_name": record.company_name,
        "business_type": record.business_type or None,
        "segments": list(record.segments),
        "target_markets": list(record.markets),
        "products_services": list(record.products_services),
        "social_accounts": list(record.social_accounts),
    }
    try:
        response = ClientProfileResponse.model_validate(profile)
    except ValidationError as exc:
        raise HTTPException(status_code=409, detail="stored client profile is invalid") from exc
    if check_workspace_leakage(response.model_dump(mode="json"), client_safe=True):
        raise HTTPException(status_code=409, detail="stored client profile failed TrustOS checks")
    return response


def _storage_profile(profile: ClientProfileResponse, *, metadata: object = None) -> dict[str, object]:
    value = profile.model_dump(mode="json")
    value["markets"] = value.pop("target_markets")
    value["metadata"] = dict(metadata) if isinstance(metadata, dict) else {}
    return value


def _raise_profile_repository_error(exc: Exception) -> NoReturn:
    if isinstance(exc, WorkspaceAccessDenied):
        raise HTTPException(status_code=403, detail="operator workspace access denied") from exc
    if isinstance(exc, ClientProfileAlreadyExists):
        raise HTTPException(status_code=409, detail="client profile already exists") from exc
    if isinstance(exc, PostgresWorkspaceRepositoryError):
        raise HTTPException(status_code=503, detail="client profile repository unavailable") from exc
    if isinstance(exc, ValueError):
        raise HTTPException(status_code=422, detail="client profile is invalid") from exc
    raise exc


@router.get("/departments")
def departments() -> dict:
    return {"departments": [d.to_dict() for d in get_organization_registry().list_departments()]}


@router.get("/agents")
def agents() -> dict:
    return {"agents": [a.to_dict() for a in get_organization_registry().list_agents()]}


@router.get("/defaults")
def defaults() -> dict:
    registry = get_organization_registry()
    return {"departments": [d.to_dict() for d in registry.list_departments()], "agents": [a.to_dict() for a in registry.list_agents()], "bootstrapped": bool(registry.list_departments())}


@router.post("/bootstrap-defaults")
def bootstrap_defaults() -> dict:
    return get_organization_registry().bootstrap_defaults()


@router.post(
    "/client-profile",
    response_model=ClientProfileResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_client_profile(
    request: Request,
    principal: VerifiedPrincipal = Depends(require_verified_principal),
    repository: WorkspaceRepository = Depends(get_workspace_repository),
    create: ClientProfileCreate = Body(...),
) -> ClientProfileResponse:
    _reject_workspace_selector(request)
    profile = ClientProfileResponse.model_validate(create.model_dump())
    if check_workspace_leakage(profile.model_dump(mode="json"), client_safe=True):
        raise HTTPException(status_code=422, detail="client profile failed TrustOS checks")
    try:
        saved = repository.create_operator_client_profile(
            principal,
            _storage_profile(profile),
        )
    except (PostgresWorkspaceRepositoryError, ValueError) as exc:
        _raise_profile_repository_error(exc)
    return _profile_response(saved)


@router.get("/client-profile", response_model=ClientProfileResponse)
def get_client_profile(
    request: Request,
    principal: VerifiedPrincipal = Depends(require_verified_principal),
    repository: WorkspaceRepository = Depends(get_workspace_repository),
) -> ClientProfileResponse:
    _reject_workspace_selector(request)
    try:
        record = repository.get_operator_client_profile(principal)
    except (PostgresWorkspaceRepositoryError, ValueError) as exc:
        _raise_profile_repository_error(exc)
    if record is None:
        raise HTTPException(status_code=404, detail="client profile not found")
    return _profile_response(record)


@router.patch("/client-profile", response_model=ClientProfileResponse)
def patch_client_profile(
    request: Request,
    principal: VerifiedPrincipal = Depends(require_verified_principal),
    repository: WorkspaceRepository = Depends(get_workspace_repository),
    patch: ClientProfilePatch = Body(...),
) -> ClientProfileResponse:
    _reject_workspace_selector(request)
    patch_values = patch.model_dump(exclude_unset=True)
    if not patch_values or any(value is None for value in patch_values.values()):
        raise HTTPException(status_code=422, detail="profile patch must contain non-null fields")
    try:
        current = repository.get_operator_client_profile(principal)
        if current is None:
            raise HTTPException(status_code=404, detail="client profile not found")
        values = _profile_response(current).model_dump(mode="python")
        values.update(patch_values)
        profile = ClientProfileResponse.model_validate(values)
        if check_workspace_leakage(profile.model_dump(mode="json"), client_safe=True):
            raise HTTPException(status_code=422, detail="client profile failed TrustOS checks")
        saved = repository.update_operator_client_profile(
            principal,
            _storage_profile(profile, metadata=current.metadata),
        )
        if saved is None:
            raise HTTPException(status_code=404, detail="client profile not found")
    except HTTPException:
        raise
    except (PostgresWorkspaceRepositoryError, ValueError) as exc:
        _raise_profile_repository_error(exc)
    return _profile_response(saved)


__all__ = ["router"]
