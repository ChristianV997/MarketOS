from __future__ import annotations

from fastapi import APIRouter

from backend.organization.org_registry import get_organization_registry

router = APIRouter(prefix="/api/organization", tags=["organization"])


@router.get("/departments")
def departments() -> dict:
    return {"departments": [d.to_dict() for d in get_organization_registry().list_departments()]}


@router.get("/agents")
def agents() -> dict:
    return {"agents": [a.to_dict() for a in get_organization_registry().list_agents()]}


@router.post("/bootstrap-defaults")
def bootstrap_defaults() -> dict:
    return get_organization_registry().bootstrap_defaults()
