"""Tool catalog and side-effect policies; definitions only, no clients."""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from typing import Any, Mapping

TOOL_CATEGORIES = frozenset({"read_file", "write_file", "read_database", "write_database", "search_web", "read_email", "send_email", "read_crm", "write_crm", "read_calendar", "write_calendar", "send_whatsapp", "send_sms", "place_call", "create_invoice", "create_payment", "launch_ad", "publish_site", "create_order", "sync_accounting", "run_script", "query_vector_memory"})
RISK_LEVELS = frozenset({"read_only", "draft_only", "sandbox_write", "approved_write", "capped_live", "blocked"})
AUTH_MODES = frozenset({"none", "api_key", "oauth", "service_account", "user_delegated", "manual_export"})
LIVE_CATEGORIES = frozenset({"send_email", "write_crm", "write_calendar", "send_whatsapp", "send_sms", "place_call", "create_invoice", "create_payment", "launch_ad", "publish_site", "create_order", "sync_accounting", "write_database"})
ToolCategory = str
ToolRiskLevel = str


@dataclass(frozen=True)
class ToolProvider:
    provider_id: str
    name: str
    integration_status: str
    notes: str


@dataclass(frozen=True)
class ToolAuthMode:
    mode: str
    secret_required: bool
    operator_present: bool


@dataclass(frozen=True)
class ToolInputSchema:
    required_fields: tuple[str, ...]
    optional_fields: tuple[str, ...]
    rejects_secrets: bool


@dataclass(frozen=True)
class ToolOutputSchema:
    fields: tuple[str, ...]
    sanitized: bool
    provenance_required: bool


@dataclass(frozen=True)
class ToolCostEstimate:
    unit: str
    estimated_cost: float
    currency: str
    assumption_note: str


@dataclass(frozen=True)
class ToolApprovalPolicy:
    approval_required: bool
    approver_role: str
    pause_event: str


@dataclass(frozen=True)
class ToolSideEffectProfile:
    side_effect_type: str
    reversible: bool
    external_world: bool


@dataclass(frozen=True)
class ToolSandboxPolicy:
    sandbox_allowed: bool
    network_allowed: bool
    filesystem_scope: str
    audit_required: bool


@dataclass(frozen=True)
class ToolDefinition:
    tool_id: str
    name: str
    category: str
    provider_candidates: tuple[str, ...]
    auth_mode: str
    risk_level: str
    default_mode: str
    approval_required: bool
    side_effect_type: str
    cost_estimate: ToolCostEstimate
    input_schema: ToolInputSchema
    output_schema: ToolOutputSchema
    sandbox_policy: ToolSandboxPolicy
    audit_event_type: str
    forbidden_without_approval: tuple[str, ...]
    approval_policy: ToolApprovalPolicy
    side_effect_profile: ToolSideEffectProfile


@dataclass(frozen=True)
class ToolRegistryReport:
    report_version: str
    generated_at: str
    providers: tuple[ToolProvider, ...]
    tools: tuple[ToolDefinition, ...]
    policy: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _tool(category: str, name: str, risk: str | None = None) -> ToolDefinition:
    live = category in LIVE_CATEGORIES
    risk = risk or ("approval_required" if live else "read_only")
    if risk not in RISK_LEVELS:
        risk = "blocked"
    default_mode = "blocked" if live else "read_only"
    return ToolDefinition(category, name, category, ("local_stub",), "manual_export" if category in {"read_file", "read_database"} else "none", risk, default_mode, live, "external_write" if live else "read", ToolCostEstimate("call", 0.0, "USD", "Offline estimate; no call is made."), ToolInputSchema(("sanitized_input",), (), True), ToolOutputSchema(("result", "warnings", "provenance"), True, True), ToolSandboxPolicy(True, False, "workspace_allowlist", True), f"companyos_tool_{category}", ("human approval", "consent", "audit record") if live else (), ToolApprovalPolicy(live, "management", "pause_before_external_action" if live else "none"), ToolSideEffectProfile("external_write" if live else "none", not live, live))


def default_tools() -> list[ToolDefinition]:
    names = [(item, item.replace("_", " ").title()) for item in sorted(TOOL_CATEGORIES)]
    return [_tool(category, name) for category, name in names]


def build_tool_registry(*, generated_at: str = "offline-deterministic", seed: Mapping[str, Any] | None = None) -> ToolRegistryReport:
    tools = default_tools()
    overrides = {str(item.get("tool_id")): item for item in (seed or {}).get("tools", []) if isinstance(item, Mapping)}
    normalized: list[ToolDefinition] = []
    for tool in tools:
        override = overrides.get(tool.tool_id, {})
        risk = str(override.get("risk_level", tool.risk_level))
        if risk not in RISK_LEVELS:
            risk = "blocked"
        normalized.append(replace(tool, risk_level=risk, default_mode="blocked" if tool.category in LIVE_CATEGORIES else tool.default_mode))
    providers = tuple(ToolProvider(provider, provider.replace("_", " ").title(), "reference_only", "No provider client is installed.") for provider in ("local_stub", "mcp_reference", "composio_reference", "pipedream_reference", "activepieces_reference", "n8n_reference", "windmill_reference"))
    return ToolRegistryReport("companyos-tool-registry-v1", generated_at, providers, tuple(normalized), "Tools are schemas with risk, cost, audit, and approval policies. Real-world action tools are blocked by default.")


__all__ = ["TOOL_CATEGORIES", "RISK_LEVELS", "AUTH_MODES", "ToolDefinition", "ToolProvider", "ToolCategory", "ToolAuthMode", "ToolRiskLevel", "ToolInputSchema", "ToolOutputSchema", "ToolCostEstimate", "ToolApprovalPolicy", "ToolSideEffectProfile", "ToolSandboxPolicy", "ToolRegistryReport", "default_tools", "build_tool_registry"]
