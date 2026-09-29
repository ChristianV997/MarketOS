"""Deterministic, offline approval control for CompanyOS.

The approval ledger is deliberately a policy and simulation layer.  It records
what would need approval, why a request is blocked, and which evidence would be
required.  It never grants authority to an external system and never executes
the action represented by a request.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from typing import Any, Iterable, Mapping, Sequence

REQUEST_TYPES = (
    "model_spend", "provider_call", "web_data_acquisition", "vector_indexing",
    "crm_mutation", "email_send", "whatsapp_send", "sms_send", "voice_call",
    "accounting_sync", "invoice_creation", "payment_creation", "supplier_order",
    "ad_launch", "site_publish", "domain_change", "hosting_change",
    "customer_message", "workflow_resume",
)
STATUS_VALUES = ("draft", "pending_review", "approved", "denied", "expired", "revoked", "simulated", "blocked_by_policy")
RISK_LEVELS = ("low", "medium", "high", "critical", "blocked")
DECISION_CLASSES = ("approval_required", "approval_possible_later", "blocked_in_current_mode", "approved_simulation_only")
SIMULATION_STATUSES = (
    "would_auto_allow_draft", "would_require_human_approval", "would_be_blocked_by_policy",
    "would_be_denied_missing_conditions", "would_expire_before_execution",
)
OUTREACH_TYPES = frozenset({"email_send", "whatsapp_send", "sms_send", "voice_call", "customer_message"})
LIVE_ACTION_TYPES = frozenset({
    "crm_mutation", "email_send", "whatsapp_send", "sms_send", "voice_call", "accounting_sync",
    "invoice_creation", "payment_creation", "supplier_order", "ad_launch", "site_publish",
    "domain_change", "hosting_change", "customer_message",
})


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
    if hasattr(value, "to_dict"):
        return value.to_dict()
    if isinstance(value, Mapping):
        return {str(key): _clean(item) for key, item in value.items()}
    if isinstance(value, (tuple, list, set)):
        return [_clean(item) for item in value]
    return value


@dataclass(frozen=True)
class ApprovalScope:
    resources: tuple[str, ...] = ()
    actions: tuple[str, ...] = ()
    environments: tuple[str, ...] = ("offline",)
    constraints: tuple[str, ...] = ()
    expiry_required: bool = True


@dataclass(frozen=True)
class ApprovalCondition:
    condition_id: str
    description: str
    required: bool = True
    satisfied: bool = False
    evidence_ref: str = ""


@dataclass(frozen=True)
class ApprovalRequirement:
    requirement_id: str
    requirement_type: str
    description: str
    blocking: bool = True
    satisfied: bool = False
    evidence_ref: str = ""


@dataclass(frozen=True)
class ApprovalBudgetCap:
    scope: str
    per_run: float
    monthly: float
    currency: str = "USD"
    consumed: float = 0.0
    remaining: float | None = None

    def __post_init__(self) -> None:
        if self.per_run < 0 or self.monthly < 0 or self.consumed < 0:
            raise ValueError("budget values cannot be negative")
        if self.remaining is None:
            object.__setattr__(self, "remaining", max(0.0, self.monthly - self.consumed))


@dataclass(frozen=True)
class ApprovalEvidence:
    ref_id: str
    evidence_type: str
    source: str
    summary: str
    sanitized: bool = True


@dataclass(frozen=True)
class ApprovalRiskAssessment:
    risk_level: str
    factors: tuple[str, ...]
    blocking_reasons: tuple[str, ...]
    score: int

    def __post_init__(self) -> None:
        if self.risk_level not in RISK_LEVELS:
            raise ValueError(f"invalid risk level: {self.risk_level}")
        if not 0 <= self.score <= 100:
            raise ValueError("risk score must be between 0 and 100")


@dataclass(frozen=True)
class ApprovalToolLink:
    tool_id: str
    risk_level: str
    side_effect_type: str
    approval_required: bool
    policy_note: str


@dataclass(frozen=True)
class ApprovalWorkflowLink:
    workflow_id: str
    interrupt_points: tuple[str, ...]
    resume_condition: str
    approval_required: bool


@dataclass(frozen=True)
class ApprovalExpiry:
    created_at: str
    expires_at: str
    expired: bool = False
    reason: str = ""


@dataclass(frozen=True)
class ApprovalRevocation:
    revocation_id: str
    approval_id: str
    revoked_by: str
    revoked_at: str
    reason: str
    effective_immediately: bool = True


@dataclass(frozen=True)
class ApprovalDecision:
    decision_id: str
    approval_id: str
    decision: str
    approver_role: str
    approver_id: str
    rationale: str
    conditions: tuple[str, ...]
    decided_at: str
    simulation_only: bool = True


@dataclass(frozen=True)
class ApprovalRequest:
    approval_id: str
    request_title: str
    request_type: str
    requested_by_agent: str
    owner_department: str
    linked_tool_id: str
    linked_workflow_id: str
    linked_skill_id: str
    linked_model_route_id: str
    target_resource: str
    external_system: str
    action_category: str
    side_effect_type: str
    risk_level: str
    requested_mode: str
    requested_scope: ApprovalScope
    requested_budget_cap: ApprovalBudgetCap
    requested_time_window: ApprovalExpiry
    required_approver_role: str
    evidence: tuple[ApprovalEvidence, ...]
    conditions: tuple[ApprovalCondition, ...]
    created_at: str
    expires_at: str
    status: str = "draft"
    read_only: bool = True
    network_calls: bool = False
    mutated: bool = False
    external_action_performed: bool = False

    def __post_init__(self) -> None:
        if self.request_type not in REQUEST_TYPES:
            raise ValueError(f"invalid request type: {self.request_type}")
        if self.status not in STATUS_VALUES:
            raise ValueError(f"invalid approval status: {self.status}")
        if self.risk_level not in RISK_LEVELS:
            raise ValueError(f"invalid approval risk: {self.risk_level}")
        if not self.read_only or self.network_calls or self.mutated or self.external_action_performed:
            raise ValueError("Approval Ledger v1 is offline and read-only")

    def to_dict(self) -> dict[str, Any]:
        return _clean(self)


@dataclass(frozen=True)
class ApprovalPolicy:
    policy_id: str
    request_type: str
    decision_class: str
    default_risk: str
    required_approver_role: str
    required_conditions: tuple[str, ...]
    budget_cap: ApprovalBudgetCap
    rationale: str
    blocked_in_current_mode: bool

    def __post_init__(self) -> None:
        if self.request_type not in REQUEST_TYPES:
            raise ValueError(f"invalid policy request type: {self.request_type}")
        if self.decision_class not in DECISION_CLASSES:
            raise ValueError(f"invalid decision class: {self.decision_class}")
        if self.default_risk not in RISK_LEVELS:
            raise ValueError(f"invalid policy risk: {self.default_risk}")


@dataclass(frozen=True)
class ApprovalAuditEvent:
    event_id: str
    approval_id: str
    event_type: str
    actor: str
    timestamp: str
    before_status: str
    after_status: str
    reason: str
    evidence_refs: tuple[str, ...]
    immutable_note: str = "Offline audit record; no external action occurred."


@dataclass(frozen=True)
class ApprovalSimulation:
    simulation_id: str
    action: str
    request_type: str
    result: str
    can_be_approved_now: bool
    missing_conditions: tuple[str, ...]
    blocking_reasons: tuple[str, ...]
    budget_cap: ApprovalBudgetCap
    audit_event_type: str
    request: ApprovalRequest

    def to_dict(self) -> dict[str, Any]:
        return _clean(self)


@dataclass(frozen=True)
class ApprovalQueueSummary:
    pending: int
    approved: int
    denied: int
    expired: int
    revoked: int
    blocked: int
    draft_or_simulated: int
    high_risk: int
    missing_conditions: int


@dataclass(frozen=True)
class ApprovalLedgerSafetySummary:
    read_only: bool
    network_calls: bool
    mutated: bool
    external_action_performed: bool
    credentials_present: bool
    live_capabilities_enabled: bool
    policy_fail_closed: bool
    audit_trail_present: bool
    secrets_stored: bool
    summary: str


@dataclass(frozen=True)
class ApprovalLedgerReport:
    report_version: str
    generated_at: str
    approval_count: int
    pending_count: int
    approved_count: int
    denied_count: int
    expired_count: int
    revoked_count: int
    blocked_count: int
    critical_count: int
    highest_risk_requests: tuple[ApprovalRequest, ...]
    requests: tuple[ApprovalRequest, ...]
    decisions: tuple[ApprovalDecision, ...]
    audit_events: tuple[ApprovalAuditEvent, ...]
    revocations: tuple[ApprovalRevocation, ...]
    expiries: tuple[ApprovalExpiry, ...]
    policies: tuple[ApprovalPolicy, ...]
    simulations: tuple[ApprovalSimulation, ...]
    queue_summary: ApprovalQueueSummary
    safety_summary: ApprovalLedgerSafetySummary
    registry_integration: dict[str, Any]
    next_best_action: str

    def to_dict(self) -> dict[str, Any]:
        return _clean(self)

    def to_markdown(self) -> str:
        lines = [
            "# CompanyOS Approval Ledger", "", "## Executive Summary", "",
            f"- Requests: **{self.approval_count}**", f"- Pending review: **{self.pending_count}**",
            f"- Blocked by policy: **{self.blocked_count}**", f"- Critical risk: **{self.critical_count}**",
            "- Mode: **offline, deterministic, read-only**", "",
            "## Pending Approvals", "", "| ID | Request | Risk | Status | Approver |", "|---|---|---|---|---|",
        ]
        for item in self.requests:
            if item.status in {"pending_review", "draft"}:
                lines.append(f"| {item.approval_id} | {item.request_title} | {item.risk_level} | {item.status} | {item.required_approver_role} |")
        lines += ["", "## Blocked Actions", ""]
        for item in self.requests:
            if item.status == "blocked_by_policy":
                lines.append(f"- **{item.request_type}** - {item.request_title} ({item.risk_level})")
        lines += ["", "## Approval Policies", "", "| Request type | Class | Risk | Current mode |", "|---|---|---|---|"]
        lines.extend(f"| {p.request_type} | {p.decision_class} | {p.default_risk} | {'blocked' if p.blocked_in_current_mode else 'draft-safe'} |" for p in self.policies)
        lines += ["", "## High-Risk Requests", ""]
        for item in self.highest_risk_requests:
            lines.append(f"- {item.approval_id}: {item.request_title} - **{item.risk_level}**")
        lines += ["", "## Simulations", ""]
        if self.simulations:
            for simulation in self.simulations:
                lines.append(f"- `{simulation.action}` -> **{simulation.result}**; missing: {', '.join(simulation.missing_conditions) or 'none'}")
        else:
            lines.append("- No action simulation requested.")
        lines += ["", "## Budget Caps", ""]
        for policy in self.policies:
            if policy.budget_cap.per_run or policy.budget_cap.monthly:
                lines.append(f"- {policy.request_type}: ${policy.budget_cap.per_run:.2f}/run, ${policy.budget_cap.monthly:.2f}/month")
        lines += ["", "## Missing Conditions", ""]
        missing = [(request.approval_id, condition.description) for request in self.requests for condition in request.conditions if condition.required and not condition.satisfied]
        lines.extend(f"- {approval_id}: {description}" for approval_id, description in missing) or lines.append("- None in the current report.")
        lines += ["", "## Audit Trail", ""]
        lines.extend(f"- `{event.timestamp}` `{event.event_type}` {event.approval_id}: {event.before_status} -> {event.after_status} ({event.reason})" for event in self.audit_events)
        lines += ["", "## Safety Boundaries", "", "- No credentials, secrets, private recipients, or provider payloads are stored.", "- No provider, model, vector, CRM, accounting, messaging, payment, ad, order, or publishing action occurred.", "- An approval record does not authorize execution; every live capability remains blocked in this mode.", "", "## Next Best Action", "", self.next_best_action, ""]
        return "\n".join(lines)


def _cap(scope: str, per_run: float, monthly: float) -> ApprovalBudgetCap:
    return ApprovalBudgetCap(scope, per_run, monthly)


def default_approval_policies() -> tuple[ApprovalPolicy, ...]:
    """Return the single source of truth for current-mode approval behavior."""
    rows = [
        ("model_spend", "approval_possible_later", "medium", "human_operator", ("model route is registered", "run is within budget cap"), _cap("model route", 5.0, 100.0), "Local and cheap routes can be simulated; no model call is made.", False),
        ("provider_call", "blocked_in_current_mode", "high", "human_operator", ("provider and purpose reviewed", "network gate explicitly enabled", "robots/TOS review complete"), _cap("provider call", 0.0, 0.0), "Provider calls remain disabled in this offline ledger.", True),
        ("web_data_acquisition", "approval_possible_later", "medium", "human_operator", ("source is public or manual", "robots/TOS review complete"), _cap("web acquisition", 0.0, 0.0), "Manual imports are safe drafts; network acquisition needs later approval.", False),
        ("vector_indexing", "blocked_in_current_mode", "high", "knowledge_owner", ("privacy classification approved", "retention policy approved", "citation policy configured"), _cap("vector indexing", 0.0, 0.0), "Vector indexing is blocked in current mode; no database calls are available.", True),
        ("crm_mutation", "blocked_in_current_mode", "high", "sales_manager", ("consent verified", "record scope approved", "audit event configured"), _cap("CRM mutation", 0.0, 0.0), "CRM writes are not installed.", True),
        ("email_send", "blocked_in_current_mode", "high", "human_operator", ("recipient consent verified", "do-not-contact is false", "message approved", "unsubscribe language present"), _cap("outreach", 0.0, 0.0), "Email is draft-only and cannot be sent.", True),
        ("whatsapp_send", "blocked_in_current_mode", "high", "human_operator", ("recipient consent verified", "do-not-contact is false", "message approved"), _cap("outreach", 0.0, 0.0), "WhatsApp is draft-only and cannot be sent.", True),
        ("sms_send", "blocked_in_current_mode", "high", "human_operator", ("recipient consent verified", "do-not-contact is false", "message approved", "unsubscribe language present"), _cap("outreach", 0.0, 0.0), "SMS is draft-only and cannot be sent.", True),
        ("voice_call", "blocked_in_current_mode", "critical", "human_operator", ("recipient consent verified", "do-not-contact is false", "call script approved"), _cap("outreach", 0.0, 0.0), "Voice calls are not available.", True),
        ("accounting_sync", "blocked_in_current_mode", "high", "finance_manager", ("period is open", "ledger reviewed", "sync scope approved"), _cap("accounting sync", 0.0, 0.0), "Accounting platform mutation is not installed.", True),
        ("invoice_creation", "approval_required", "high", "finance_manager", ("client and amount verified", "invoice reviewed", "payment terms approved"), _cap("invoice", 0.0, 0.0), "Invoice issuance is blocked in current mode; only a draft may be prepared.", True),
        ("payment_creation", "blocked_in_current_mode", "critical", "finance_manager", ("payee verified", "payment purpose approved", "dual review complete"), _cap("payment", 0.0, 0.0), "Payment creation is permanently blocked in this version.", True),
        ("supplier_order", "blocked_in_current_mode", "critical", "operations_manager", ("supplier proof confirmed", "margin approved", "order scope and budget approved"), _cap("supplier order", 0.0, 0.0), "Supplier order creation is not available.", True),
        ("ad_launch", "blocked_in_current_mode", "critical", "marketing_manager", ("creative approved", "budget cap approved", "claims review passed", "tracking plan approved"), _cap("ad launch", 0.0, 0.0), "Ad launch is not available.", True),
        ("site_publish", "blocked_in_current_mode", "high", "site_owner", ("copy approved", "claims approved", "policies approved", "deployment reviewed"), _cap("site publish", 0.0, 0.0), "Site publishing is blocked in current mode; payloads remain draft-only.", True),
        ("domain_change", "blocked_in_current_mode", "critical", "site_owner", ("domain owner verified", "rollback plan approved", "DNS change reviewed"), _cap("domain", 0.0, 0.0), "Domain changes are not available.", True),
        ("hosting_change", "blocked_in_current_mode", "critical", "site_owner", ("hosting owner verified", "rollback plan approved", "deployment reviewed"), _cap("hosting", 0.0, 0.0), "Hosting changes are not available.", True),
        ("customer_message", "blocked_in_current_mode", "high", "human_operator", ("consent verified", "do-not-contact is false", "message approved", "AI disclosure reviewed"), _cap("customer message", 0.0, 0.0), "Customer messaging is blocked in current mode and remains draft-only.", True),
        ("workflow_resume", "approval_required", "medium", "workflow_owner", ("checkpoint is valid", "approval conditions remain true"), _cap("workflow resume", 0.0, 0.0), "Workflow resume is blocked in current mode until an approved checkpoint exists.", True),
    ]
    return tuple(ApprovalPolicy(f"approval-policy-{request_type}", request_type, decision, risk, role, tuple(conditions), cap, rationale, blocked) for request_type, decision, risk, role, conditions, cap, rationale, blocked in rows)


def _policy_map(policies: Iterable[ApprovalPolicy] | None = None) -> dict[str, ApprovalPolicy]:
    return {policy.request_type: policy for policy in (policies or default_approval_policies())}


def _action_type(action: str) -> str:
    aliases = {
        "send_email": "email_send", "send_whatsapp": "whatsapp_send", "send_sms": "sms_send",
        "place_call": "voice_call", "create_payment": "payment_creation", "launch_ad": "ad_launch",
        "publish_site": "site_publish", "provider_call": "provider_call", "manual_import": "web_data_acquisition",
        "create_order": "supplier_order", "index_vectors": "vector_indexing", "sync_accounting": "accounting_sync",
    }
    return aliases.get(action, action)


def _conditions(policy: ApprovalPolicy, *, consent: bool = False, do_not_contact: bool = False, unsubscribe: bool = False, message_approved: bool = False, route_registered: bool = True, budget_ok: bool = True) -> tuple[ApprovalCondition, ...]:
    results: list[ApprovalCondition] = []
    for index, description in enumerate(policy.required_conditions, 1):
        lower = description.lower()
        satisfied = (
            ("consent" not in lower or consent)
            and ("do-not-contact" not in lower or not do_not_contact)
            and ("unsubscribe" not in lower or unsubscribe)
            and ("message approved" not in lower or message_approved)
            and ("route is registered" not in lower or route_registered)
            and ("within budget" not in lower or budget_ok)
        )
        results.append(ApprovalCondition(f"condition-{index}", description, True, satisfied, "operator_input" if satisfied else "missing_operator_input"))
    return tuple(results)


def make_request(*, approval_id: str, request_type: str, title: str | None = None, requested_by_agent: str = "approval-gatekeeper", owner_department: str = "risk_approval", linked_tool_id: str = "", linked_workflow_id: str = "", linked_skill_id: str = "", linked_model_route_id: str = "", target_resource: str = "offline-draft", external_system: str = "none", action_category: str | None = None, side_effect_type: str = "none", requested_mode: str = "simulation", requested_budget: float = 0.0, created_at: str = "offline-deterministic", expires_at: str = "offline-deterministic-expiry", status: str | None = None, consent: bool = False, do_not_contact: bool = False, unsubscribe: bool = False, message_approved: bool = False, route_registered: bool = True, budget_ok: bool = True, evidence: Sequence[ApprovalEvidence] = ()) -> ApprovalRequest:
    policy = _policy_map()[request_type]
    conditions = _conditions(policy, consent=consent, do_not_contact=do_not_contact, unsubscribe=unsubscribe, message_approved=message_approved, route_registered=route_registered, budget_ok=budget_ok)
    if status is None:
        if policy.blocked_in_current_mode:
            status = "blocked_by_policy"
        elif policy.decision_class == "draft_only":
            status = "draft"
        else:
            status = "pending_review"
    return ApprovalRequest(approval_id, title or request_type.replace("_", " ").title(), request_type, requested_by_agent, owner_department, linked_tool_id, linked_workflow_id, linked_skill_id, linked_model_route_id, target_resource, external_system, action_category or request_type, side_effect_type, policy.default_risk, requested_mode, ApprovalScope((target_resource,), (request_type,), ("offline",), ("no external execution",), True), ApprovalBudgetCap(policy.budget_cap.scope, min(requested_budget, policy.budget_cap.per_run) if policy.budget_cap.per_run else requested_budget, policy.budget_cap.monthly, policy.budget_cap.currency, 0.0), ApprovalExpiry(created_at, expires_at, False), policy.required_approver_role, tuple(evidence), conditions, created_at, expires_at, status)


def simulate_action(action: str, *, requested_budget: float = 0.0, consent: bool = False, do_not_contact: bool = False, unsubscribe: bool = False, message_approved: bool = False, route_registered: bool = True, budget_ok: bool | None = None, generated_at: str = "offline-deterministic") -> ApprovalSimulation:
    request_type = _action_type(action)
    if request_type not in REQUEST_TYPES:
        request_type = "workflow_resume"
        action = "unknown_action"
    policy = _policy_map()[request_type]
    if budget_ok is None:
        budget_ok = requested_budget <= policy.budget_cap.monthly and (policy.budget_cap.per_run == 0 or requested_budget <= policy.budget_cap.per_run)
    request = make_request(approval_id=f"simulation-{action}", request_type=request_type, title=f"Simulate {action}", requested_budget=requested_budget, created_at=generated_at, expires_at=f"{generated_at}-expiry", status="simulated", consent=consent, do_not_contact=do_not_contact, unsubscribe=unsubscribe, message_approved=message_approved, route_registered=route_registered, budget_ok=budget_ok)
    missing = tuple(condition.description for condition in request.conditions if condition.required and not condition.satisfied)
    blocks: list[str] = []
    if not budget_ok:
        blocks.append("requested budget exceeds the applicable cap")
    if policy.blocked_in_current_mode:
        blocks.append(policy.rationale)
    if missing:
        result = "would_be_denied_missing_conditions"
    elif policy.blocked_in_current_mode:
        result = "would_be_blocked_by_policy"
    elif request_type == "model_spend" and budget_ok:
        result = "would_auto_allow_draft"
    elif action == "manual_import" or policy.decision_class == "draft_only":
        result = "would_auto_allow_draft"
    else:
        result = "would_require_human_approval"
    return ApprovalSimulation(f"simulation-{action}", action, request_type, result, result == "would_auto_allow_draft", missing, tuple(blocks), policy.budget_cap, f"companyos_approval_simulation_{request_type}", request)


def _request_from_mapping(item: Mapping[str, Any], index: int) -> ApprovalRequest:
    request_type = _action_type(str(item.get("request_type", "workflow_resume")))
    if request_type not in REQUEST_TYPES:
        raise ValueError(f"unsupported approval request type: {request_type}")
    policy = _policy_map()[request_type]
    conditions = tuple(ApprovalCondition(str(c.get("condition_id", f"condition-{i}")), str(c.get("description", "operator condition")), bool(c.get("required", True)), bool(c.get("satisfied", False)), str(c.get("evidence_ref", ""))) for i, c in enumerate(item.get("conditions", []), 1) if isinstance(c, Mapping))
    if not conditions:
        conditions = _conditions(policy)
    evidence = tuple(ApprovalEvidence(str(e.get("ref_id", f"evidence-{i}")), str(e.get("evidence_type", "manual")), str(e.get("source", "sanitized_input")), str(e.get("summary", "Sanitized operator evidence")), True) for i, e in enumerate(item.get("evidence", []), 1) if isinstance(e, Mapping))
    return ApprovalRequest(
        str(item.get("approval_id", f"approval-{index}")), str(item.get("request_title", request_type.replace("_", " ").title())), request_type,
        str(item.get("requested_by_agent", "operator")), str(item.get("owner_department", "risk_approval")), str(item.get("linked_tool_id", "")), str(item.get("linked_workflow_id", "")), str(item.get("linked_skill_id", "")), str(item.get("linked_model_route_id", "")), str(item.get("target_resource", "offline-draft")), str(item.get("external_system", "none")), str(item.get("action_category", request_type)), str(item.get("side_effect_type", "none")), str(item.get("risk_level", policy.default_risk)), str(item.get("requested_mode", "simulation")), ApprovalScope(_tuple(item.get("resources", (item.get("target_resource", "offline-draft"),))), _tuple(item.get("actions", (request_type,))), _tuple(item.get("environments", ("offline",))), _tuple(item.get("constraints", ("no external execution",))), True), ApprovalBudgetCap(policy.budget_cap.scope, float(item.get("requested_budget", 0.0)), policy.budget_cap.monthly, "USD", 0.0), ApprovalExpiry(str(item.get("created_at", "offline-deterministic")), str(item.get("expires_at", "offline-deterministic-expiry"))), str(item.get("required_approver_role", policy.required_approver_role)), evidence, conditions, str(item.get("created_at", "offline-deterministic")), str(item.get("expires_at", "offline-deterministic-expiry")), str(item.get("status", "pending_review")), True, False, False, False,
    )


def _default_requests() -> tuple[ApprovalRequest, ...]:
    return (
        make_request(approval_id="approval-email-draft", request_type="email_send", title="Send client outreach email", linked_tool_id="send_email", linked_skill_id="cold_email_draft", external_system="email", side_effect_type="message", requested_mode="approval_required"),
        make_request(approval_id="approval-site-publish", request_type="site_publish", title="Publish site draft", linked_tool_id="publish_site", linked_workflow_id="launch_pack_to_site_draft", external_system="hosting", side_effect_type="publish", requested_mode="approval_required"),
        make_request(approval_id="approval-payment", request_type="payment_creation", title="Create payment", linked_tool_id="create_payment", external_system="payment_provider", side_effect_type="financial", requested_mode="approval_required"),
        make_request(approval_id="approval-provider-call", request_type="provider_call", title="Call external provider", linked_tool_id="search_web", external_system="provider", side_effect_type="network_read", requested_mode="approval_required"),
        make_request(approval_id="approval-model-spend", request_type="model_spend", title="Spend on bounded model route", linked_model_route_id="sales_draft_variants", external_system="model_gateway", side_effect_type="model_cost", requested_budget=0.20, requested_mode="approval_simulation"),
        make_request(approval_id="approval-manual-import", request_type="web_data_acquisition", title="Use sanitized manual import", requested_by_agent="lead-researcher", owner_department="intelligence", external_system="manual_file", side_effect_type="read", requested_mode="draft_only", status="draft"),
    )


def _registry_snapshot(registry_report: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    data = _clean(registry_report)
    tools = data.get("tools", {}).get("tools", []) if isinstance(data, Mapping) else []
    workflows = data.get("workflows", {}).get("workflows", []) if isinstance(data, Mapping) else []
    agents = data.get("agents", {}).get("agents", []) if isinstance(data, Mapping) else []
    skills = data.get("skills", {}).get("skills", []) if isinstance(data, Mapping) else []
    routes = data.get("model_router", {}).get("policy", {}).get("routes", []) if isinstance(data, Mapping) else []
    evals = data.get("eval_registry", {}) if isinstance(data, Mapping) else {}
    knowledge = data.get("knowledge", {}).get("sources", []) if isinstance(data, Mapping) else []
    snapshot = {"tool_count": len(tools), "workflow_count": len(workflows), "agent_count": len(agents), "skill_count": len(skills), "model_route_count": len(routes), "quality_gate_count": len(evals.get("quality_gates", [])) if isinstance(evals, Mapping) else 0, "knowledge_source_count": len(knowledge)}
    interrupt_values = []
    for item in workflows:
        if not isinstance(item, Mapping):
            continue
        for point in item.get("human_approval_points", []):
            if isinstance(point, str):
                interrupt_values.append(point)
            elif isinstance(point, Mapping):
                interrupt_values.append(str(point.get("point", point.get("interrupt_id", ""))))
    failed_gates = sorted(str(item.get("gate_id")) for item in evals.get("gate_results", []) if isinstance(item, Mapping) and str(item.get("status", "")).lower() not in {"pass", "passed", "ok"}) if isinstance(evals, Mapping) else []
    linked = {"blocked_tools": sorted(str(item.get("tool_id")) for item in tools if isinstance(item, Mapping) and str(item.get("default_mode", "")) == "blocked"), "workflow_interrupts": sorted({point for point in interrupt_values if point}), "forbidden_agent_actions": sorted({str(action) for item in agents if isinstance(item, Mapping) for action in item.get("forbidden_actions", [])}), "quality_gates": sorted(str(item.get("gate_id")) for item in evals.get("quality_gates", []) if isinstance(item, Mapping)) if isinstance(evals, Mapping) else [], "failed_quality_gates": failed_gates, "privacy_sources": sorted(str(item.get("source_id")) for item in knowledge if isinstance(item, Mapping) and str(item.get("access_level", "")) != "public")}
    return snapshot, linked


def _audit_for_requests(requests: Sequence[ApprovalRequest], generated_at: str) -> tuple[ApprovalAuditEvent, ...]:
    return tuple(ApprovalAuditEvent(f"audit-{request.approval_id}", request.approval_id, "approval_request_created", request.requested_by_agent, generated_at, "none", request.status, "Deterministic offline request assessment.", tuple(item.ref_id for item in request.evidence)) for request in requests)


def build_approval_ledger(*, generated_at: str = "offline-deterministic", registry_report: Any | None = None, approval_requests: Sequence[Mapping[str, Any]] | None = None, simulations: Sequence[ApprovalSimulation] = ()) -> ApprovalLedgerReport:
    """Build an immutable report from registry definitions and sanitized requests."""
    if registry_report is None:
        from .companyos_registry_report import build_companyos_registry_report
        registry_report = build_companyos_registry_report(generated_at=generated_at)
    snapshot, linked = _registry_snapshot(registry_report)
    requests = tuple(_request_from_mapping(item, index) for index, item in enumerate(approval_requests or (), 1)) if approval_requests is not None else _default_requests()
    requests = tuple(sorted(requests, key=lambda item: item.approval_id))
    if linked["failed_quality_gates"]:
        requests = tuple(replace(request, status="blocked_by_policy") for request in requests if request.status not in {"expired", "revoked"}) + tuple(request for request in requests if request.status in {"expired", "revoked"})
    policies = default_approval_policies()
    decisions = tuple(ApprovalDecision(f"decision-{request.approval_id}", request.approval_id, "simulation_only", "human_operator", "placeholder", "No live approval is granted by offline mode.", tuple(condition.description for condition in request.conditions if not condition.satisfied), generated_at, True) for request in requests if request.status == "simulated")
    audits = _audit_for_requests(requests, generated_at)
    queue = ApprovalQueueSummary(sum(request.status == "pending_review" for request in requests), sum(request.status == "approved" for request in requests), sum(request.status == "denied" for request in requests), sum(request.status == "expired" for request in requests), sum(request.status == "revoked" for request in requests), sum(request.status == "blocked_by_policy" for request in requests), sum(request.status in {"draft", "simulated"} for request in requests), sum(request.risk_level in {"high", "critical", "blocked"} for request in requests), sum(any(not condition.satisfied for condition in request.conditions if condition.required) for request in requests))
    highest = tuple(sorted(requests, key=lambda item: (RISK_LEVELS.index(item.risk_level), item.approval_id), reverse=True)[:5])
    safety = ApprovalLedgerSafetySummary(True, False, False, False, False, False, True, bool(audits), False, "Offline ledger only; records and simulations do not authorize execution.")
    return ApprovalLedgerReport("companyos-approval-ledger-v1", generated_at, len(requests), queue.pending, queue.approved, queue.denied, queue.expired, queue.revoked, queue.blocked, sum(item.risk_level == "critical" for item in requests), highest, requests, decisions, audits, (), tuple(item.requested_time_window for item in requests), policies, tuple(simulations), queue, safety, {"registry_counts": snapshot, "linked_controls": linked}, "Review blocked and pending requests; keep external-world actions disabled until a future credential, policy, and human-approval implementation is explicitly reviewed.")


def transition_status(request: ApprovalRequest, new_status: str, *, actor: str = "human_operator", reason: str = "offline review", generated_at: str = "offline-deterministic") -> tuple[ApprovalRequest, ApprovalAuditEvent]:
    if new_status not in STATUS_VALUES:
        raise ValueError(f"invalid approval status: {new_status}")
    if request.status in {"revoked", "expired", "denied"} and new_status not in {request.status}:
        raise ValueError(f"terminal approval status cannot transition: {request.status}")
    if new_status == "approved":
        raise ValueError("offline mode cannot grant live approval")
    updated = ApprovalRequest(**{**request.to_dict(), "requested_scope": request.requested_scope, "requested_budget_cap": request.requested_budget_cap, "requested_time_window": request.requested_time_window, "evidence": request.evidence, "conditions": request.conditions, "status": new_status})
    event = ApprovalAuditEvent(f"audit-{request.approval_id}-{new_status}", request.approval_id, "approval_status_changed", actor, generated_at, request.status, new_status, reason, tuple(item.ref_id for item in request.evidence))
    return updated, event


def revoke_request(request: ApprovalRequest, *, revoked_by: str = "human_operator", reason: str = "operator revoked in offline review", generated_at: str = "offline-deterministic") -> tuple[ApprovalRequest, ApprovalRevocation, ApprovalAuditEvent]:
    if request.status == "revoked":
        raise ValueError("request is already revoked")
    updated, event = transition_status(request, "revoked", actor=revoked_by, reason=reason, generated_at=generated_at)
    revocation = ApprovalRevocation(f"revocation-{request.approval_id}", request.approval_id, revoked_by, generated_at, reason)
    return updated, revocation, event


__all__ = [
    "REQUEST_TYPES", "STATUS_VALUES", "RISK_LEVELS", "DECISION_CLASSES", "SIMULATION_STATUSES",
    "ApprovalLedgerReport", "ApprovalRequest", "ApprovalDecision", "ApprovalScope", "ApprovalCondition",
    "ApprovalRequirement", "ApprovalPolicy", "ApprovalRiskAssessment", "ApprovalBudgetCap", "ApprovalToolLink",
    "ApprovalWorkflowLink", "ApprovalEvidence", "ApprovalAuditEvent", "ApprovalRevocation", "ApprovalExpiry",
    "ApprovalSimulation", "ApprovalQueueSummary", "ApprovalLedgerSafetySummary", "default_approval_policies",
    "make_request", "simulate_action", "build_approval_ledger", "transition_status", "revoke_request",
]
