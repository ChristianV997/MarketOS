"""Offline credential metadata and secret-manager references for CompanyOS.

Only references, scopes, owners, budgets, rotation policy, and health metadata
are represented here.  Secret values are intentionally not a supported field.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, replace
from typing import Any, Mapping, Sequence

CREDENTIAL_TYPES = ("api_key", "oauth_token", "service_account", "user_delegated_oauth", "manual_export", "webhook_secret", "database_connection", "model_gateway_key", "vector_store_key", "none")
SECRET_MANAGERS = ("infisical", "doppler", "aws_secrets_manager", "gcp_secret_manager", "azure_key_vault", "supabase_secrets", "github_actions_secrets", "environment_variable", "manual_reference", "none")
CREDENTIAL_STATUSES = ("planned", "needed", "configured_reference_only", "pending_approval", "active_reference_only", "expired", "revoked", "blocked")
RISK_LEVELS = ("low", "medium", "high", "critical", "blocked")
SECRET_KEYS = frozenset({"actual_secret_value", "raw_api_key", "raw_oauth_token", "password", "private_key_material", "api_key", "access_token", "refresh_token", "client_secret"})
_SECRET_VALUE_PATTERNS = (re.compile(r"-----BEGIN [A-Z ]+-----"), re.compile(r"\bBearer\s+\S+", re.I), re.compile(r"(?:^|\s)(?:sk|ghp|xoxb|AIza)[-_][A-Za-z0-9_-]{12,}"), re.compile(r"eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{10,}"))


def _tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    if isinstance(value, Sequence):
        return tuple(str(item) for item in value)
    return (str(value),)


def _clean(value: Any) -> Any:
    if hasattr(value, "__dataclass_fields__"):
        return {key: _clean(item) for key, item in asdict(value).items()}
    if isinstance(value, Mapping):
        return {str(key): _clean(item) for key, item in value.items()}
    if isinstance(value, (tuple, list, set)):
        return [_clean(item) for item in value]
    return value


def _secret_like(value: Any) -> bool:
    if isinstance(value, Mapping):
        return any(str(key).lower().replace("-", "_") in SECRET_KEYS or _secret_like(item) for key, item in value.items())
    if isinstance(value, (tuple, list, set)):
        return any(_secret_like(item) for item in value)
    if isinstance(value, str):
        return any(pattern.search(value) for pattern in _SECRET_VALUE_PATTERNS)
    return False


@dataclass(frozen=True)
class SecretManagerReference:
    manager_id: str
    name: str
    provider_id: str
    secret_ref: str
    environment: str
    access_policy: str
    rotation_supported: bool
    reference_only: bool = True


@dataclass(frozen=True)
class ProviderPermissionScope:
    scope_id: str
    description: str
    action_mode: str
    approval_required: bool
    least_privilege_note: str


@dataclass(frozen=True)
class ProviderRiskPolicy:
    provider_id: str
    risk_level: str
    security_risk: str
    terms_risk: str
    privacy_review_required: bool
    approval_types: tuple[str, ...]
    default_action_mode: str

    def __post_init__(self) -> None:
        if self.risk_level not in RISK_LEVELS:
            raise ValueError(f"invalid provider risk level: {self.risk_level}")


@dataclass(frozen=True)
class ProviderCostPolicy:
    provider_id: str
    currency: str
    per_run_cap: float
    monthly_cap: float
    cost_driver: str
    overage_action: str
    assumption_note: str


@dataclass(frozen=True)
class ProviderRateLimitPolicy:
    provider_id: str
    requests_per_minute: int
    requests_per_day: int
    burst_allowed: bool
    backoff_policy: str
    source: str


@dataclass(frozen=True)
class ProviderBudgetPolicy:
    provider_id: str
    monthly_cap: float
    per_run_cap: float
    currency: str
    approval_required_to_exceed: bool
    pause_action: str


@dataclass(frozen=True)
class ProviderHealthCheckStatus:
    provider_id: str
    status: str
    last_checked: str
    check_mode: str
    credential_presence: str
    observed_capabilities: tuple[str, ...]
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class CredentialRotationPolicy:
    policy_id: str
    cadence_days: int
    rotate_on_owner_change: bool
    rotate_on_incident: bool
    revoke_old_reference: bool
    runbook_ref: str


@dataclass(frozen=True)
class CredentialEnvironmentPolicy:
    environment: str
    allowed_secret_managers: tuple[str, ...]
    forbidden_storage: tuple[str, ...]
    required_approval: str
    notes: str


@dataclass(frozen=True)
class CredentialApprovalLink:
    credential_id: str
    approval_types: tuple[str, ...]
    policy_ids: tuple[str, ...]
    activation_gate: str
    status: str


@dataclass(frozen=True)
class CredentialToolLink:
    credential_id: str
    tool_categories: tuple[str, ...]
    tool_ids: tuple[str, ...]
    permission_scopes: tuple[str, ...]
    approval_required: bool


@dataclass(frozen=True)
class CredentialModelRouteLink:
    credential_id: str
    route_ids: tuple[str, ...]
    allowed_tiers: tuple[str, ...]
    budget_policy_id: str
    approval_required: bool


@dataclass(frozen=True)
class CredentialKnowledgeLink:
    credential_id: str
    source_ids: tuple[str, ...]
    access_level: str
    citation_required: bool
    privacy_review_required: bool


@dataclass(frozen=True)
class ProviderCapability:
    capability_id: str
    provider_id: str
    name: str
    description: str
    action_mode: str
    tool_categories: tuple[str, ...]
    approval_types: tuple[str, ...]
    evidence_model: str


@dataclass(frozen=True)
class ProviderCapabilityMatrix:
    provider_id: str
    capability_ids: tuple[str, ...]
    covered_data_needs: tuple[str, ...]
    evidence_models: tuple[str, ...]
    gaps: tuple[str, ...]
    confidence: str


@dataclass(frozen=True)
class ProviderAccount:
    provider_id: str
    account_id: str
    account_label: str
    environment: str
    owner_department: str
    credential_ids: tuple[str, ...]
    status: str
    region: str
    notes: str


@dataclass(frozen=True)
class CredentialReference:
    credential_id: str
    provider_id: str
    account_id: str
    environment: str
    secret_manager: str
    secret_manager_ref: str
    credential_type: str
    permission_scopes: tuple[ProviderPermissionScope, ...]
    owner_department: str
    allowed_tools: tuple[str, ...]
    allowed_workflows: tuple[str, ...]
    allowed_agents: tuple[str, ...]
    linked_approval_policy: str
    risk_level: str
    monthly_budget_cap: float
    per_run_budget_cap: float
    rate_limit: ProviderRateLimitPolicy
    rotation_policy: CredentialRotationPolicy
    health_status: ProviderHealthCheckStatus
    last_health_check: str
    expires_at: str
    status: str
    notes: str

    def __post_init__(self) -> None:
        if self.credential_type not in CREDENTIAL_TYPES:
            raise ValueError(f"invalid credential type: {self.credential_type}")
        if self.secret_manager not in SECRET_MANAGERS:
            raise ValueError(f"invalid secret manager: {self.secret_manager}")
        if self.status not in CREDENTIAL_STATUSES:
            raise ValueError(f"invalid credential status: {self.status}")
        if self.risk_level not in RISK_LEVELS:
            raise ValueError(f"invalid credential risk: {self.risk_level}")
        if self.monthly_budget_cap < 0 or self.per_run_budget_cap < 0:
            raise ValueError("credential budget caps cannot be negative")
        if _secret_like({"notes": self.notes, "secret_manager_ref": self.secret_manager_ref}):
            raise ValueError("secret-like values are not allowed in credential metadata")

    def to_dict(self) -> dict[str, Any]:
        return _clean(self)


@dataclass(frozen=True)
class CredentialRegistryReport:
    report_version: str
    generated_at: str
    credentials: tuple[CredentialReference, ...]
    secret_managers: tuple[SecretManagerReference, ...]
    accounts: tuple[ProviderAccount, ...]
    capabilities: tuple[ProviderCapability, ...]
    permission_scopes: tuple[ProviderPermissionScope, ...]
    risk_policies: tuple[ProviderRiskPolicy, ...]
    cost_policies: tuple[ProviderCostPolicy, ...]
    rate_limits: tuple[ProviderRateLimitPolicy, ...]
    budget_policies: tuple[ProviderBudgetPolicy, ...]
    health_checks: tuple[ProviderHealthCheckStatus, ...]
    rotation_policies: tuple[CredentialRotationPolicy, ...]
    environment_policies: tuple[CredentialEnvironmentPolicy, ...]
    approval_links: tuple[CredentialApprovalLink, ...]
    tool_links: tuple[CredentialToolLink, ...]
    model_route_links: tuple[CredentialModelRouteLink, ...]
    knowledge_links: tuple[CredentialKnowledgeLink, ...]
    safety_summary: dict[str, Any]
    credential_gaps: tuple[str, ...]
    next_best_action: str

    def to_dict(self) -> dict[str, Any]:
        return _clean(self)

    def to_markdown(self) -> str:
        lines = ["# CompanyOS Credential Registry", "", "## Summary", "", f"- Credential references: **{len(self.credentials)}**", f"- Secret-manager references: **{len(self.secret_managers)}**", f"- Provider accounts: **{len(self.accounts)}**", "- Mode: **metadata-only, offline, reference-only**", "", "## Credential References", "", "| Credential | Provider | Type | Status | Health | Budget |", "|---|---|---|---|---|---|"]
        lines.extend(f"| {item.credential_id} | {item.provider_id} | {item.credential_type} | {item.status} | {item.health_status.status} | ${item.monthly_budget_cap:.2f}/mo |" for item in self.credentials)
        lines += ["", "## Credential Gaps", ""]
        lines.extend(f"- {gap}" for gap in self.credential_gaps)
        lines += ["", "## Safety", "", "- Secret values, raw tokens, passwords, and private-key material are not accepted.", "- Health checks are metadata-only and do not validate live credentials.", "- No provider, model, CRM, accounting, messaging, payment, advertising, or publishing call occurred.", "", "## Next Best Action", "", self.next_best_action, ""]
        return "\n".join(lines)


def _scope(scope_id: str, description: str, action_mode: str = "reference_only", approval: bool = True) -> ProviderPermissionScope:
    return ProviderPermissionScope(scope_id, description, action_mode, approval, "Use the smallest read-only scope and keep writes unavailable.")


def _credential(provider_id: str, *, credential_type: str = "api_key", status: str = "needed", manager: str = "manual_reference", owner: str = "intelligence", risk: str = "medium", scopes: tuple[ProviderPermissionScope, ...] = ()) -> CredentialReference:
    scopes = scopes or (_scope(f"{provider_id}:read_only", f"Reference-only {provider_id} metadata"),)
    health = ProviderHealthCheckStatus(provider_id, "not_checked", "never", "metadata_only", "unknown", (), ("Live credential validation is disabled.",))
    rotation = CredentialRotationPolicy(f"rotation-{provider_id}", 90, True, True, True, "docs/COMPANYOS_PROVIDER_CREDENTIAL_REGISTRY.md")
    limit = ProviderRateLimitPolicy(provider_id, 30, 1000, False, "bounded exponential backoff in a future adapter", "offline assumption")
    return CredentialReference(f"credential-{provider_id}", provider_id, f"account-{provider_id}-placeholder", "local", manager, f"marketos/{provider_id}/reference", credential_type, scopes, owner, (), (), (), f"approval-policy-provider-{provider_id}", risk, 0.0, 0.0, limit, rotation, health, "never", "not_configured", status, "Reference metadata only; no account identifier or secret value.")


def build_credential_registry(*, generated_at: str = "offline-deterministic", seed: Mapping[str, Any] | None = None) -> CredentialRegistryReport:
    if seed is not None and _secret_like(seed):
        raise ValueError("secret-like credential input is not accepted")
    providers = ("cj", "apify", "dataforseo", "serpapi", "litellm", "langfuse", "composio", "shopify", "quickbooks", "xero", "twilio", "supabase")
    credentials = [_credential(provider, credential_type="manual_export" if provider in {"cj", "shopify"} else "model_gateway_key" if provider == "litellm" else "api_key", status="needed", owner="supplier" if provider == "cj" else "intelligence" if provider in {"apify", "dataforseo", "serpapi"} else "operations") for provider in providers]
    overrides = {str(item.get("credential_id")): item for item in (seed or {}).get("credentials", []) if isinstance(item, Mapping)}
    credentials = [replace(item, status=str(overrides.get(item.credential_id, {}).get("status", item.status))) if str(overrides.get(item.credential_id, {}).get("status", item.status)) in CREDENTIAL_STATUSES else item for item in credentials]
    managers = tuple(SecretManagerReference(manager, manager.replace("_", " ").title(), manager, f"marketos/{manager}/reference", "local", "operator-owned reference only", manager not in {"none", "manual_reference"}) for manager in SECRET_MANAGERS)
    accounts = tuple(ProviderAccount(item.provider_id, item.account_id, f"{item.provider_id.title()} placeholder", item.environment, item.owner_department, (item.credential_id,), "reference_only", "unknown", item.notes) for item in credentials)
    scopes = tuple(sorted({scope for item in credentials for scope in item.permission_scopes}, key=lambda item: item.scope_id))
    capabilities = tuple(ProviderCapability(f"cap-{item.provider_id}-read", item.provider_id, "read-only metadata reference", "Future bounded read-only capability; no call is made.", "reference_only", ("read_file", "run_script"), ("provider_call", "web_data_acquisition"), "sanitized_report") for item in credentials)
    risk = tuple(ProviderRiskPolicy(item.provider_id, item.risk_level, "secret-manager and scope review required", "provider terms review required", True, ("provider_call", "web_data_acquisition"), "reference_only") for item in credentials)
    costs = tuple(ProviderCostPolicy(item.provider_id, "USD", 0.0, 0.0, "future provider usage", "pause and review", "No live pricing is queried; values are planning placeholders.") for item in credentials)
    limits = tuple(item.rate_limit for item in credentials)
    budgets = tuple(ProviderBudgetPolicy(item.provider_id, 0.0, 0.0, "USD", True, "block until approved") for item in credentials)
    health = tuple(item.health_status for item in credentials)
    rotations = tuple(item.rotation_policy for item in credentials)
    environments = tuple(CredentialEnvironmentPolicy(environment, SECRET_MANAGERS, ("git", ".env", "logs", "artifacts", "raw payloads"), "approval_required_before_configuration", "Use platform secret references only.") for environment in ("local", "ci", "staging", "production"))
    approvals = tuple(CredentialApprovalLink(item.credential_id, ("provider_call", "web_data_acquisition", "model_spend"), (item.linked_approval_policy,), "approval_required_to_activate_provider", "blocked_in_current_mode") for item in credentials)
    tools = tuple(CredentialToolLink(item.credential_id, ("search_web", "run_script"), (), tuple(scope.scope_id for scope in item.permission_scopes), True) for item in credentials)
    routes = tuple(CredentialModelRouteLink(item.credential_id, ("local_low_cost", "cheap_api") if item.provider_id == "litellm" else (), ("local_low_cost", "cheap_api") if item.provider_id == "litellm" else (), "approval-policy-model-spend", True) for item in credentials)
    knowledge = tuple(CredentialKnowledgeLink(item.credential_id, (), "restricted", True, True) for item in credentials)
    gaps = tuple(f"{item.provider_id}: metadata reference exists but no secret-manager value or live health check is configured" for item in credentials)
    return CredentialRegistryReport("companyos-credential-registry-v1", generated_at, tuple(credentials), managers, accounts, capabilities, scopes, risk, costs, limits, budgets, health, rotations, environments, approvals, tools, routes, knowledge, {"read_only": True, "network_calls": False, "mutated": False, "secret_values_stored": False, "live_health_checks": False, "credentials_present": False, "fail_closed": True}, gaps, "Choose one provider owner and configure a secret-manager reference only after an Approval Ledger review; do not validate live credentials in this mode.")


__all__ = ["CREDENTIAL_TYPES", "SECRET_MANAGERS", "CREDENTIAL_STATUSES", "CredentialRegistryReport", "CredentialReference", "SecretManagerReference", "ProviderAccount", "ProviderCapability", "ProviderCapabilityMatrix", "ProviderPermissionScope", "ProviderRiskPolicy", "ProviderCostPolicy", "ProviderRateLimitPolicy", "ProviderBudgetPolicy", "ProviderHealthCheckStatus", "CredentialRotationPolicy", "CredentialEnvironmentPolicy", "CredentialApprovalLink", "CredentialToolLink", "CredentialModelRouteLink", "CredentialKnowledgeLink", "build_credential_registry"]
