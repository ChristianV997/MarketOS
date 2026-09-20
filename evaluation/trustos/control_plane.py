"""TrustOS Control Plane v1.

TrustOS deliberately reduces security, privacy, legal, tax, AI-governance,
provider, and launch checks to four reusable objects: controls describe what
must be true, evidence describes how it is proved, gates decide whether an
action may proceed, and exceptions identify the human/professional review
needed when it cannot.

This module is metadata-only. It never scans, calls providers, reads secrets,
stores artifacts, makes legal/tax conclusions, or performs external actions.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, is_dataclass
from typing import Any, Iterable, Mapping, Sequence

DOMAINS = (
    "security", "privacy", "legal", "tax", "ai_governance", "provider_risk",
    "public_launch", "client_workspace", "financial_controls", "operations",
)
GATE_BEHAVIORS = ("hard_block", "soft_block", "warn", "track_risk", "allow", "needs_professional_review", "not_applicable")
EXCEPTION_STATUSES = ("none", "requested", "accepted_risk", "rejected", "expired", "requires_lawyer", "requires_accountant", "requires_security_owner", "requires_founder")
EVIDENCE_STATUSES = ("missing", "draft", "present", "stale", "failed", "passed", "not_applicable", "requires_review")
ACTION_CATEGORIES = (
    "publish_site", "activate_provider", "use_credentials", "send_customer_message",
    "send_outbound_email", "launch_ad", "create_order", "create_payment",
    "sync_accounting", "collect_personal_data", "process_uploaded_file",
    "enable_public_signup", "enable_live_model_calls", "run_provider_readonly_call",
    "run_provider_write_call", "public_beta_launch", "client_workspace_export",
    "client_clone_generation", "client_report_generation", "lawyer_packet_export",
    "accountant_packet_export", "security_reviewer_packet_export",
    "client_workspace_activation", "multi_client_workspace_access",
)


def _clean(value: Any) -> Any:
    if is_dataclass(value):
        return {key: _clean(item) for key, item in asdict(value).items()}
    if isinstance(value, Mapping):
        return {str(key): _clean(item) for key, item in value.items()}
    if isinstance(value, (tuple, list, set, frozenset)):
        return [_clean(item) for item in value]
    return value


def _client_safe_scrub(value: Any) -> Any:
    """Remove internal-only vocabulary from a client projection."""
    if isinstance(value, Mapping):
        return {_client_safe_scrub(str(key).replace("internal_notes", "internal_content")): _client_safe_scrub(item) for key, item in value.items() if str(key) not in {"internal_notes", "prompt", "source_code", "formula"}}
    if isinstance(value, list):
        return [_client_safe_scrub(item) for item in value]
    if isinstance(value, str):
        return value.replace("internal_notes", "internal content").replace("cross_client_data", "cross-client content")
    return value


def _tuple(value: Iterable[Any] | None) -> tuple[Any, ...]:
    return tuple(value or ())


@dataclass(frozen=True)
class TrustEvidenceRequirement:
    evidence_type: str
    description: str
    required: bool = True
    freshness_days: int = 0
    professional_review_required: bool = False

    def to_dict(self) -> dict[str, Any]:
        return _clean(self)


@dataclass(frozen=True)
class TrustControl:
    control_id: str
    name: str
    domain: str
    category: str
    description: str
    applies_to_actions: tuple[str, ...]
    applies_to_departments: tuple[str, ...]
    applies_to_jurisdictions: tuple[str, ...]
    risk_level: str
    evidence_required: tuple[TrustEvidenceRequirement, ...]
    gate_behavior: str
    exception_policy: str
    source_refs: tuple[str, ...]
    review_frequency_days: int
    owner_department: str
    professional_review_required: bool
    status: str = "planned"

    def __post_init__(self) -> None:
        if self.domain not in DOMAINS:
            raise ValueError(f"unsupported TrustOS domain: {self.domain}")
        if self.gate_behavior not in GATE_BEHAVIORS:
            raise ValueError(f"unsupported gate behavior: {self.gate_behavior}")
        if not self.applies_to_actions or any(action not in ACTION_CATEGORIES for action in self.applies_to_actions):
            raise ValueError("controls must reference known actions")

    def to_dict(self) -> dict[str, Any]:
        return _clean(self)


@dataclass(frozen=True)
class TrustControlPack:
    pack_id: str
    name: str
    domain: str
    description: str
    controls: tuple[TrustControl, ...]
    source_refs: tuple[str, ...]
    status: str = "metadata_only"

    def to_dict(self) -> dict[str, Any]:
        return _clean(self)


@dataclass(frozen=True)
class TrustEvidenceRecord:
    evidence_id: str
    control_id: str
    source_type: str
    source_ref: str
    summary: str
    owner_department: str
    created_at: str
    expires_at: str
    status: str
    redaction_status: str
    client_visible: bool
    internal_only: bool
    professional_review_required: bool
    notes: str = ""

    def __post_init__(self) -> None:
        if self.status not in EVIDENCE_STATUSES:
            raise ValueError(f"unsupported evidence status: {self.status}")
        if self.client_visible and self.internal_only:
            raise ValueError("evidence cannot be both client-visible and internal-only")

    def to_dict(self) -> dict[str, Any]:
        return _clean(self)


@dataclass(frozen=True)
class TrustEvidenceSource:
    source_id: str
    source_type: str
    description: str
    allowed_storage: str
    metadata_only: bool = True

    def to_dict(self) -> dict[str, Any]:
        return _clean(self)


@dataclass(frozen=True)
class TrustEvidenceExpiry:
    evidence_id: str
    expires_at: str
    action: str
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return _clean(self)


@dataclass(frozen=True)
class TrustEvidenceRedaction:
    evidence_id: str
    redacted_fields: tuple[str, ...]
    policy: str
    client_export_allowed: bool

    def to_dict(self) -> dict[str, Any]:
        return _clean(self)


@dataclass(frozen=True)
class TrustEvidenceExportPolicy:
    policy_id: str
    client_visible_fields: tuple[str, ...]
    excluded_fields: tuple[str, ...]
    internal_only_fields: tuple[str, ...]
    cross_client_isolation: bool = True

    def to_dict(self) -> dict[str, Any]:
        return _clean(self)


@dataclass(frozen=True)
class TrustGate:
    gate_id: str
    action: str
    name: str
    control_ids: tuple[str, ...]
    default_decision: str
    required_approvals: tuple[str, ...]
    required_evidence: tuple[str, ...]
    exception_status: str
    notes: str = ""

    def __post_init__(self) -> None:
        if self.action not in ACTION_CATEGORIES:
            raise ValueError(f"unsupported TrustOS action: {self.action}")
        if self.default_decision not in GATE_BEHAVIORS:
            raise ValueError(f"unsupported gate decision: {self.default_decision}")
        if self.exception_status not in EXCEPTION_STATUSES:
            raise ValueError(f"unsupported exception status: {self.exception_status}")

    def to_dict(self) -> dict[str, Any]:
        return _clean(self)


@dataclass(frozen=True)
class TrustGateResult:
    gate_id: str
    action: str
    decision: str
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]
    missing_evidence: tuple[str, ...]
    required_approvals: tuple[str, ...]
    exception_request: str
    evaluated_at: str
    simulated: bool = True

    def __post_init__(self) -> None:
        if self.decision not in GATE_BEHAVIORS:
            raise ValueError(f"unsupported gate result: {self.decision}")

    def to_dict(self) -> dict[str, Any]:
        return _clean(self)


@dataclass(frozen=True)
class TrustException:
    exception_id: str
    control_id: str
    action: str
    status: str
    requested_by: str
    approver_role: str
    reason: str
    expires_at: str
    evidence_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.status not in EXCEPTION_STATUSES:
            raise ValueError(f"unsupported exception status: {self.status}")

    def to_dict(self) -> dict[str, Any]:
        return _clean(self)


@dataclass(frozen=True)
class TrustRiskItem:
    risk_id: str
    domain: str
    title: str
    description: str
    likelihood: str
    impact: str
    mitigation: str
    owner_department: str
    status: str
    professional_review_required: bool = False

    def to_dict(self) -> dict[str, Any]:
        return _clean(self)


@dataclass(frozen=True)
class TrustPolicySource:
    source_id: str
    name: str
    scope: str
    status: str
    note: str

    def to_dict(self) -> dict[str, Any]:
        return _clean(self)


@dataclass(frozen=True)
class TrustJurisdiction:
    jurisdiction_id: str
    name: str
    relevance: str
    review_required: bool
    note: str

    def to_dict(self) -> dict[str, Any]:
        return _clean(self)


@dataclass(frozen=True)
class TrustActionManifest:
    action: str
    description: str
    external_world_effect: bool
    default_gate: str
    approval_ledger_request_type: str
    professional_review: str = "none"

    def __post_init__(self) -> None:
        if self.action not in ACTION_CATEGORIES:
            raise ValueError(f"unsupported action manifest action: {self.action}")

    def to_dict(self) -> dict[str, Any]:
        return _clean(self)


@dataclass(frozen=True)
class TrustModuleManifest:
    module_id: str
    name: str
    version: str
    domains: tuple[str, ...]
    controls: tuple[str, ...]
    gates: tuple[str, ...]
    safety_boundary: str

    def to_dict(self) -> dict[str, Any]:
        return _clean(self)


@dataclass(frozen=True)
class TrustScorecard:
    scorecard_id: str
    scope: str
    total_controls: int
    passed_controls: int
    missing_evidence: int
    hard_blockers: int
    soft_blockers: int
    warnings: int
    score: float
    grade: str
    assumptions: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return _clean(self)


@dataclass(frozen=True)
class TrustReadinessSummary:
    internal_dry_run: str
    private_beta: str
    public_beta: str
    provider_activation: str
    customer_facing_launch: str
    professional_review_needed: bool
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return _clean(self)


@dataclass(frozen=True)
class TrustSafetySummary:
    read_only: bool = True
    network_calls: bool = False
    scanner_runs: bool = False
    credentials_read: bool = False
    raw_payloads_stored: bool = False
    legal_conclusions: bool = False
    tax_conclusions: bool = False
    external_mutations: bool = False
    client_data_present: bool = False
    fail_closed: bool = True

    def __post_init__(self) -> None:
        if not self.read_only or any((self.network_calls, self.scanner_runs, self.credentials_read, self.raw_payloads_stored, self.legal_conclusions, self.tax_conclusions, self.external_mutations, self.client_data_present)):
            raise ValueError("TrustOS must remain offline, metadata-only, and fail-closed")

    def to_dict(self) -> dict[str, Any]:
        return _clean(self)


@dataclass(frozen=True)
class TrustOSReport:
    report_version: str
    generated_at: str
    controls: tuple[TrustControl, ...]
    policy_packs: tuple[TrustControlPack, ...]
    evidence_records: tuple[TrustEvidenceRecord, ...]
    gates: tuple[TrustGate, ...]
    gate_results: tuple[TrustGateResult, ...]
    exceptions: tuple[TrustException, ...]
    risks: tuple[TrustRiskItem, ...]
    scorecards: tuple[TrustScorecard, ...]
    readiness: TrustReadinessSummary
    hard_blocker_count: int
    soft_blocker_count: int
    warning_count: int
    next_best_action: str
    service_package_opportunities: tuple[str, ...]
    safety_summary: TrustSafetySummary

    def to_dict(self) -> dict[str, Any]:
        data = _clean(self)
        data.update({
            "control_count": len(self.controls),
            "policy_pack_count": len(self.policy_packs),
            "evidence_record_count": len(self.evidence_records),
            "gate_count": len(self.gates),
            "exception_count": len(self.exceptions),
            "public_launch_decision": self.readiness.public_beta,
            "provider_activation_decision": self.readiness.provider_activation,
            "client_workspace_export_decision": next((result.decision for result in self.gate_results if result.action == "client_workspace_export"), "hard_block"),
            "top_blockers": list(self.readiness.blockers[:10]),
            "top_missing_evidence": [record.control_id for record in self.evidence_records if record.status == "missing"],
            "trust_scorecard": _clean(self.scorecards[0]) if self.scorecards else {},
        })
        return data

    def to_markdown(self, *, client_safe: bool = False) -> str:
        lines = [
            "# TrustOS Control Plane", "", "## Executive Summary", "",
            f"- Controls: **{len(self.controls)}**", f"- Policy packs: **{len(self.policy_packs)}**",
            f"- Evidence records: **{len(self.evidence_records)}**", f"- Gates: **{len(self.gates)}**",
            f"- Public beta: **{self.readiness.public_beta}**", f"- Provider activation: **{self.readiness.provider_activation}**",
            f"- Mode: **offline, metadata-only, fail-closed**", "",
            "## Control / Evidence / Gate / Exception", "",
            "TrustOS records what must be true, how it is evidenced, when an action is blocked, and who may review an exception.", "",
            "## Policy Packs", "", "| Pack | Domain | Controls | Status |", "|---|---|---:|---|",
        ]
        for pack in self.policy_packs:
            lines.append(f"| {pack.name} | {pack.domain} | {len(pack.controls)} | {pack.status} |")
        lines += ["", "## Readiness", "", f"- Internal dry run: **{self.readiness.internal_dry_run}**", f"- Private beta: **{self.readiness.private_beta}**", f"- Public beta: **{self.readiness.public_beta}**", f"- Customer-facing launch: **{self.readiness.customer_facing_launch}**", ""]
        lines += ["## Hard Blockers", ""] + [f"- {item}" for item in self.readiness.blockers] + ["", "## Missing Evidence", ""] + [f"- {record.control_id}: {record.summary}" for record in self.evidence_records if record.status in {"missing", "draft", "requires_review"}]
        lines += ["", "## Gate Results", "", "| Action | Decision | Blockers | Warnings |", "|---|---|---:|---:|"]
        for result in self.gate_results:
            lines.append(f"| {result.action} | {result.decision} | {len(result.blockers)} | {len(result.warnings)} |")
        lines += ["", "## Service Opportunities", ""] + [f"- {item}" for item in self.service_package_opportunities]
        lines += ["", "## Next Best Action", "", self.next_best_action, "", "## Safety Boundaries", "", "No scanners, provider calls, credentials, legal/tax conclusions, raw payloads, client data, or external mutations are used."]
        if client_safe:
            lines = [line for line in lines if "internal" not in line.lower() and "formula" not in line.lower()]
        return "\n".join(lines) + "\n"


def build_action_manifests() -> tuple[TrustActionManifest, ...]:
    request_map = {
        "activate_provider": "provider_call", "use_credentials": "provider_call", "send_customer_message": "customer_message",
        "send_outbound_email": "email_send", "launch_ad": "ad_launch", "create_order": "supplier_order",
        "create_payment": "payment_creation", "sync_accounting": "accounting_sync", "publish_site": "site_publish",
        "run_provider_readonly_call": "provider_call", "run_provider_write_call": "provider_call", "enable_live_model_calls": "model_spend",
        "public_beta_launch": "site_publish", "client_workspace_export": "customer_message",
    }
    professional = {"create_payment": "accountant", "public_beta_launch": "lawyer/security_owner", "collect_personal_data": "privacy_owner"}
    return tuple(TrustActionManifest(action, action.replace("_", " ").title(), action not in {"process_uploaded_file"}, "hard_block" if action not in {"process_uploaded_file"} else "needs_professional_review", request_map.get(action, "none"), professional.get(action, "none")) for action in ACTION_CATEGORIES)


def build_trust_risks() -> tuple[TrustRiskItem, ...]:
    rows = (
        ("security", "security-evidence", "Security evidence is not scanned", "No scanner execution occurs in offline mode.", "medium", "high", "Run approved security, dependency, and secret scans later."),
        ("privacy", "privacy-policy", "Privacy policy is not approved", "Client-facing data handling requires reviewed policy text.", "medium", "high", "Obtain privacy-owner or lawyer review."),
        ("legal", "terms-policy", "Terms are not approved", "Public launch terms remain a draft requirement.", "medium", "high", "Obtain lawyer review; TrustOS gives no legal conclusion."),
        ("tax", "tax-classification", "Tax classification is not reviewed", "Jurisdiction and filing questions require an accountant.", "medium", "high", "Prepare accountant-ready packet."),
        ("ai_governance", "agent-boundary", "AI agent controls need evidence", "Prompt injection and approval-bypass tests are planned only.", "medium", "high", "Run approved governance test suite later."),
        ("provider_risk", "provider-activation", "Provider activation is blocked", "Credential, terms, privacy, approval, and output evidence are incomplete.", "high", "high", "Keep live provider calls disabled."),
        ("client_workspace", "workspace-isolation", "Client export isolation is planned", "Cross-client leakage must be tested before export.", "medium", "high", "Use client-safe projection and isolation tests."),
        ("financial_controls", "payment-review", "Payment actions require accountant review", "No payment is created by this system.", "low", "critical", "Keep payment creation blocked."),
    )
    return tuple(TrustRiskItem(rid, domain, title, description, likelihood, impact, mitigation, "risk_approval", "open", domain in {"legal", "tax", "privacy"}) for domain, rid, title, description, likelihood, impact, mitigation in rows)


def build_default_evidence() -> tuple[TrustEvidenceRecord, ...]:
    required = (
        ("security-scan", "Security scan evidence is planned, not run.", "missing", False),
        ("privacy-policy", "Privacy policy draft requires owner review.", "draft", True),
        ("terms-policy", "Terms draft requires lawyer review.", "draft", True),
        ("tax-review", "Tax classification requires accountant review.", "missing", True),
        ("provider-approval", "Approval Ledger activation request is not approved.", "missing", False),
        ("credential-reference", "Credential Registry reference is metadata-only.", "present", False),
        ("ai-safety-eval", "AI safety evaluation evidence is planned.", "missing", True),
        ("workspace-isolation", "Client workspace isolation evidence is planned.", "missing", False),
    )
    return tuple(TrustEvidenceRecord(f"evidence-{key}", key, "metadata_check", f"trustos://{key}", summary, "risk_approval", "offline-deterministic", "TBD", status, "none", not internal, internal, professional, "No artifact is stored by default.") for key, summary, status, professional in required for internal in (False,))


def build_trust_gates() -> tuple[TrustGate, ...]:
    return tuple(TrustGate(f"gate-{action}", action, action.replace("_", " ").title(), (), "hard_block" if action not in {"process_uploaded_file"} else "needs_professional_review", ("human_operator",), ("approval-ledger-request",), "requires_founder" if action in {"public_beta_launch", "client_workspace_export"} else "none", "Simulation only; no action is performed.") for action in ACTION_CATEGORIES)


def build_trust_controls() -> tuple[TrustControl, ...]:
    pack_specs = {
        "security": ("security_baseline", "Security Baseline", "NIST CSF 2.0; CIS Controls; OWASP ASVS; OWASP SAMM; OpenSSF Scorecard", ("secret_scan", "dependency_scan", "supply_chain", "code_scan", "sbom", "cicd_hardening", "incident_contact", "admin_access", "rate_limit", "audit_logging")),
        "ai_governance": ("ai_agent_security", "AI Agent Security", "OWASP LLM Top 10; NIST AI RMF; PyRIT; garak", ("prompt_injection", "tool_hijack", "secret_exfiltration", "model_spend", "approval_bypass", "untrusted_input", "least_privilege", "no_prompt_credentials", "no_unrestricted_internet")),
        "provider_risk": ("provider_activation", "Provider / Data Activation", "Approval Ledger; Credential Registry; Provider Registry", ("provider_registered", "credential_reference", "secret_absent", "approval_request", "budget_cap", "terms_review", "privacy_review", "output_contract", "raw_payload_policy", "live_disabled")),
        "privacy": ("privacy_legal_baseline", "Privacy / Legal Baseline", "Privacy policy; terms draft; DPA/vendor review metadata", ("privacy_policy", "terms", "retention", "cookie_disclosure", "rights_workflow", "identity_disclosure", "consent", "dpa_review", "professional_review")),
        "tax": ("tax_accounting_readiness", "Tax / Accounting Readiness", "Accountant review metadata; jurisdiction checklist", ("tax_classification", "sales_tax_flags", "invoice_review", "cfdi_review", "vat_oss_review", "gst_hst_review", "us_nexus_review", "accountant_review")),
        "public_launch": ("public_launch_readiness", "Public Launch Readiness", "TrustOS readiness policy; approval and evidence records", ("security_evidence", "secret_clean", "dependency_clean", "policies", "incident_response", "provider_gates", "approval_ledger", "trust_scorecard", "abuse_policy", "workspace_isolation")),
        "client_workspace": ("client_trustos_service", "Client-safe TrustOps", "Client-safe export policy; isolation review", ("safe_report", "evidence_checklist", "risk_register", "lawyer_packet", "accountant_packet", "security_packet", "no_prompts", "no_cross_client", "minimal_export")),
    }
    controls: list[TrustControl] = []
    for domain, (pack_id, _name, source, keys) in pack_specs.items():
        for key in keys:
            action = "public_beta_launch" if domain in {"security", "privacy", "legal", "tax", "public_launch"} else "activate_provider" if domain == "provider_risk" else "client_workspace_export" if domain == "client_workspace" else "enable_live_model_calls"
            professional = domain in {"privacy", "legal", "tax"} or key in {"terms_review", "privacy_review", "cfdi_review", "accountant_review", "professional_review"}
            behavior = "needs_professional_review" if professional else "hard_block" if key in {"secret_absent", "approval_request", "live_disabled", "no_prompt_credentials", "no_unrestricted_internet", "no_cross_client"} else "soft_block"
            evidence = TrustEvidenceRequirement(f"{key}_evidence", f"Evidence for {key.replace('_', ' ')}", True, 90 if domain == "security" else 365, professional)
            controls.append(TrustControl(f"control-{pack_id}-{key}", key.replace("_", " ").title(), domain, pack_id, f"{key.replace('_', ' ').capitalize()} must be reviewed before the related action.", (action,), ("management", "risk_approval", domain), ("global",), "high" if behavior in {"hard_block", "needs_professional_review"} else "medium", (evidence,), behavior, "professional review or founder exception where applicable", (source,), 90 if domain == "security" else 180, "risk_approval", professional, "planned"))
    extras = (
        ("legal", "privacy_legal_baseline", "legal_review", "Legal review must be completed before public-facing launch materials are approved.", "public_beta_launch", True),
        ("financial_controls", "tax_accounting_readiness", "financial_controls", "Financial controls require accountant-reviewed inputs before financial actions.", "create_payment", True),
        ("operations", "public_launch_readiness", "operations_owner", "Operations owner and incident response responsibilities must be assigned.", "public_beta_launch", False),
    )
    for domain, pack_id, key, description, action, professional in extras:
        controls.append(TrustControl(f"control-{pack_id}-{key}", key.replace("_", " ").title(), domain, pack_id, description, (action,), ("management", "risk_approval", "operations"), ("global",), "high" if professional else "medium", (TrustEvidenceRequirement(f"{key}_evidence", f"Evidence for {key.replace('_', ' ')}", True, 180, professional),), "needs_professional_review" if professional else "soft_block", "professional review or founder exception where applicable", ("TrustOS readiness policy",), 180, "risk_approval", professional, "planned"))
    from .mexico_product_compliance import build_mexico_trust_controls
    return tuple(controls) + build_mexico_trust_controls()


def build_policy_packs_from_controls(controls: Sequence[TrustControl]) -> tuple[TrustControlPack, ...]:
    grouped: dict[str, list[TrustControl]] = {}
    names: dict[str, str] = {}
    sources: dict[str, set[str]] = {}
    for control in controls:
        grouped.setdefault(control.category, []).append(control)
        names[control.category] = control.category.replace("_", " ").title()
        sources.setdefault(control.category, set()).update(control.source_refs)
    return tuple(TrustControlPack(key, names[key], next(item.domain for item in values), f"Deterministic {names[key]} policy pack.", tuple(values), tuple(sorted(sources[key]))) for key, values in sorted(grouped.items()))


def build_trustos_report(*, generated_at: str = "offline-deterministic", action_context: Mapping[str, Any] | None = None) -> TrustOSReport:
    controls = build_trust_controls()
    packs = build_policy_packs_from_controls(controls)
    evidence = build_default_evidence()
    gates = build_trust_gates()
    from .gate_runner import evaluate_action
    context = dict(action_context or {})
    results = tuple(evaluate_action(gate.action, context=context, generated_at=generated_at) for gate in gates)
    risks = build_trust_risks()
    missing = sum(1 for item in evidence if item.status in {"missing", "draft", "requires_review"})
    hard = sum(1 for item in results if item.decision == "hard_block")
    soft = sum(1 for item in results if item.decision == "soft_block")
    warnings = sum(len(item.warnings) for item in results)
    score = round(max(0.0, min(100.0, (len(controls) - missing) / max(1, len(controls)) * 100)), 1)
    grade = "A" if score >= 90 else "B" if score >= 75 else "C" if score >= 60 else "D"
    scorecard = TrustScorecard("trustos-global", "company", len(controls), len(controls) - missing, missing, hard, soft, warnings, score, grade, ("Offline metadata only; no professional conclusion.",))
    readiness = TrustReadinessSummary("allow", "soft_block", "blocked_for_public_beta", "blocked_for_live_provider_activation", "blocked_for_customer_facing_launch", True, tuple(item for item in ("security evidence missing", "privacy/terms review pending", "tax/accountant review pending", "provider approval and live transport disabled", "client isolation evidence missing") if item), ("Fixture/readiness evidence is not production proof.",))
    services = ("Public Launch Readiness Audit", "SaaS Trust & Compliance Setup", "AI Agent Safety Audit", "Ecommerce Compliance Readiness", "Provider/Vendor Risk Review", "Monthly TrustOps Retainer", "Lawyer/Accountant-Ready Packet")
    return TrustOSReport("trustos-control-plane-v1", generated_at, controls, packs, evidence, gates, results, (), risks, (scorecard,), readiness, hard, soft, warnings, "Keep public launch and live provider activation blocked; complete the evidence checklist with the appropriate professional owners.", services, TrustSafetySummary())


__all__ = ["DOMAINS", "GATE_BEHAVIORS", "EXCEPTION_STATUSES", "EVIDENCE_STATUSES", "ACTION_CATEGORIES", "TrustOSReport", "TrustControl", "TrustControlPack", "TrustEvidenceRequirement", "TrustEvidenceRecord", "TrustEvidenceSource", "TrustEvidenceExpiry", "TrustEvidenceRedaction", "TrustEvidenceExportPolicy", "TrustGate", "TrustGateResult", "TrustException", "TrustRiskItem", "TrustPolicySource", "TrustJurisdiction", "TrustActionManifest", "TrustModuleManifest", "TrustScorecard", "TrustReadinessSummary", "TrustSafetySummary", "build_action_manifests", "build_trust_risks", "build_default_evidence", "build_trust_gates", "build_trust_controls", "build_policy_packs_from_controls", "build_trustos_report"]
