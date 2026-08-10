"""JSON-safe vendor capability records used by the ProviderRegistry router."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any


class VendorStage(str, Enum):
    USE_NOW = "use_now"
    EVALUATE_NEXT = "evaluate_next"
    DEFER = "defer"


class IntegrationMode(str, Enum):
    CATALOG_ONLY = "catalog_only"
    MANUAL_EXPORT = "manual_export"
    CSV_IMPORT = "csv_import"
    READ_ONLY_API = "read_only_api"
    WRITE_API_REQUIRES_APPROVAL = "write_api_requires_approval"
    MCP_TOOL = "mcp_tool"
    EMBEDDED_APP = "embedded_app"
    GATEWAY = "gateway"
    SELF_HOSTED_SIDECAR = "self_hosted_sidecar"


class AuthMode(str, Enum):
    NONE = "none"
    MANUAL = "manual"
    API_KEY = "api_key"
    OAUTH = "oauth"
    SERVICE_ROLE = "service_role"
    MCP = "mcp"
    APP_INSTALLATION = "app_installation"


class CostTier(str, Enum):
    FREE = "free"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    ENTERPRISE = "enterprise"
    USAGE_BASED = "usage_based"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class VendorCapability:
    vendor_id: str
    capability_id: str
    integration_mode: IntegrationMode
    auth_mode: AuthMode
    cost_tier: CostTier
    use_stage: VendorStage
    free_plan_available: bool
    paid_when: str
    data_sent: tuple[str, ...]
    data_received: tuple[str, ...]
    canonical_events_emitted: tuple[str, ...]
    workspace_department: str
    agent_owner_role: str
    approval_required: bool
    live_mutation_risk: bool
    mvp_allowed: bool
    open_source_reference: bool = False
    license: str = "proprietary"
    source_urls: tuple[str, ...] = ()
    notes: str = "Verify current pricing before committing spend."

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        for key in ("integration_mode", "auth_mode", "cost_tier", "use_stage"):
            value[key] = value[key].value
        return value

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "VendorCapability":
        data = dict(value)
        data["integration_mode"] = IntegrationMode(data["integration_mode"])
        data["auth_mode"] = AuthMode(data["auth_mode"])
        data["cost_tier"] = CostTier(data["cost_tier"])
        data["use_stage"] = VendorStage(data["use_stage"])
        for field_name in ("data_sent", "data_received", "canonical_events_emitted", "source_urls"):
            data[field_name] = tuple(data.get(field_name, ()))
        return cls(**data)


@dataclass(frozen=True)
class VendorRouteRecommendation:
    capability_id: str
    recommended_vendor_id: str | None
    alternatives: tuple[str, ...]
    use_stage: VendorStage
    rationale: tuple[str, ...]
    blockers: tuple[str, ...]
    required_env_vars: tuple[str, ...]
    required_approvals: tuple[str, ...]
    next_action: str
    manual_mode_available: bool

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["use_stage"] = self.use_stage.value
        return value


__all__ = ["AuthMode", "CostTier", "IntegrationMode", "VendorCapability", "VendorRouteRecommendation", "VendorStage"]
