"""Offline client-workspace isolation and export-boundary planning for TrustOS."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Mapping

from backend.workspaces.client_workspace import ClientWorkspace
from backend.workspaces.registry import WorkspaceRegistry, get_workspace_registry

from .control_plane import ACTION_CATEGORIES, EVIDENCE_STATUSES, _clean
from .gate_runner import evaluate_action

WORKSPACE_TYPES = ("internal_marketos_core", "client_trustops_workspace", "client_companyos_workspace", "client_launch_workspace", "client_growth_workspace", "client_ecommerce_workspace", "client_agency_workspace", "client_readonly_report_workspace")
WORKSPACE_STATUSES = ("draft", "planned", "client_safe", "blocked_internal_leakage", "blocked_cross_client_risk", "blocked_missing_policy", "blocked_missing_review")
DATA_CLASSES = ("internal_prompt", "internal_scoring_formula", "internal_heuristic", "internal_strategy_note", "internal_pricing_note", "internal_upsell_note", "internal_agent_instruction", "source_code", "global_provider_intelligence", "cross_client_learning", "client_private_data", "client_safe_summary", "client_safe_blocker", "client_safe_evidence_requirement", "client_safe_approval_request", "client_safe_next_action", "client_safe_export_packet", "lawyer_ready_packet", "accountant_ready_packet", "security_reviewer_packet")
ACCESS_MODES = ("internal_only", "workspace_only", "client_visible", "aggregated_safe_summary_only", "redacted_summary_only", "blocked")
CLONE_TYPES = ("trustops_readiness_clone", "companyos_operating_clone", "launch_pack_clone", "growth_pack_clone", "provider_risk_clone", "public_launch_readiness_clone")
LEAKAGE_STATUSES = ("pass", "warn", "hard_block", "redacted", "requires_review")
SERVICE_PACKAGES = ("Trust Readiness Snapshot", "Public Launch Readiness Pack", "AI Agent Safety & Governance Audit", "Ecommerce Compliance Readiness", "Provider/Vendor Risk Review", "Monthly TrustOps Retainer", "CompanyOS Setup", "MarketOS Growth Retainer", "Full MarketOS Managed OS")

DEFAULT_ACCESS = {item: "internal_only" for item in DATA_CLASSES}
DEFAULT_ACCESS.update({"client_private_data": "workspace_only", "client_safe_summary": "client_visible", "client_safe_blocker": "client_visible", "client_safe_evidence_requirement": "client_visible", "client_safe_approval_request": "client_visible", "client_safe_next_action": "client_visible", "client_safe_export_packet": "client_visible", "lawyer_ready_packet": "redacted_summary_only", "accountant_ready_packet": "redacted_summary_only", "security_reviewer_packet": "redacted_summary_only", "global_provider_intelligence": "aggregated_safe_summary_only"})
INTERNAL_KEYS = {"internal_prompt", "internal_scoring_formula", "internal_heuristic", "internal_strategy_note", "internal_pricing_note", "internal_upsell_note", "internal_agent_instruction", "source_code", "cross_client_learning"}
SECRET_KEYS = {"api_key", "private_key", "password", "raw_payload", "raw_html", "credentials", "credential", "access_token", "refresh_token", "authorization", "cookie", "cookies", "jwt", "token", "tokens", "client_secret", "webhook_secret", "raw_provider_payload", "provider_payload", "raw_provider_response", "provider_response"}
_FORBIDDEN_KEY_MARKERS = ("prompt", "formula", "heuristic", "strategy", "pricing", "upsell", "agent_instruction", "source_code", "cross_client", "other_client", "private_tenant", "client_private_data", "provider_payload", "raw_payload", "provider_response", "raw_response", "credential", "secret", "password", "api_key", "access_token", "refresh_token", "authorization", "cookie", "token")
_FORBIDDEN_VALUE_MARKERS = ("sk-", "ghp_", "github_pat_", "-----begin", "bearer ", "cookie=", "session=", "<html", "other_client", "cross_client", "prompt", "formula", "heuristic", "strategy", "credential", "token", "cookie", "source code", "provider response", "raw payload")
_SOURCE_CODE_VALUE = re.compile(r"(?im)^\s*(?:def|class|import|from)\s+\w+")
_FILESYSTEM_PATH_VALUE = re.compile(r"(?i)(?:^|[\s=(\[{,:])(?:file://|[a-z]:[\\/]|\\\\|/(?!/)|[^\\/\s]+\\[^\\/\s]+)")
_NON_AUTHORITATIVE_CLAIM_MARKERS = ("actual", "live", "live_validated", "verified_live", "production")
_SAFE_WORKSPACE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_SAFE_PROVENANCE = re.compile(r"^[a-z][a-z0-9+.-]{1,15}://[A-Za-z0-9._/-]{1,192}$")
_ALLOWED_PROVENANCE_SCHEMES = frozenset({"derived", "fixture", "manual", "offline"})
CLIENT_EXPORT_FIELDS = frozenset({"workspace_id", "status", "blockers", "evidence_required", "approvals_required", "next_actions"})
MAX_CLIENT_EVIDENCE_EXPORT_BYTES = 64_000
_EXPORT_ERROR_MESSAGES = {
    "invalid_metadata": "invalid client evidence export",
    "identity_rejected": "client workspace identity rejected",
    "content_rejected": "client evidence export rejected",
    "size_exceeded": "client evidence export exceeds size limit",
}


@dataclass(frozen=True)
class ClientWorkspaceScope:
    scope_id: str
    allowed_modules: tuple[str, ...]
    allowed_reports: tuple[str, ...]
    allowed_exports: tuple[str, ...]
    allowed_actions: tuple[str, ...]
    forbidden_actions: tuple[str, ...]
    data_classes_allowed: tuple[str, ...]
    data_classes_forbidden: tuple[str, ...]
    def to_dict(self) -> dict[str, Any]: return _clean(self)


@dataclass(frozen=True)
class ClientWorkspaceRole:
    role_id: str
    name: str
    permissions: tuple[str, ...]
    client_visible: bool
    internal_only: bool = False
    def to_dict(self) -> dict[str, Any]: return _clean(self)


@dataclass(frozen=True)
class ClientWorkspacePermission:
    permission_id: str
    resource: str
    action: str
    access_mode: str
    approval_required: bool
    def __post_init__(self) -> None:
        if self.access_mode not in ACCESS_MODES or self.action not in ACTION_CATEGORIES: raise ValueError("invalid workspace permission")
    def to_dict(self) -> dict[str, Any]: return _clean(self)


@dataclass(frozen=True)
class ClientWorkspacePolicy:
    policy_id: str
    name: str
    status: str
    redaction_required: bool
    cross_client_isolation: bool
    internal_content_excluded: bool
    professional_review_required: bool
    def to_dict(self) -> dict[str, Any]: return _clean(self)


@dataclass(frozen=True)
class ClientWorkspaceBoundary:
    boundary_id: str
    internal_side: tuple[str, ...]
    external_side: tuple[str, ...]
    prohibited_flows: tuple[str, ...]
    enforcement_mode: str
    def to_dict(self) -> dict[str, Any]: return _clean(self)


@dataclass(frozen=True)
class ClientWorkspaceDataClass:
    data_class: str
    default_visibility: str
    description: str
    export_allowed: bool
    redaction_required: bool
    def __post_init__(self) -> None:
        if self.data_class not in DATA_CLASSES or self.default_visibility not in ACCESS_MODES: raise ValueError("invalid workspace data class")
    def to_dict(self) -> dict[str, Any]: return _clean(self)


@dataclass(frozen=True)
class ClientWorkspaceVisibilityRule:
    rule_id: str
    data_class: str
    access_mode: str
    condition: str
    violation_behavior: str
    def __post_init__(self) -> None:
        if self.data_class not in DATA_CLASSES or self.access_mode not in ACCESS_MODES: raise ValueError("invalid visibility rule")
    def to_dict(self) -> dict[str, Any]: return _clean(self)


@dataclass(frozen=True)
class ClientWorkspaceExportPolicy:
    policy_id: str
    export_type: str
    allowed_fields: tuple[str, ...]
    excluded_fields: tuple[str, ...]
    required_checks: tuple[str, ...]
    professional_review_required: bool
    status: str
    def to_dict(self) -> dict[str, Any]: return _clean(self)


@dataclass(frozen=True)
class ClientWorkspaceCloneManifest:
    clone_id: str
    clone_type: str
    source_internal_report_refs: tuple[str, ...]
    client_visible_report_refs: tuple[str, ...]
    included_modules: tuple[str, ...]
    excluded_modules: tuple[str, ...]
    included_policy_packs: tuple[str, ...]
    excluded_internal_fields: tuple[str, ...]
    export_format: str
    export_scope: str
    retention_policy: str
    redaction_policy: str
    professional_review_required: bool
    generated_artifacts_allowed: bool
    status: str
    def __post_init__(self) -> None:
        if self.clone_type not in CLONE_TYPES or self.generated_artifacts_allowed: raise ValueError("clone must be a curated, non-artifact projection")
    def to_dict(self) -> dict[str, Any]: return _clean(self)


@dataclass(frozen=True)
class ClientWorkspaceRedactionPolicy:
    policy_id: str
    redacted_data_classes: tuple[str, ...]
    rejected_patterns: tuple[str, ...]
    client_export_safe: bool
    notes: str
    def to_dict(self) -> dict[str, Any]: return _clean(self)


@dataclass(frozen=True)
class ClientWorkspaceLeakageCheck:
    finding_id: str
    data_class: str
    field_path: str
    visibility_violation: str
    severity: str
    recommended_action: str
    client_visible: bool
    internal_only: bool
    status: str
    def __post_init__(self) -> None:
        if self.status not in LEAKAGE_STATUSES: raise ValueError("invalid leakage status")
    def to_dict(self) -> dict[str, Any]: return _clean(self)


@dataclass(frozen=True)
class ClientWorkspaceGateResult:
    action: str
    decision: str
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]
    missing_evidence: tuple[str, ...]
    next_action: str
    def __post_init__(self) -> None:
        if self.action not in ACTION_CATEGORIES: raise ValueError("invalid TrustOS action")
    def to_dict(self) -> dict[str, Any]: return _clean(self)


@dataclass(frozen=True)
class ClientWorkspaceRiskItem:
    risk_id: str
    title: str
    severity: str
    description: str
    mitigation: str
    client_visible: bool
    def to_dict(self) -> dict[str, Any]: return _clean(self)


@dataclass(frozen=True)
class ClientWorkspaceSafetySummary:
    read_only: bool = True
    network_calls: bool = False
    database_writes: bool = False
    auth_calls: bool = False
    tenant_created: bool = False
    client_data_present: bool = False
    source_code_exported: bool = False
    internal_prompts_exported: bool = False
    cross_client_data_exported: bool = False
    artifacts_written: bool = False
    def __post_init__(self) -> None:
        if not self.read_only or any((self.network_calls, self.database_writes, self.auth_calls, self.tenant_created, self.client_data_present, self.source_code_exported, self.internal_prompts_exported, self.cross_client_data_exported, self.artifacts_written)): raise ValueError("workspace isolation must remain offline and safe")
    def to_dict(self) -> dict[str, Any]: return _clean(self)


@dataclass(frozen=True)
class ClientWorkspaceManifest:
    workspace_id: str
    client_id_placeholder: str
    workspace_type: str
    allowed_departments: tuple[str, ...]
    allowed_modules: tuple[str, ...]
    allowed_reports: tuple[str, ...]
    allowed_exports: tuple[str, ...]
    allowed_actions: tuple[str, ...]
    forbidden_actions: tuple[str, ...]
    data_classes_allowed: tuple[str, ...]
    data_classes_forbidden: tuple[str, ...]
    credential_visibility: str
    provider_visibility: str
    approval_visibility: str
    evidence_visibility: str
    internal_notes_visibility: str
    cross_client_access: bool
    source_code_access: bool
    prompt_access: bool
    scoring_formula_access: bool
    global_provider_intelligence_access: bool
    created_for_service_package: str
    status: str
    scope: ClientWorkspaceScope
    roles: tuple[ClientWorkspaceRole, ...]
    permissions: tuple[ClientWorkspacePermission, ...]
    policy: ClientWorkspacePolicy
    boundary: ClientWorkspaceBoundary
    def __post_init__(self) -> None:
        if self.workspace_type not in WORKSPACE_TYPES or self.status not in WORKSPACE_STATUSES: raise ValueError("invalid workspace manifest")
        if any((self.cross_client_access, self.source_code_access, self.prompt_access, self.scoring_formula_access, self.global_provider_intelligence_access)): raise ValueError("unsafe workspace access")
    def to_dict(self) -> dict[str, Any]: return _clean(self)


@dataclass(frozen=True)
class ClientWorkspaceIsolationReport:
    report_version: str
    generated_at: str
    manifests: tuple[ClientWorkspaceManifest, ...]
    data_classes: tuple[ClientWorkspaceDataClass, ...]
    visibility_rules: tuple[ClientWorkspaceVisibilityRule, ...]
    clone_manifests: tuple[ClientWorkspaceCloneManifest, ...]
    export_policies: tuple[ClientWorkspaceExportPolicy, ...]
    redaction_policy: ClientWorkspaceRedactionPolicy
    leakage_checks: tuple[ClientWorkspaceLeakageCheck, ...]
    gate_results: tuple[ClientWorkspaceGateResult, ...]
    risks: tuple[ClientWorkspaceRiskItem, ...]
    service_package_mappings: tuple[dict[str, Any], ...]
    safety_summary: ClientWorkspaceSafetySummary
    next_best_action: str
    def to_dict(self) -> dict[str, Any]:
        data = _clean(self)
        checks = self.leakage_checks
        data.update({"workspace_count": len(self.manifests), "workspace_types": sorted({item.workspace_type for item in self.manifests}), "clone_manifest_count": len(self.clone_manifests), "export_policy_count": len(self.export_policies), "leakage_check_count": len(checks), "hard_blocker_count": sum(item.status == "hard_block" for item in checks) + sum(item.decision == "hard_block" for item in self.gate_results), "warning_count": sum(item.status == "warn" for item in checks), "client_safe_workspace_count": sum(item.status == "client_safe" for item in self.manifests), "blocked_workspace_count": sum(item.status.startswith("blocked") for item in self.manifests), "internal_external_separation_summary": "Internal IP and cross-client data stay internal; client exports are curated projections and redacted projections."})
        return data
    def to_markdown(self) -> str:
        data = self.to_dict()
        lines = ["# Client Workspace Isolation Plan", "", "## Executive Summary", "", f"- Workspaces: **{data['workspace_count']}**", f"- Client-safe: **{data['client_safe_workspace_count']}**", f"- Blocked: **{data['blocked_workspace_count']}**", f"- Leakage checks: **{data['leakage_check_count']}**", "- Mode: **offline schema/readiness only**", "", "## Workspace Manifests", "", "| Workspace | Type | Status | Package |", "|---|---|---|---|"]
        lines.extend(f"| {item.workspace_id} | {item.workspace_type} | {item.status} | {item.created_for_service_package} |" for item in self.manifests)
        lines += ["", "## Internal vs External Data Classes", "", "| Data class | Visibility | Export |", "|---|---|---|"]
        lines.extend(f"| {item.data_class} | {item.default_visibility} | {item.export_allowed} |" for item in self.data_classes)
        lines += ["", "## Visibility Rules", ""] + [f"- `{item.data_class}` -> **{item.access_mode}**: {item.condition}" for item in self.visibility_rules]
        lines += ["", "## Clone Manifests", ""] + [f"- `{item.clone_type}`: {item.status}; excluded fields: {len(item.excluded_internal_fields)}" for item in self.clone_manifests]
        lines += ["", "## Export Policies", ""] + [f"- `{item.export_type}`: {item.status}; professional review: {item.professional_review_required}" for item in self.export_policies]
        lines += ["", "## Leakage Checks", "", "| Field | Class | Status | Action |", "|---|---|---|---|"] + [f"| {item.field_path} | {item.data_class} | {item.status} | {item.recommended_action} |" for item in self.leakage_checks]
        lines += ["", "## TrustOS Gate Results", "", "| Action | Decision | Blockers |", "|---|---|---|"] + [f"| {item.action} | {item.decision} | {', '.join(item.blockers) or 'none'} |" for item in self.gate_results]
        lines += ["", "## Service Package Mapping", ""] + [f"- **{item['service_package']}** -> `{item['default_workspace_type']}`; client exports: {', '.join(item['allowed_exports'])}" for item in self.service_package_mappings]
        lines += ["", "## Client-Safe Output Rules", "", "Expose status, blockers, evidence requirements, approvals, next actions, and reviewed packets only. Exclude prompts, formulas, heuristics, source code, global intelligence, pricing strategy, and cross-client learning.", "", "## Safety Boundaries", "", "No auth, database, tenant, network, client data, source-code export, or internal-content export occurred.", "", "## Next Best Action", "", self.next_best_action, ""]
        return "\n".join(lines)


def _data_classes() -> tuple[ClientWorkspaceDataClass, ...]:
    descriptions = {item: item.replace("_", " ").capitalize() for item in DATA_CLASSES}
    return tuple(ClientWorkspaceDataClass(item, DEFAULT_ACCESS[item], descriptions[item], DEFAULT_ACCESS[item] in {"client_visible", "redacted_summary_only", "aggregated_safe_summary_only"}, DEFAULT_ACCESS[item] not in {"client_visible", "workspace_only"}) for item in DATA_CLASSES)


def _scope(workspace_type: str) -> ClientWorkspaceScope:
    allowed_modules = {"client_trustops_workspace": ("trustos",), "client_companyos_workspace": ("trustos", "companyos"), "client_launch_workspace": ("trustos", "launch", "website_store_funnel"), "client_growth_workspace": ("trustos", "commerce", "launch", "website_store_funnel"), "client_ecommerce_workspace": ("trustos", "commerce", "launch", "website_store_funnel"), "client_agency_workspace": ("trustos", "companyos", "commerce"), "client_readonly_report_workspace": ("trustos",)}.get(workspace_type, ("trustos", "companyos", "commerce", "launch", "website_store_funnel"))
    reports = ("client_safe_trustos_report", "client_safe_readiness_report", "client_safe_evidence_checklist")
    actions = ("client_report_generation", "client_workspace_export")
    forbidden = ("publish_site", "activate_provider", "use_credentials", "create_payment", "create_order", "multi_client_workspace_access")
    return ClientWorkspaceScope(f"scope-{workspace_type}", allowed_modules, reports, ("client_safe_report", "professional_packet"), actions, forbidden, tuple(item for item in DATA_CLASSES if DEFAULT_ACCESS[item] in {"client_visible", "redacted_summary_only", "aggregated_safe_summary_only", "workspace_only"}), tuple(item for item in DATA_CLASSES if DEFAULT_ACCESS[item] == "internal_only"),)


def _manifest(workspace_type: str, package: str) -> ClientWorkspaceManifest:
    scope = _scope(workspace_type)
    roles = (ClientWorkspaceRole("client_viewer", "Client Viewer", ("read_client_safe_reports",), True), ClientWorkspaceRole("internal_operator", "Internal Operator", ("review_export",), False, True))
    permissions = tuple(ClientWorkspacePermission(f"permission-{action}", "client_safe_workspace", action, "client_visible" if action == "client_report_generation" else "redacted_summary_only", True) for action in scope.allowed_actions)
    policy = ClientWorkspacePolicy("client-workspace-isolation-v1", "Client-safe export boundary", "approved_metadata_only", True, True, True, True)
    boundary = ClientWorkspaceBoundary("boundary-core-client", ("source_code", "internal_prompts", "internal_formulas", "global_intelligence", "cross_client_learning"), ("client_safe_summary", "client_safe_blocker", "client_safe_evidence_requirement", "client_safe_next_action"), ("internal_to_client_unredacted", "client_to_client", "credential_to_client"), "fail_closed")
    return ClientWorkspaceManifest(f"workspace-{workspace_type}", "client-placeholder", workspace_type, ("risk_approval", "operations"), scope.allowed_modules, scope.allowed_reports, scope.allowed_exports, scope.allowed_actions, scope.forbidden_actions, scope.data_classes_allowed, scope.data_classes_forbidden, "reference_only", "aggregated_safe_summary_only", "client_safe_summary_only", "redacted_summary_only", "internal_only", False, False, False, False, False, package, "client_safe", scope, roles, permissions, policy, boundary)


def _clone(clone_type: str) -> ClientWorkspaceCloneManifest:
    return ClientWorkspaceCloneManifest(f"clone-{clone_type}", clone_type, ("internal_trustos_report", "internal_operating_report"), ("client_safe_trustos_report", "client_safe_readiness_report"), ("trustos",), ("credentials", "provider_internals", "agent_orchestration", "internal_strategy"), ("security_baseline", "privacy_legal_baseline", "public_launch_readiness"), tuple(sorted(INTERNAL_KEYS | {"global_provider_intelligence"})), "json_and_markdown", "workspace_only", "client_policy_defined", "client-workspace-redaction-v1", clone_type in {"lawyer_ready_packet", "provider_risk_clone"}, False, "client_safe")


def _service_mappings() -> tuple[dict[str, Any], ...]:
    mapping = {"Trust Readiness Snapshot": "client_readonly_report_workspace", "Public Launch Readiness Pack": "client_trustops_workspace", "AI Agent Safety & Governance Audit": "client_trustops_workspace", "Ecommerce Compliance Readiness": "client_ecommerce_workspace", "Provider/Vendor Risk Review": "client_trustops_workspace", "Monthly TrustOps Retainer": "client_companyos_workspace", "CompanyOS Setup": "client_companyos_workspace", "MarketOS Growth Retainer": "client_growth_workspace", "Full MarketOS Managed OS": "client_agency_workspace"}
    return tuple({"service_package": name, "default_workspace_type": workspace, "client_visible_reports": ("client_safe_status", "client_safe_blockers", "client_safe_next_actions"), "internal_only_reports": ("internal_strategy_notes", "internal_upsell_notes", "global_provider_intelligence"), "allowed_exports": ("client_safe_report", "professional_packet"), "professional_packets": ("lawyer_ready_packet", "accountant_ready_packet", "security_reviewer_packet"), "upsell_paths": ("next_approved_deliverable",), "retainer_path": name in {"Monthly TrustOps Retainer", "MarketOS Growth Retainer", "Full MarketOS Managed OS"}} for name, workspace in mapping.items())


def check_workspace_leakage(payload: Mapping[str, Any], *, client_safe: bool = True) -> tuple[ClientWorkspaceLeakageCheck, ...]:
    findings: list[ClientWorkspaceLeakageCheck] = []
    def walk(value: Any, path: str = "") -> None:
        if isinstance(value, Mapping):
            for key, child in value.items():
                key_text = str(key).lower().replace("-", "_").replace(" ", "_")
                data_class = next((item for item in DATA_CLASSES if item in key_text), None)
                forbidden_key = (
                    key_text in SECRET_KEYS
                    or data_class in INTERNAL_KEYS
                    or (client_safe and data_class in {"client_private_data", "global_provider_intelligence"})
                    or any(marker in key_text for marker in _FORBIDDEN_KEY_MARKERS)
                    or _contains_filesystem_path(str(key))
                )
                if forbidden_key:
                    cls = data_class or "client_private_data"
                    findings.append(ClientWorkspaceLeakageCheck(f"leak-{len(findings)+1}", cls, f"{path}.{key}".strip("."), "internal content exposed to client projection", "critical" if cls in INTERNAL_KEYS or key_text in SECRET_KEYS else "high", "remove field or replace with an approved redacted summary", False, True, "hard_block"))
                elif data_class in {"lawyer_ready_packet", "accountant_ready_packet", "security_reviewer_packet"}:
                    findings.append(ClientWorkspaceLeakageCheck(f"review-{len(findings)+1}", data_class, f"{path}.{key}".strip("."), "professional packet requires redaction review", "medium", "complete professional review before export", True, False, "requires_review"))
                walk(child, f"{path}.{key}".strip("."))
        elif isinstance(value, (list, tuple)):
            for index, child in enumerate(value): walk(child, f"{path}[{index}]")
        elif isinstance(value, str) and (_contains_forbidden_value(value) or _contains_filesystem_path(value)):
            findings.append(ClientWorkspaceLeakageCheck(f"leak-{len(findings)+1}", "client_private_data", path, "secret or cross-client value detected", "critical", "reject value and request a sanitized replacement", False, True, "hard_block"))
    walk(payload)
    return tuple(findings)


def _contains_forbidden_value(value: str) -> bool:
    lowered = value.lower()
    return any(marker in lowered for marker in _FORBIDDEN_VALUE_MARKERS) or _SOURCE_CODE_VALUE.search(value) is not None


def _contains_filesystem_path(value: str) -> bool:
    return _FILESYSTEM_PATH_VALUE.search(value) is not None


class ClientWorkspaceExportError(ValueError):
    """Stable, non-reflective failure for rejected client evidence exports."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(_EXPORT_ERROR_MESSAGES[code])


