"""Server-only Postgres workspace/profile repository via the existing Supabase client.

The adapter is explicit and injectable.  It never falls back to the JSON
workspace registry, and every read/write resolves membership before applying a
workspace selector.  Supabase is used only as the existing Postgres client
convention; no browser or anonymous access is introduced here.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Mapping, Protocol

from backend.security.principal import VerifiedPrincipal

MAX_JSON_BYTES = 64 * 1024
SECRET_KEY_PARTS = ("secret", "token", "password", "credential", "api_key", "private_key")


class PostgresWorkspaceRepositoryError(RuntimeError):
    """Base error for the explicit Postgres workspace adapter."""


class PostgresRepositoryUnavailable(PostgresWorkspaceRepositoryError):
    """The adapter cannot reach a configured database client."""


class WorkspaceAccessDenied(PostgresWorkspaceRepositoryError):
    """The principal is not authorized for the requested workspace."""


class ClientProfileAlreadyExists(PostgresWorkspaceRepositoryError):
    """A create-only client-profile request targeted an existing profile."""


class WorkspaceSelectionRequired(PostgresWorkspaceRepositoryError):
    """A principal has multiple workspaces and must select one explicitly."""


class WorkspaceRepository(Protocol):
    def resolve_workspace(
        self,
        principal: VerifiedPrincipal,
        *,
        workspace_id: str | None = None,
        workspace_name: str | None = None,
    ) -> "WorkspaceRecord": ...

    def resolve_operator_workspace(self, principal: VerifiedPrincipal) -> "WorkspaceRecord": ...

    def get_operator_client_profile(self, principal: VerifiedPrincipal) -> "ClientProfileRecord | None": ...

    def create_operator_client_profile(
        self,
        principal: VerifiedPrincipal,
        profile: Mapping[str, Any],
    ) -> "ClientProfileRecord": ...

    def update_operator_client_profile(
        self,
        principal: VerifiedPrincipal,
        profile: Mapping[str, Any],
    ) -> "ClientProfileRecord | None": ...

    def upsert_operator_client_profile(
        self,
        principal: VerifiedPrincipal,
        profile: Mapping[str, Any],
    ) -> "ClientProfileRecord": ...


@dataclass(frozen=True)
class WorkspaceRecord:
    workspace_id: str
    name: str
    workspace_type: str = "internal"
    metadata: Mapping[str, Any] | None = None

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "WorkspaceRecord":
        workspace_id = row.get("workspace_id")
        name = row.get("name")
        if not isinstance(workspace_id, str) or not workspace_id.strip() or not isinstance(name, str):
            raise PostgresWorkspaceRepositoryError("workspace row is malformed")
        metadata = row.get("metadata", {})
        if not isinstance(metadata, Mapping):
            raise PostgresWorkspaceRepositoryError("workspace metadata is malformed")
        workspace_type = row.get("workspace_type") or metadata.get("workspace_type", "internal")
        if not isinstance(workspace_type, str) or not workspace_type.strip():
            raise PostgresWorkspaceRepositoryError("workspace type is malformed")
        return cls(workspace_id=workspace_id, name=name, workspace_type=workspace_type, metadata=dict(metadata))


@dataclass(frozen=True)
class ClientProfileRecord:
    workspace_id: str
    company_name: str
    business_type: str
    segments: tuple[Any, ...]
    markets: tuple[Any, ...]
    products_services: tuple[Any, ...]
    social_accounts: tuple[Any, ...]
    metadata: Mapping[str, Any]

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "ClientProfileRecord":
        workspace_id = row.get("workspace_id")
        company_name = row.get("company_name")
        business_type = row.get("business_type", "")
        if (
            not isinstance(workspace_id, str)
            or not workspace_id.strip()
            or not isinstance(company_name, str)
            or not company_name.strip()
            or not isinstance(business_type, str)
        ):
            raise PostgresWorkspaceRepositoryError("profile identity fields are malformed")
        fields: dict[str, tuple[Any, ...]] = {}
        for field in ("segments", "markets", "products_services", "social_accounts"):
            value = row.get(field, [])
            if not isinstance(value, (list, tuple)):
                raise PostgresWorkspaceRepositoryError("profile arrays are malformed")
            fields[field] = tuple(value)
        metadata = row.get("metadata", {})
        if not isinstance(metadata, Mapping):
            raise PostgresWorkspaceRepositoryError("profile metadata is malformed")
        return cls(
            workspace_id=workspace_id,
            company_name=company_name,
            business_type=business_type,
            metadata=dict(metadata),
            **fields,
        )


@dataclass(frozen=True)
class OwnerPortfolioRecord:
    portfolio_id: str
    workspace_id: str
    title: str
    status: str
    payload: Mapping[str, Any]

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "OwnerPortfolioRecord":
        payload = row.get("payload", {})
        if not isinstance(payload, Mapping):
            raise PostgresWorkspaceRepositoryError("portfolio payload is malformed")
        return cls(
            portfolio_id=str(row.get("portfolio_id", "")),
            workspace_id=str(row.get("workspace_id", "")),
            title=str(row.get("title", "")),
            status=str(row.get("status", "advisory")),
            payload=dict(payload),
        )


def _rows(response: Any) -> list[dict[str, Any]]:
    data = response.get("data") if isinstance(response, Mapping) else getattr(response, "data", response)
    if not isinstance(data, (list, tuple)):
        return []
    return [dict(row) for row in data if isinstance(row, Mapping)]


def _safe_json_object(value: Mapping[str, Any], *, label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be an object")
    def reject_restricted_keys(item: Any) -> None:
        if isinstance(item, Mapping):
            for key, child in item.items():
                if not isinstance(key, str):
                    raise ValueError(f"{label} contains a non-string key")
                if any(part in key.lower() for part in SECRET_KEY_PARTS):
                    raise ValueError(f"{label} contains a restricted field")
                reject_restricted_keys(child)
        elif isinstance(item, (list, tuple)):
            for child in item:
                reject_restricted_keys(child)

    reject_restricted_keys(value)
    try:
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError, RecursionError) as exc:
        raise ValueError(f"{label} is not safe JSON") from exc
    if len(encoded.encode("utf-8")) > MAX_JSON_BYTES:
        raise ValueError(f"{label} exceeds the bounded size")
    return dict(value)


class PostgresWorkspaceRepository:
    """Explicit membership-backed repository for Postgres workspace state."""

    def __init__(
        self,
        *,
        url: str | None = None,
        key: str | None = None,
        client: Any | None = None,
    ) -> None:
        self.url = url if url is not None else os.getenv("SUPABASE_URL", "")
        self.key = key if key is not None else os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
        self._client = client

    @property
    def configured(self) -> bool:
        return self._client is not None or bool(self.url and self.key)

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        if not self.url or not self.key:
            raise PostgresRepositoryUnavailable("workspace Postgres adapter is unconfigured")
        try:
            from supabase import create_client
        except ImportError as exc:  # pragma: no cover - dependency is optional in local unit tests.
            raise PostgresRepositoryUnavailable("workspace Postgres client package is unavailable") from exc
        try:
            self._client = create_client(self.url, self.key)
        except Exception as exc:
            raise PostgresRepositoryUnavailable("workspace Postgres client could not be created") from exc
        return self._client

    @staticmethod
    def _require_principal(principal: VerifiedPrincipal) -> str:
        if not isinstance(principal, VerifiedPrincipal):
            raise WorkspaceAccessDenied("verified principal is required")
        return principal.subject

    def _execute(self, query: Any, *, operation: str) -> list[dict[str, Any]]:
        try:
            return _rows(query.execute())
        except PostgresWorkspaceRepositoryError:
            raise
        except Exception as exc:
            code = str(getattr(exc, "code", ""))
            status_code = str(getattr(exc, "status_code", ""))
            if operation == "profile insert" and (code == "23505" or status_code == "409"):
                raise ClientProfileAlreadyExists("client profile already exists") from exc
            raise PostgresWorkspaceRepositoryError(f"workspace Postgres {operation} failed: {type(exc).__name__}") from exc

    def _membership_ids(self, principal: VerifiedPrincipal) -> list[str]:
        subject = self._require_principal(principal)
        query = self._get_client().table("workspace_memberships").select("workspace_id").eq("principal_id", subject)
        rows = self._execute(query, operation="membership lookup")
        ids = sorted({row.get("workspace_id") for row in rows if isinstance(row.get("workspace_id"), str) and row["workspace_id"]})
        return ids

    def _workspace_for_id(self, principal: VerifiedPrincipal, workspace_id: str) -> WorkspaceRecord:
        if not isinstance(workspace_id, str) or not workspace_id.strip():
            raise WorkspaceAccessDenied("workspace access denied")
        if workspace_id not in self._membership_ids(principal):
            raise WorkspaceAccessDenied("workspace access denied")
        query = self._get_client().table("workspaces").select("*").eq("workspace_id", workspace_id).limit(1)
        rows = self._execute(query, operation="workspace lookup")
        if not rows:
            raise WorkspaceAccessDenied("workspace access denied")
        return WorkspaceRecord.from_row(rows[0])

    def resolve_workspace(
        self,
        principal: VerifiedPrincipal,
        *,
        workspace_id: str | None = None,
        workspace_name: str | None = None,
    ) -> WorkspaceRecord:
        """Resolve a workspace only after checking principal membership."""

        ids = self._membership_ids(principal)
        if workspace_id is not None and workspace_name is not None:
            raise WorkspaceAccessDenied("workspace access denied")
        if workspace_id is not None:
            return self._workspace_for_id(principal, workspace_id)
        if workspace_name is not None:
            matches: list[WorkspaceRecord] = []
            for candidate_id in ids:
                try:
                    candidate = self._workspace_for_id(principal, candidate_id)
                except WorkspaceAccessDenied:
                    continue
                if candidate.name == workspace_name:
                    matches.append(candidate)
            if len(matches) == 1:
                return matches[0]
            raise WorkspaceAccessDenied("workspace access denied")
        if len(ids) != 1:
            if not ids:
                raise WorkspaceAccessDenied("workspace access denied")
            raise WorkspaceSelectionRequired("workspace selector is required")
        return self._workspace_for_id(principal, ids[0])

    def resolve_operator_workspace(self, principal: VerifiedPrincipal) -> WorkspaceRecord:
        """Resolve one client-service workspace from an unambiguous operator membership."""
        subject = self._require_principal(principal)
        query = self._get_client().table("workspace_memberships").select("workspace_id,role").eq("principal_id", subject)
        rows = self._execute(query, operation="operator membership lookup")
        membership_roles: dict[str, set[str]] = {}
        allowed_roles = {"owner", "operator", "member", "reader"}
        for row in rows:
            workspace_id = row.get("workspace_id")
            role = row.get("role")
            if (
                not isinstance(workspace_id, str)
                or not workspace_id.strip()
                or not isinstance(role, str)
                or role not in allowed_roles
            ):
                raise WorkspaceAccessDenied("operator membership is malformed")
            membership_roles.setdefault(workspace_id, set()).add(role)
        if any(len(roles) != 1 for roles in membership_roles.values()):
            raise WorkspaceAccessDenied("operator membership is ambiguous")
        operator_ids: set[str] = set()
        for workspace_id, roles in membership_roles.items():
            if roles == {"operator"}:
                operator_ids.add(workspace_id)
        ids = sorted(operator_ids)
        if len(ids) != 1:
            raise WorkspaceAccessDenied("operator workspace access denied")
        workspace_query = self._get_client().table("workspaces").select("*").eq("workspace_id", ids[0]).limit(1)
        workspace_rows = self._execute(workspace_query, operation="operator workspace lookup")
        if not workspace_rows:
            raise WorkspaceAccessDenied("operator workspace access denied")
        workspace = WorkspaceRecord.from_row(workspace_rows[0])
        if workspace.workspace_type != "client_service":
            raise WorkspaceAccessDenied("operator workspace is not a client service workspace")
        return workspace

    def _get_client_profile_for_workspace(self, workspace: WorkspaceRecord) -> ClientProfileRecord | None:
        query = self._get_client().table("workspace_profiles").select("*").eq("workspace_id", workspace.workspace_id).limit(1)
        rows = self._execute(query, operation="profile lookup")
        return ClientProfileRecord.from_row(rows[0]) if rows else None

    def get_client_profile(self, principal: VerifiedPrincipal, *, workspace_id: str | None = None, workspace_name: str | None = None) -> ClientProfileRecord | None:
        workspace = self.resolve_workspace(principal, workspace_id=workspace_id, workspace_name=workspace_name)
        return self._get_client_profile_for_workspace(workspace)

    def get_operator_client_profile(self, principal: VerifiedPrincipal) -> ClientProfileRecord | None:
        workspace = self.resolve_operator_workspace(principal)
        return self._get_client_profile_for_workspace(workspace)

    @staticmethod
    def _client_profile_row(workspace: WorkspaceRecord, profile: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(profile, Mapping):
            raise ValueError("client profile must be an object")
        if "workspace_id" in profile:
            raise ValueError("workspace_id is selected by the verified principal, not the payload")
        allowed_fields = {
            "company_name", "business_type", "segments", "markets",
            "products_services", "social_accounts", "metadata",
        }
        if any(not isinstance(key, str) or key not in allowed_fields for key in profile):
            raise ValueError("client profile contains an unsupported field")
        safe = _safe_json_object(profile, label="client profile")
        company_name = safe.get("company_name")
        business_type = safe.get("business_type")
        if (
            not isinstance(company_name, str)
            or not company_name.strip()
            or len(company_name.strip()) > 120
            or (business_type is not None and (not isinstance(business_type, str) or not business_type.strip() or len(business_type.strip()) > 120))
        ):
            raise ValueError("client profile identity fields are invalid")
        row: dict[str, Any] = {
            "workspace_id": workspace.workspace_id,
            "company_name": company_name.strip(),
            "business_type": business_type.strip() if isinstance(business_type, str) else "",
            "segments": safe.get("segments", []),
            "markets": safe.get("markets", []),
            "products_services": safe.get("products_services", []),
            "social_accounts": safe.get("social_accounts", []),
            "metadata": safe.get("metadata", {}),
        }
        for field in ("segments", "markets"):
            values = row[field]
            if not isinstance(values, list) or len(values) > 32 or any(
                not isinstance(value, str) or not value.strip() or len(value.strip()) > 120
                for value in values
            ):
                raise ValueError(f"client profile {field} is invalid")
            row[field] = [value.strip() for value in values]
        offerings = row["products_services"]
        if not isinstance(offerings, list) or len(offerings) > 32:
            raise ValueError("client profile products_services is invalid")
        for offering in offerings:
            if not isinstance(offering, Mapping) or set(offering) - {"name", "kind", "category"}:
                raise ValueError("client profile offering is invalid")
            if (
                not isinstance(offering.get("name"), str)
                or not offering["name"].strip()
                or len(offering["name"].strip()) > 120
                or not isinstance(offering.get("kind"), str)
                or offering["kind"] not in {"product", "service"}
                or (offering.get("category") is not None and (
                    not isinstance(offering["category"], str)
                    or not offering["category"].strip()
                    or len(offering["category"].strip()) > 120
                ))
            ):
                raise ValueError("client profile offering is invalid")
        socials = row["social_accounts"]
        if not isinstance(socials, list) or len(socials) > 16:
            raise ValueError("client profile social_accounts is invalid")
        allowed_platforms = {"facebook", "instagram", "linkedin", "pinterest", "tiktok", "x", "youtube", "other"}
        for social in socials:
            if not isinstance(social, Mapping) or set(social) - {"platform", "handle", "connection_status"}:
                raise ValueError("client profile social account is invalid")
            if (
                not isinstance(social.get("platform"), str)
                or social["platform"] not in allowed_platforms
                or not isinstance(social.get("handle"), str)
                or not social["handle"].strip()
                or len(social["handle"].strip()) > 64
                or social.get("connection_status", "unconnected") != "unconnected"
            ):
                raise ValueError("client social accounts must remain unconnected metadata")
        if not isinstance(row["metadata"], Mapping):
            raise ValueError("client profile metadata must be an object")
        row["social_accounts"] = [
            {**dict(social), "handle": social["handle"].strip(), "connection_status": "unconnected"}
            for social in socials
        ]
        return _safe_json_object(row, label="client profile")

    def _upsert_client_profile_for_workspace(
        self,
        workspace: WorkspaceRecord,
        profile: Mapping[str, Any],
    ) -> ClientProfileRecord:
        row = self._client_profile_row(workspace, profile)
        try:
            query = self._get_client().table("workspace_profiles").upsert(row, on_conflict="workspace_id")
            rows = self._execute(query, operation="profile upsert")
        except PostgresWorkspaceRepositoryError:
            raise
        if rows:
            return ClientProfileRecord.from_row(rows[0])
        return ClientProfileRecord.from_row(row)

    def upsert_client_profile(self, principal: VerifiedPrincipal, profile: Mapping[str, Any], *, workspace_id: str | None = None, workspace_name: str | None = None) -> ClientProfileRecord:
        workspace = self.resolve_workspace(principal, workspace_id=workspace_id, workspace_name=workspace_name)
        return self._upsert_client_profile_for_workspace(workspace, profile)

    def upsert_operator_client_profile(
        self,
        principal: VerifiedPrincipal,
        profile: Mapping[str, Any],
    ) -> ClientProfileRecord:
        workspace = self.resolve_operator_workspace(principal)
        return self._upsert_client_profile_for_workspace(workspace, profile)

    def create_operator_client_profile(
        self,
        principal: VerifiedPrincipal,
        profile: Mapping[str, Any],
    ) -> ClientProfileRecord:
        workspace = self.resolve_operator_workspace(principal)
        row = self._client_profile_row(workspace, profile)
        query = self._get_client().table("workspace_profiles").insert(row).select("*")
        rows = self._execute(query, operation="profile insert")
        return ClientProfileRecord.from_row(rows[0] if rows else row)

    def update_operator_client_profile(
        self,
        principal: VerifiedPrincipal,
        profile: Mapping[str, Any],
    ) -> ClientProfileRecord | None:
        workspace = self.resolve_operator_workspace(principal)
        row = self._client_profile_row(workspace, profile)
        query = (
            self._get_client()
            .table("workspace_profiles")
            .update(row)
            .eq("workspace_id", workspace.workspace_id)
            .select("*")
        )
        rows = self._execute(query, operation="profile update")
        return ClientProfileRecord.from_row(rows[0]) if rows else None

    def get_owner_portfolio(self, principal: VerifiedPrincipal, portfolio_id: str) -> OwnerPortfolioRecord | None:
        if not isinstance(portfolio_id, str) or not portfolio_id.strip():
            raise ValueError("portfolio_id is required")
        subject = self._require_principal(principal)
        query = self._get_client().table("owner_portfolios").select("*").eq("portfolio_id", portfolio_id).limit(1)
        rows = self._execute(query, operation="portfolio lookup")
        if not rows:
            return None
        record = OwnerPortfolioRecord.from_row(rows[0])
        if record.workspace_id not in self._membership_ids(principal):
            raise WorkspaceAccessDenied("workspace access denied")
        del subject
        return record

    def upsert_owner_portfolio(self, principal: VerifiedPrincipal, portfolio: Mapping[str, Any], *, workspace_id: str | None = None, workspace_name: str | None = None) -> OwnerPortfolioRecord:
        workspace = self.resolve_workspace(principal, workspace_id=workspace_id, workspace_name=workspace_name)
        if "workspace_id" not in portfolio or "portfolio_id" not in portfolio:
            raise ValueError("portfolio_id and workspace_id are required for a portfolio record")
        if portfolio.get("workspace_id") != workspace.workspace_id:
            raise WorkspaceAccessDenied("workspace access denied")
        safe = _safe_json_object(portfolio, label="owner portfolio")
        payload = safe.get("payload", {})
        if not isinstance(payload, Mapping):
            raise ValueError("owner portfolio payload must be an object")
        row = {
            "portfolio_id": safe["portfolio_id"],
            "workspace_id": workspace.workspace_id,
            "title": str(safe.get("title", "")),
            "status": str(safe.get("status", "advisory")),
            "payload": dict(payload),
        }
        safe_row = _safe_json_object(row, label="owner portfolio")
        try:
            query = self._get_client().table("owner_portfolios").upsert(safe_row, on_conflict="portfolio_id")
            rows = self._execute(query, operation="portfolio upsert")
        except PostgresWorkspaceRepositoryError:
            raise
        return OwnerPortfolioRecord.from_row(rows[0] if rows else row)


__all__ = [
    "ClientProfileRecord",
    "ClientProfileAlreadyExists",
    "MAX_JSON_BYTES",
    "OwnerPortfolioRecord",
    "PostgresRepositoryUnavailable",
    "PostgresWorkspaceRepository",
    "PostgresWorkspaceRepositoryError",
    "WorkspaceAccessDenied",
    "WorkspaceRecord",
    "WorkspaceRepository",
    "WorkspaceSelectionRequired",
]