@dataclass(frozen=True)
class ClientWorkspaceEvidenceExport:
    export_version: str
    workspace_id: str
    provenance: str
    evidence_state: str
    payload: dict[str, Any]
    redaction_status: str
    redaction_policy_id: str
    redacted_fields: tuple[str, ...]
    fingerprint: str
    payload_size_bytes: int
    max_payload_bytes: int

    def to_dict(self) -> dict[str, Any]:
        return _clean(self)


def _validate_export_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip()) and value == value.strip() and value.isprintable() and len(value.encode("utf-8")) <= 256


def _validate_workspace_id(value: Any) -> bool:
    return _validate_export_text(value) and _SAFE_WORKSPACE_ID.fullmatch(value) is not None


def _validate_provenance(value: Any) -> bool:
    if not _validate_export_text(value) or _SAFE_PROVENANCE.fullmatch(value) is None:
        return False
    scheme, _, reference = value.partition("://")
    return scheme in _ALLOWED_PROVENANCE_SCHEMES and all(part not in {".", ".."} for part in reference.split("/")) and not _contains_forbidden_value(value)


def _is_export_value(value: Any) -> bool:
    if value is None or isinstance(value, (bool, int)):
        return True
    if isinstance(value, str):
        return value.isprintable()
    if isinstance(value, float):
        return value == value and abs(value) != float("inf")
    if isinstance(value, Mapping):
        return all(isinstance(key, str) and _is_export_value(child) for key, child in value.items())
    if isinstance(value, (list, tuple)):
        return all(_is_export_value(child) for child in value)
    return False


def _canonical_export_bytes(value: Any) -> bytes:
    return json.dumps(_clean(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def export_client_evidence(
    *,
    workspace: ClientWorkspace,
    registry: WorkspaceRegistry | None = None,
    provenance: str,
    evidence_state: str,
    payload: Mapping[str, Any],
    max_payload_bytes: int = MAX_CLIENT_EVIDENCE_EXPORT_BYTES,
) -> ClientWorkspaceEvidenceExport:
    """Create one bounded, canonical client-safe evidence projection."""
    if not isinstance(workspace, ClientWorkspace) or (registry is not None and not isinstance(registry, WorkspaceRegistry)):
        raise ClientWorkspaceExportError("invalid_metadata")
    try:
        registered = (registry or get_workspace_registry()).get(workspace.workspace_id)
    except Exception:
        raise ClientWorkspaceExportError("identity_rejected") from None
    if registered is None or registered.to_dict() != workspace.to_dict():
        raise ClientWorkspaceExportError("identity_rejected")
    if (
        not _validate_workspace_id(registered.workspace_id)
        or not _validate_provenance(provenance)
        or evidence_state not in EVIDENCE_STATUSES
        or not isinstance(payload, Mapping)
        or not _is_export_value(payload)
        or ("status" in payload and not isinstance(payload["status"], str))
        or not isinstance(max_payload_bytes, int)
        or isinstance(max_payload_bytes, bool)
        or max_payload_bytes <= 0
        or max_payload_bytes > MAX_CLIENT_EVIDENCE_EXPORT_BYTES
    ):
        raise ClientWorkspaceExportError("invalid_metadata")
    try:
        if any(not isinstance(key, str) or key not in CLIENT_EXPORT_FIELDS for key in payload):
            raise ClientWorkspaceExportError("content_rejected")
        claimed_workspace_id = payload.get("workspace_id")
        if claimed_workspace_id is not None and claimed_workspace_id != registered.workspace_id:
            raise ClientWorkspaceExportError("content_rejected")
        if check_workspace_leakage(payload, client_safe=True):
            raise ClientWorkspaceExportError("content_rejected")
        status_claim = str(payload.get("status", "")).casefold().replace("-", "_").replace(" ", "_")
        if any(marker in status_claim.split("_") for marker in _NON_AUTHORITATIVE_CLAIM_MARKERS):
            raise ClientWorkspaceExportError("content_rejected")
        safe_payload = _clean(dict(payload))
        payload_bytes = _canonical_export_bytes(safe_payload)
        if len(payload_bytes) > max_payload_bytes:
            raise ClientWorkspaceExportError("size_exceeded")
        canonical = _canonical_export_bytes({
            "workspace_id": registered.workspace_id,
            "provenance": provenance,
            "evidence_state": evidence_state,
            "payload": safe_payload,
        })
    except ValueError:
        raise
    except Exception:
        raise ClientWorkspaceExportError("content_rejected") from None
    return ClientWorkspaceEvidenceExport(
        "client-workspace-evidence-export-v1",
        registered.workspace_id,
        provenance,
        evidence_state,
        safe_payload,
        "validated_no_sensitive_fields",
        "client-workspace-redaction-v1",
        (),
        hashlib.sha256(canonical).hexdigest(),
        len(payload_bytes),
        max_payload_bytes,
    )


def build_client_workspace_isolation_report(*, generated_at: str = "offline-deterministic", workspace_type: str | None = None, clone_type: str | None = None, service_package: str | None = None, payload: Mapping[str, Any] | None = None, check_leakage: bool = True) -> ClientWorkspaceIsolationReport:
    selected_type = workspace_type or "client_trustops_workspace"
    if selected_type not in WORKSPACE_TYPES: raise ValueError("unsupported workspace type")
    package = service_package or "Trust Readiness Snapshot"
    if package not in SERVICE_PACKAGES: raise ValueError("unsupported service package")
    manifests = (_manifest(selected_type, package),)
    clones = (_clone(clone_type),) if clone_type else tuple(_clone(item) for item in CLONE_TYPES)
    leakage = check_workspace_leakage(payload or {}, client_safe=True) if check_leakage else ()
    policies = tuple(ClientWorkspaceExportPolicy(f"export-{item}", item, ("status", "blockers", "evidence_required", "approvals_required", "next_actions"), tuple(sorted(INTERNAL_KEYS | {"source_code", "global_provider_intelligence", "cross_client_learning"})), ("leakage_check", "redaction_policy", "client_isolation_policy"), item != "client_safe_report", "approved_metadata_only") for item in ("client_safe_report", "professional_packet"))
    gates = []
    for action in ("client_workspace_export", "client_clone_generation", "client_report_generation", "lawyer_packet_export", "accountant_packet_export", "security_reviewer_packet_export", "client_workspace_activation", "multi_client_workspace_access"):
        base = evaluate_action(action)
        if leakage and action in {"client_workspace_export", "client_clone_generation", "client_workspace_activation", "multi_client_workspace_access"}: decision, blockers = "hard_block", tuple(item.field_path for item in leakage)
        elif action in {"lawyer_packet_export", "accountant_packet_export", "security_reviewer_packet_export"}: decision, blockers = "needs_professional_review", ("professional redaction review required",)
        else: decision, blockers = ("allow" if action == "client_report_generation" else base.decision), base.blockers
        gates.append(ClientWorkspaceGateResult(action, decision, blockers, base.warnings, base.missing_evidence, "Complete isolation and redaction checks before export." if blockers else "Export only the client-safe projection."))
    risks = tuple(ClientWorkspaceRiskItem(f"risk-{item}", title, "high", desc, mitigation, True) for item, title, desc, mitigation in (("internal-leakage", "Internal IP leakage", "Prompts, formulas, source code, and strategy must not cross the boundary.", "Run deterministic leakage checks."), ("cross-client", "Cross-client data exposure", "Workspace exports must remain single-client and scoped.", "Keep cross-client access disabled.")))
    return ClientWorkspaceIsolationReport("client-workspace-isolation-v1", generated_at, manifests, _data_classes(), tuple(ClientWorkspaceVisibilityRule(f"visibility-{item}", item, DEFAULT_ACCESS[item], "default policy", "hard_block" if DEFAULT_ACCESS[item] == "internal_only" else "redact_or_allow") for item in DATA_CLASSES), clones, policies, ClientWorkspaceRedactionPolicy("client-workspace-redaction-v1", tuple(sorted(INTERNAL_KEYS | {"global_provider_intelligence", "client_private_data"})), tuple(sorted(SECRET_KEYS | {"cross_client", "raw_payload", "source_code"})), True, "Client-safe fields only; professional packets require review."), leakage, tuple(gates), risks, _service_mappings(), ClientWorkspaceSafetySummary(), "Keep client exports as curated projections; internal prompts remain internal; next implement reviewed auth/database/RLS separately.")


__all__ = ["WORKSPACE_TYPES", "WORKSPACE_STATUSES", "DATA_CLASSES", "ACCESS_MODES", "CLONE_TYPES", "SERVICE_PACKAGES", "CLIENT_EXPORT_FIELDS", "MAX_CLIENT_EVIDENCE_EXPORT_BYTES", "ClientWorkspaceIsolationReport", "ClientWorkspaceManifest", "ClientWorkspaceScope", "ClientWorkspaceRole", "ClientWorkspacePermission", "ClientWorkspacePolicy", "ClientWorkspaceBoundary", "ClientWorkspaceDataClass", "ClientWorkspaceVisibilityRule", "ClientWorkspaceExportPolicy", "ClientWorkspaceCloneManifest", "ClientWorkspaceRedactionPolicy", "ClientWorkspaceLeakageCheck", "ClientWorkspaceGateResult", "ClientWorkspaceRiskItem", "ClientWorkspaceSafetySummary", "ClientWorkspaceEvidenceExport", "ClientWorkspaceExportError", "check_workspace_leakage", "export_client_evidence", "build_client_workspace_isolation_report"]
