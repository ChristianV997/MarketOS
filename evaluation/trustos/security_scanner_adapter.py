"""Offline security-scanner evidence normalization for TrustOS.

This adapter wraps sanitized scanner-shaped outputs. It never runs a scanner,
calls GitHub, reads credentials, stores raw reports, or retains secrets,
exploit payloads, HTML, or vulnerable source code.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict, is_dataclass
from typing import Any, Mapping, Sequence

from .control_plane import TrustEvidenceRecord, TrustException, TrustGateResult, TrustRiskItem, _clean, build_trust_controls
from .gate_runner import evaluate_action

SCANNER_IDS = (
    "gitleaks", "trufflehog", "github_secret_scanning", "codeql_sarif", "semgrep_json", "semgrep_sarif", "osv_scanner", "trivy", "syft_sbom", "grype", "openssf_scorecard", "owasp_dependency_check", "zap_baseline", "nuclei", "pyr_it", "garak", "manual_security_review",
)
CATEGORIES = (
    "secret_exposure", "dependency_vulnerability", "code_vulnerability", "misconfiguration", "supply_chain", "sbom_inventory", "repo_posture", "web_app_security", "api_security", "ai_prompt_injection", "ai_tool_hijack", "ai_secret_exfiltration", "ai_model_spend_abuse", "ai_approval_bypass", "manual_review",
)
SEVERITIES = ("info", "low", "medium", "high", "critical", "unknown")
INTEGRATION_MODES = ("normalize_fixture_now", "normalize_uploaded_output_later", "run_local_later", "run_ci_later", "study_later", "avoid_for_now")
GATE_ACTIONS = ("public_beta_launch", "customer_facing_launch", "activate_provider", "use_credentials", "enable_public_signup", "enable_live_model_calls", "run_provider_readonly_call", "process_uploaded_file", "client_workspace_export")
REDACTION_OUTCOMES = ("redacted", "rejected", "safe_summary_only", "allowed_metadata")
SECRET_KEYS = {"actual_secret_value", "api_key", "raw_api_key", "oauth_token", "raw_oauth_token", "access_token", "refresh_token", "password", "private_key", "private_key_material", "cookie", "cookies", "jwt", "token", "authorization", "database_url", "webhook_secret", "client_secret", "raw_payload", "raw_html", "exploit_payload", "vulnerable_code"}


def _secret_like(value: Any) -> bool:
    if isinstance(value, Mapping):
        return any(str(key).lower().replace("-", "_") in SECRET_KEYS or _secret_like(item) for key, item in value.items())
    if isinstance(value, (list, tuple)):
        return any(_secret_like(item) for item in value)
    if isinstance(value, str):
        lowered = value.lower()
        return "-----begin " in lowered or "bearer " in lowered or "<html" in lowered or "<script" in lowered or any(marker in lowered for marker in ("sk-", "ghp_", "xoxb-", "AIza", "eyjhb", "jdbc:", "mysql://", "postgres://"))
    return False


def _clean_text(value: Any, default: str = "Synthetic scanner summary.", limit: int = 280) -> str:
    text = str(value if value not in (None, "") else default).replace("\n", " ").strip()
    if _secret_like(text):
        raise ValueError("secret-like, HTML, or exploit-like scanner text is not accepted")
    return text[:limit]


def _severity(value: Any) -> str:
    value = str(value or "unknown").lower().replace("error", "high").replace("warning", "medium")
    return value if value in SEVERITIES else "unknown"


def _category(scanner_id: str, item: Mapping[str, Any]) -> str:
    explicit = str(item.get("category", item.get("type", ""))).lower().replace("-", "_").replace(" ", "_")
    if explicit in CATEGORIES:
        return explicit
    if scanner_id in {"gitleaks", "trufflehog", "github_secret_scanning"}:
        return "secret_exposure"
    if scanner_id in {"osv_scanner", "trivy", "grype", "owasp_dependency_check"}:
        return "dependency_vulnerability"
    if scanner_id in {"codeql_sarif", "semgrep_json", "semgrep_sarif"}:
        return "code_vulnerability"
    if scanner_id == "syft_sbom":
        return "sbom_inventory"
    if scanner_id == "openssf_scorecard":
        return "repo_posture"
    if scanner_id in {"zap_baseline", "nuclei"}:
        return "web_app_security"
    if scanner_id in {"pyr_it", "garak"}:
        return explicit if explicit in {"ai_prompt_injection", "ai_tool_hijack", "ai_secret_exfiltration", "ai_model_spend_abuse", "ai_approval_bypass"} else "ai_prompt_injection"
    return "manual_review"


def _items(payload: Mapping[str, Any], scanner_id: str) -> list[Mapping[str, Any]]:
    direct_key = next((key for key in ("findings", "results", "alerts") if key in payload), None)
    direct = payload.get(direct_key, ()) if direct_key else ()
    if direct_key and (not isinstance(direct, Sequence) or isinstance(direct, (str, bytes))):
        raise ValueError(f"scanner fixture field {direct_key} must be a list")
    rows: list[Mapping[str, Any]] = []
    if isinstance(direct, Sequence) and not isinstance(direct, (str, bytes)):
        rows.extend(item for item in direct if isinstance(item, Mapping))
    runs = payload.get("runs", ())
    if runs and (not isinstance(runs, Sequence) or isinstance(runs, (str, bytes))):
        raise ValueError("scanner fixture field runs must be a list")
    for run in runs if isinstance(runs, Sequence) else ():
        if isinstance(run, Mapping):
            run_results = run.get("results", ())
            if not isinstance(run_results, Sequence) or isinstance(run_results, (str, bytes)):
                raise ValueError("scanner fixture run results must be a list")
            rows.extend(item for item in run_results if isinstance(item, Mapping))
    if scanner_id == "syft_sbom" and isinstance(payload.get("packages"), Sequence):
        rows.extend({"id": item.get("id", "package"), "name": item.get("name", "Synthetic package"), "category": "sbom_inventory", "severity": "info"} for item in payload["packages"] if isinstance(item, Mapping))
    if scanner_id == "openssf_scorecard" and payload.get("score") is not None:
        rows.append({"id": "scorecard", "title": "Synthetic repository posture score", "category": "repo_posture", "severity": "low" if float(payload.get("score", 10)) < 7 else "info", "summary": f"Synthetic score: {payload.get('score')}"})
    if scanner_id == "manual_security_review" and isinstance(payload.get("checks"), Sequence):
        rows.extend({"id": item.get("id", "manual-check"), "title": item.get("title", "Manual security review"), "category": "manual_review", "severity": item.get("severity", "unknown"), "status": item.get("status", "requires_review")} for item in payload["checks"] if isinstance(item, Mapping))
    return rows


@dataclass(frozen=True)
class SecurityFindingSeverity:
    value: str

    def __post_init__(self) -> None:
        if self.value not in SEVERITIES:
            raise ValueError(f"unsupported security severity: {self.value}")

    def to_dict(self) -> dict[str, Any]:
        return _clean(self)


@dataclass(frozen=True)
class SecurityFindingCategory:
    value: str

    def __post_init__(self) -> None:
        if self.value not in CATEGORIES:
            raise ValueError(f"unsupported security finding category: {self.value}")

    def to_dict(self) -> dict[str, Any]:
        return _clean(self)


@dataclass(frozen=True)
class SecurityScannerReference:
    scanner_id: str
    name: str
    category: str
    integration_mode: str
    license_note: str
    recommended_use: str
    output_formats: tuple[str, ...]
    trustos_controls_covered: tuple[str, ...]
    default_gate_impact: str
    run_mode: str
    network_required: bool
    credentials_required: bool
    safe_to_run_in_ci_later: bool

    def __post_init__(self) -> None:
        if self.scanner_id not in SCANNER_IDS or self.integration_mode not in INTEGRATION_MODES:
            raise ValueError("unsupported scanner reference")
        if self.run_mode != "normalize_fixture_only":
            raise ValueError("no scanner may run in this adapter")
        if self.network_required or self.credentials_required:
            raise ValueError("scanner reference cannot require live access in v1")

    def to_dict(self) -> dict[str, Any]:
        return _clean(self)


@dataclass(frozen=True)
class SecurityScannerOutputContract:
    contract_id: str
    scanner_id: str
    accepted_formats: tuple[str, ...]
    required_fields: tuple[str, ...]
    normalized_models: tuple[str, ...]
    raw_payload_allowed: bool
    raw_html_allowed: bool
    exploit_payload_allowed: bool
    fixture_tested: bool

    def __post_init__(self) -> None:
        if self.raw_payload_allowed or self.raw_html_allowed or self.exploit_payload_allowed:
            raise ValueError("scanner output contract cannot allow raw or exploit content")

    def to_dict(self) -> dict[str, Any]:
        return _clean(self)


@dataclass(frozen=True)
class SecurityScannerFixture:
    fixture_id: str
    scanner_id: str
    source_file: str
    fixture_mode: bool
    item_count: int
    schema_status: str
    raw_payload_stored: bool = False

    def __post_init__(self) -> None:
        if not self.fixture_mode or self.raw_payload_stored:
            raise ValueError("fixtures must be explicit and raw-payload-free")

    def to_dict(self) -> dict[str, Any]:
        return _clean(self)


@dataclass(frozen=True)
class SecurityScanFinding:
    finding_id: str
    scanner_id: str
    category: str
    severity: str
    title: str
    summary: str
    rule_id: str
    location_placeholder: str
    package_placeholder: str
    evidence_status: str
    redaction_status: str
    source_ref: str
    raw_payload_stored: bool = False
    exploit_payload_stored: bool = False
    client_data_present: bool = False

    def __post_init__(self) -> None:
        if self.category not in CATEGORIES or self.severity not in SEVERITIES:
            raise ValueError("invalid normalized scanner finding")
        if self.raw_payload_stored or self.exploit_payload_stored or self.client_data_present:
            raise ValueError("normalized finding cannot contain unsafe content")

    def to_dict(self) -> dict[str, Any]:
        return _clean(self)


@dataclass(frozen=True)
class SecurityScanSummary:
    scanner_id: str
    status: str
    finding_count: int
    critical_count: int
    high_count: int
    medium_count: int
    low_count: int
    info_count: int
    redacted_count: int
    rejected_count: int
    notes: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return _clean(self)


@dataclass(frozen=True)
class SecurityEvidenceMapping:
    category: str
    trustos_domain: str
    control_ids: tuple[str, ...]
    evidence_status: str
    limitation: str

    def to_dict(self) -> dict[str, Any]:
        return _clean(self)


@dataclass(frozen=True)
class SecurityControlCoverage:
    control_id: str
    scanner_ids: tuple[str, ...]
    finding_count: int
    coverage_status: str
    missing_evidence: bool

    def to_dict(self) -> dict[str, Any]:
        return _clean(self)


@dataclass(frozen=True)
class SecurityGateImpact:
    action: str
    decision: str
    severity: str
    finding_ids: tuple[str, ...]
    reason: str
    next_action: str

    def to_dict(self) -> dict[str, Any]:
        return _clean(self)


@dataclass(frozen=True)
class SecurityScanNormalizationRule:
    rule_id: str
    input_field: str
    output_field: str
    rule: str
    safe_summary_only: bool = True

    def to_dict(self) -> dict[str, Any]:
        return _clean(self)


@dataclass(frozen=True)
class SecurityScanRedactionPolicy:
    policy_id: str
    redacted_patterns: tuple[str, ...]
    rejected_patterns: tuple[str, ...]
    output_behavior: str
    client_export_safe: bool

    def to_dict(self) -> dict[str, Any]:
        return _clean(self)


@dataclass(frozen=True)
class SecurityScanIngestionResult:
    scanner_id: str
    status: str
    findings: tuple[SecurityScanFinding, ...]
    summary: SecurityScanSummary
    evidence_records: tuple[TrustEvidenceRecord, ...]
    risk_items: tuple[TrustRiskItem, ...]
    gate_impacts: tuple[SecurityGateImpact, ...]
    rejected_reason: str = ""
    trustos_gate_results: tuple[TrustGateResult, ...] = ()
    exceptions: tuple[TrustException, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return _clean(self)


@dataclass(frozen=True)
class SecurityScanSafetySummary:
    read_only: bool = True
    network_calls: bool = False
    scanner_execution: bool = False
    github_api_calls: bool = False
    credentials_read: bool = False
    raw_payloads_stored: bool = False
    raw_html_stored: bool = False
    exploit_payloads_stored: bool = False
    client_data_present: bool = False
    fail_closed: bool = True

    def __post_init__(self) -> None:
        if not self.read_only or any((self.network_calls, self.scanner_execution, self.github_api_calls, self.credentials_read, self.raw_payloads_stored, self.raw_html_stored, self.exploit_payloads_stored, self.client_data_present)):
            raise ValueError("security scanner adapter must remain offline and safe")

    def to_dict(self) -> dict[str, Any]:
        return _clean(self)


@dataclass(frozen=True)
class SecurityScannerAdapterReport:
    report_version: str
    generated_at: str
    scanner_references: tuple[SecurityScannerReference, ...]
    fixtures: tuple[SecurityScannerFixture, ...]
    findings: tuple[SecurityScanFinding, ...]
    summaries: tuple[SecurityScanSummary, ...]
    control_coverage: tuple[SecurityControlCoverage, ...]
    evidence_records: tuple[TrustEvidenceRecord, ...]
    risk_items: tuple[TrustRiskItem, ...]
    gate_impacts: tuple[SecurityGateImpact, ...]
    ingestion_results: tuple[SecurityScanIngestionResult, ...]
    redaction_policy: SecurityScanRedactionPolicy
    normalization_rules: tuple[SecurityScanNormalizationRule, ...]
    public_launch_security_decision: str
    provider_activation_security_decision: str
    ai_agent_activation_security_decision: str
    recommended_next_scanners: tuple[str, ...]
    scanner_integration_roadmap: tuple[dict[str, Any], ...]
    safety_summary: SecurityScanSafetySummary
    next_best_action: str
    rejected_count: int = 0
    redacted_count: int = 0
    trustos_gate_results: tuple[TrustGateResult, ...] = ()
    exceptions: tuple[TrustException, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        data = _clean(self)
        data.update({
            "scanner_count": len(self.scanner_references),
            "fixture_count": len(self.fixtures),
            "finding_count": len(self.findings),
            "critical_count": sum(item.severity == "critical" for item in self.findings),
            "high_count": sum(item.severity == "high" for item in self.findings),
            "medium_count": sum(item.severity == "medium" for item in self.findings),
            "low_count": sum(item.severity == "low" for item in self.findings),
        })
        return data

    def to_markdown(self) -> str:
        data = self.to_dict()
        lines = ["# Security Scanner Evidence Adapter", "", "## Executive Summary", "", f"- Scanners referenced: **{data['scanner_count']}**", f"- Fixtures normalized: **{data['fixture_count']}**", f"- Findings: **{data['finding_count']}**", f"- Critical/high: **{data['critical_count']}/{data['high_count']}**", f"- Public launch security: **{self.public_launch_security_decision}**", f"- Provider activation security: **{self.provider_activation_security_decision}**", f"- AI agent activation security: **{self.ai_agent_activation_security_decision}**", "- Mode: **fixture normalization only**", "", "## Scanner Coverage", "", "| Scanner | Mode | Formats | CI Later |", "|---|---|---|---|"]
        lines += [f"| {item.name} | {item.integration_mode} | {', '.join(item.output_formats)} | {item.safe_to_run_in_ci_later} |" for item in self.scanner_references]
        lines += ["", "## Findings Summary", "", "| Scanner | Severity | Category | Summary |", "|---|---|---|---|"]
        lines += [f"| {item.scanner_id} | {item.severity} | {item.category} | {item.summary} |" for item in self.findings]
        lines += ["", "## Redactions and Rejections", "", f"- Redacted: **{self.redacted_count}**", f"- Rejected: **{self.rejected_count}**", f"- Policy: **{self.redaction_policy.policy_id}**", "", "## TrustOS Evidence Mapping", "", f"- Evidence records: **{len(self.evidence_records)}**", f"- Risk items: **{len(self.risk_items)}**", f"- Control coverage rows: **{len(self.control_coverage)}**", "", "## Gate Impacts", "", "| Action | Decision | Severity | Next action |", "|---|---|---|---|"]
        lines += [f"| {item.action} | {item.decision} | {item.severity} | {item.next_action} |" for item in self.gate_impacts]
        lines += ["", "## Public Launch Security Decision", "", self.public_launch_security_decision, "", "## AI Agent Security Decision", "", self.ai_agent_activation_security_decision, "", "## Provider Activation Decision", "", self.provider_activation_security_decision, "", "## Recommended Scanner Roadmap", ""] + [f"- {item}" for item in self.recommended_next_scanners] + ["", "## Safety Boundaries", "", "No scanner, GitHub API, external service, credential, network, raw payload, HTML, exploit payload, or mutation occurred.", ""]
        return "\n".join(lines)


def _scanner_name(scanner_id: str) -> str:
    return {"gitleaks": "Gitleaks", "trufflehog": "TruffleHog", "github_secret_scanning": "GitHub Secret Scanning", "codeql_sarif": "CodeQL SARIF", "semgrep_json": "Semgrep JSON", "semgrep_sarif": "Semgrep SARIF", "osv_scanner": "OSV-Scanner", "trivy": "Trivy", "syft_sbom": "Syft SBOM", "grype": "Grype", "openssf_scorecard": "OpenSSF Scorecard", "owasp_dependency_check": "OWASP Dependency-Check", "zap_baseline": "ZAP Baseline", "nuclei": "Nuclei", "pyr_it": "PyRIT", "garak": "garak", "manual_security_review": "Manual Security Review"}.get(scanner_id, scanner_id)


def build_scanner_references() -> tuple[SecurityScannerReference, ...]:
    category_map = {"gitleaks": "secret_exposure", "trufflehog": "secret_exposure", "github_secret_scanning": "secret_exposure", "codeql_sarif": "code_vulnerability", "semgrep_json": "code_vulnerability", "semgrep_sarif": "code_vulnerability", "osv_scanner": "dependency_vulnerability", "trivy": "dependency_vulnerability", "syft_sbom": "sbom_inventory", "grype": "dependency_vulnerability", "openssf_scorecard": "repo_posture", "owasp_dependency_check": "dependency_vulnerability", "zap_baseline": "web_app_security", "nuclei": "web_app_security", "pyr_it": "ai_prompt_injection", "garak": "ai_prompt_injection", "manual_security_review": "manual_review"}
    formats = {"codeql_sarif": ("sarif",), "semgrep_sarif": ("sarif",), "semgrep_json": ("json",), "syft_sbom": ("json", "spdx", "cyclonedx"), "github_secret_scanning": ("json",), "manual_security_review": ("json", "csv")}
    refs = []
    for scanner_id in SCANNER_IDS:
        category = category_map[scanner_id]
        refs.append(SecurityScannerReference(scanner_id, _scanner_name(scanner_id), category, "normalize_fixture_now", "Review license and terms before CI integration.", f"Normalize {category.replace('_', ' ')} evidence into TrustOS.", formats.get(scanner_id, ("json",)), (f"control-security_baseline-{category.replace('secret_exposure', 'secret_scan').replace('dependency_vulnerability', 'dependency_scan').replace('code_vulnerability', 'code_scan').replace('sbom_inventory', 'sbom').replace('repo_posture', 'trust_scorecard').replace('web_app_security', 'security_evidence').replace('ai_prompt_injection', 'prompt_injection').replace('manual_review', 'security_packet')}",), "hard_block" if category in {"secret_exposure", "ai_prompt_injection"} else "warn", "normalize_fixture_only", False, False, True))
    return tuple(refs)


def parse_security_fixture(payload: Mapping[str, Any], *, scanner_id: str, source_file: str = "fixture://security-scanner") -> SecurityScanIngestionResult:
    if scanner_id not in SCANNER_IDS:
        raise ValueError(f"unsupported scanner: {scanner_id}")
    if not isinstance(payload, Mapping) or payload.get("fixture_mode") is not True:
        raise ValueError("scanner fixtures must explicitly set fixture_mode=true")
    if _secret_like(payload):
        raise ValueError("secret-like, raw HTML, or exploit-like scanner output is rejected")
    rows = _items(payload, scanner_id)
    findings: list[SecurityScanFinding] = []
    risks: list[TrustRiskItem] = []
    evidence: list[TrustEvidenceRecord] = []
    impacts: list[SecurityGateImpact] = []
    for index, item in enumerate(rows, 1):
        category = _category(scanner_id, item)
        severity = _severity(item.get("severity", item.get("level")))
        title = _clean_text(item.get("title", item.get("rule", item.get("name", f"Synthetic {_scanner_name(scanner_id)} finding"))))
        summary = _clean_text(item.get("summary", item.get("message", item.get("description", "Synthetic normalized scanner finding."))))
        finding_id = _clean_text(item.get("id", item.get("rule_id", f"{scanner_id}-finding-{index}")), f"{scanner_id}-finding-{index}", 100)
        rule_id = _clean_text(item.get("rule_id", item.get("check", "synthetic-rule")), "synthetic-rule", 100)
        location = "TBD" if not item.get("location_placeholder") else _clean_text(item.get("location_placeholder"), "TBD", 120)
        package = "TBD" if not item.get("package_placeholder") else _clean_text(item.get("package_placeholder"), "TBD", 120)
        status = "failed" if severity in {"critical", "high"} else "requires_review" if severity == "unknown" or category == "manual_review" else "draft"
        finding = SecurityScanFinding(finding_id, scanner_id, category, severity, title, summary, rule_id, location, package, status, "safe_summary_only", f"fixture://{scanner_id}")
        findings.append(finding)
        control = {"secret_exposure": "control-security_baseline-secret_scan", "dependency_vulnerability": "control-security_baseline-dependency_scan", "code_vulnerability": "control-security_baseline-code_scan", "supply_chain": "control-security_baseline-supply_chain", "sbom_inventory": "control-security_baseline-sbom", "repo_posture": "control-public_launch_readiness-trust_scorecard", "web_app_security": "control-public_launch_readiness-security_evidence", "api_security": "control-public_launch_readiness-security_evidence", "ai_prompt_injection": "control-ai_agent_security-prompt_injection", "ai_tool_hijack": "control-ai_agent_security-tool_hijack", "ai_secret_exfiltration": "control-ai_agent_security-secret_exfiltration", "ai_model_spend_abuse": "control-ai_agent_security-model_spend", "ai_approval_bypass": "control-ai_agent_security-approval_bypass", "manual_review": "control-client_trustos_service-security_packet"}[category]
        evidence.append(TrustEvidenceRecord(f"evidence-{finding_id}", control, "security_scanner_fixture", f"fixture://{scanner_id}", summary, "risk_approval", "offline-deterministic", "TBD", status, "safe_summary_only", True, False, category in {"secret_exposure", "ai_secret_exfiltration"}, "Raw scanner output is not retained."))
        risks.append(TrustRiskItem(f"risk-{finding_id}", "ai_governance" if category.startswith("ai_") else "security", title, summary, "medium" if severity in {"low", "info", "unknown"} else "high", severity, "Review normalized evidence with the security owner before gated action.", "risk_approval", "open", category in {"secret_exposure", "ai_prompt_injection", "ai_approval_bypass", "manual_review"}))
        impacts.extend(_impacts(finding))
    counts = {severity: sum(item.severity == severity for item in findings) for severity in SEVERITIES}
    summary = SecurityScanSummary(scanner_id, "parsed" if rows or payload.get("fixture_mode") else "empty", len(findings), counts["critical"], counts["high"], counts["medium"], counts["low"], counts["info"], 0, 0, ("Synthetic fixture; not proof of a live scan.",))
    fixture = SecurityScannerFixture(str(payload.get("fixture_id", f"{scanner_id}-fixture")), scanner_id, source_file, True, len(rows), "valid", False)
    merged_impacts = tuple(_merge_impacts(impacts))
    gate_results = tuple(TrustGateResult(f"gate-result-{item.action}-{scanner_id}", item.action, "needs_professional_review" if item.decision == "needs_security_owner" else item.decision, (item.reason,), (), (), ("security_owner",) if item.decision in {"hard_block", "soft_block", "needs_security_owner"} else (), "Assign security-owner review before proceeding.", "offline-deterministic", True) for item in merged_impacts)
    exceptions = tuple(TrustException(f"exception-{item.action}-{scanner_id}", "control-public_launch_readiness-security_evidence", item.action, "requires_security_owner" if item.decision == "needs_security_owner" else "requested", "security-scanner-adapter", "security_owner", item.reason, "TBD", item.finding_ids) for item in merged_impacts if item.decision in {"hard_block", "soft_block", "needs_security_owner"})
    return SecurityScanIngestionResult(scanner_id, "parsed", tuple(findings), summary, tuple(evidence), tuple(risks), merged_impacts, "", gate_results, exceptions)


def _impacts(finding: SecurityScanFinding) -> list[SecurityGateImpact]:
    category, severity, fid = finding.category, finding.severity, finding.finding_id
    impacts: list[SecurityGateImpact] = []
    if category == "secret_exposure":
        decision = "hard_block" if severity in {"critical", "high"} else "warn"
        for action in ("public_beta_launch", "activate_provider", "use_credentials"):
            impacts.append(SecurityGateImpact(action, decision, severity, (fid,), "Secret exposure evidence requires review before sensitive action.", "Revoke/rotate outside this adapter and complete a security-owner review."))
    elif category == "dependency_vulnerability":
        decision = "hard_block" if severity == "critical" else "soft_block" if severity == "high" else "warn"
        impacts.append(SecurityGateImpact("public_beta_launch", decision, severity, (fid,), "Dependency evidence affects public-launch security readiness.", "Review remediation or record a scoped exception."))
    elif category == "code_vulnerability":
        impacts.append(SecurityGateImpact("public_beta_launch", "hard_block" if severity in {"critical", "high"} else "warn", severity, (fid,), "Code-security evidence affects public launch.", "Review the finding with a security owner."))
    elif category in {"ai_prompt_injection", "ai_tool_hijack", "ai_secret_exfiltration", "ai_model_spend_abuse", "ai_approval_bypass"}:
        actions = ("enable_live_model_calls", "run_provider_readonly_call", "run_provider_write_call")
        if category == "ai_approval_bypass":
            actions += ("activate_provider", "publish_site", "send_outbound_email")
        for action in actions:
            impacts.append(SecurityGateImpact(action, "hard_block" if severity in {"critical", "high", "unknown"} else "warn", severity, (fid,), "AI-agent security evidence is incomplete or failed.", "Keep live tools disabled and complete the applicable TrustOS control review."))
    elif category == "manual_review":
        impacts.append(SecurityGateImpact("public_beta_launch", "needs_security_owner", severity, (fid,), "Manual security review is incomplete.", "Assign a security owner and record review evidence."))
    elif category == "sbom_inventory":
        impacts.append(SecurityGateImpact("public_beta_launch", "warn", severity, (fid,), "SBOM inventory is represented as planned evidence.", "Produce and review an approved SBOM later."))
    elif category == "repo_posture" and severity == "low":
        impacts.append(SecurityGateImpact("public_beta_launch", "warn", severity, (fid,), "Repository posture score is below the planning threshold.", "Review repository hardening controls."))
    elif category in {"web_app_security", "api_security", "misconfiguration", "supply_chain"}:
        impacts.append(SecurityGateImpact("public_beta_launch", "hard_block" if severity in {"critical", "high"} else "warn", severity, (fid,), "Security posture evidence affects public launch.", "Complete security-owner review before launch."))
    return impacts


def _merge_impacts(items: Sequence[SecurityGateImpact]) -> tuple[SecurityGateImpact, ...]:
    grouped: dict[str, list[SecurityGateImpact]] = {}
    rank = {"hard_block": 5, "soft_block": 4, "needs_security_owner": 3, "warn": 2, "allow": 1}
    for item in items:
        grouped.setdefault(item.action, []).append(item)
    result = []
    for action, rows in sorted(grouped.items()):
        strongest = max(rows, key=lambda row: rank.get(row.decision, 0))
        result.append(SecurityGateImpact(action, strongest.decision, max((row.severity for row in rows), key=lambda value: SEVERITIES.index(value)), tuple(fid for row in rows for fid in row.finding_ids), strongest.reason, strongest.next_action))
    return tuple(result)


def _default_payload(scanner_id: str) -> dict[str, Any]:
    if scanner_id == "syft_sbom":
        return {"fixture_id": "syft-synthetic", "fixture_mode": True, "packages": [{"id": "pkg-1", "name": "synthetic-package", "version": "0.0.0"}]}
    if scanner_id == "openssf_scorecard":
        return {"fixture_id": "scorecard-synthetic", "fixture_mode": True, "score": 6.5}
    if scanner_id == "manual_security_review":
        return {"fixture_id": "manual-review-synthetic", "fixture_mode": True, "checks": [{"id": "review-1", "title": "Synthetic manual review pending", "status": "requires_review", "severity": "unknown"}]}
    category = "secret_exposure" if scanner_id in {"gitleaks", "trufflehog", "github_secret_scanning"} else "dependency_vulnerability" if scanner_id in {"osv_scanner", "trivy", "grype", "owasp_dependency_check"} else "ai_prompt_injection" if scanner_id in {"pyr_it", "garak"} else "code_vulnerability" if scanner_id in {"codeql_sarif", "semgrep_json", "semgrep_sarif"} else "web_app_security" if scanner_id in {"zap_baseline", "nuclei"} else "repo_posture"
    return {"fixture_id": f"{scanner_id}-synthetic", "fixture_mode": True, "findings": [{"id": f"{scanner_id}-synthetic-1", "category": category, "severity": "info" if category not in {"secret_exposure", "ai_prompt_injection"} else "low", "title": f"Synthetic {_scanner_name(scanner_id)} finding", "summary": "Synthetic summary only; detailed scanner content is not retained."}]}


def build_security_scanner_report(*, generated_at: str = "offline-deterministic", scanner: str | None = None, payload: Mapping[str, Any] | None = None, source_file: str = "fixture://security-scanner-default", action: str | None = None, run_local_scanner: bool = False) -> SecurityScannerAdapterReport:
    if run_local_scanner:
        raise ValueError("run-local-scanner is blocked; v1 only normalizes fixture/output metadata")
    selected = (scanner,) if scanner else SCANNER_IDS
    if any(item not in SCANNER_IDS for item in selected):
        raise ValueError("unsupported scanner")
    references = tuple(item for item in build_scanner_references() if item.scanner_id in selected)
    ingestion: list[SecurityScanIngestionResult] = []
    fixtures: list[SecurityScannerFixture] = []
    for scanner_id in selected:
        parsed = parse_security_fixture(payload if payload is not None and scanner_id == (scanner or scanner_id) else _default_payload(scanner_id), scanner_id=scanner_id, source_file=source_file if payload is not None and scanner_id == (scanner or scanner_id) else f"fixture://{scanner_id}")
        ingestion.append(parsed)
        fixtures.append(SecurityScannerFixture(f"{scanner_id}-fixture", scanner_id, source_file, True, len(parsed.findings), "valid", False))
    findings = tuple(item for result in ingestion for item in result.findings)
    evidence = tuple(item for result in ingestion for item in result.evidence_records)
    risks = tuple(item for result in ingestion for item in result.risk_items)
    impacts = _merge_impacts(tuple(item for result in ingestion for item in result.gate_impacts))
    if action:
        if action not in GATE_ACTIONS:
            raise ValueError(f"unsupported TrustOS action: {action}")
        base = evaluate_action(action) if action in {"publish_site", "activate_provider", "use_credentials", "send_customer_message", "send_outbound_email", "launch_ad", "create_order", "create_payment", "sync_accounting", "collect_personal_data", "process_uploaded_file", "enable_public_signup", "enable_live_model_calls", "run_provider_readonly_call", "run_provider_write_call", "public_beta_launch", "client_workspace_export"} else None
        if (base is None or base.decision == "hard_block") and not any(item.action == action and item.decision == "hard_block" for item in impacts):
            impacts = _merge_impacts((*impacts, SecurityGateImpact(action, "hard_block", "high", (), "TrustOS prerequisites are missing in offline mode.", "Complete the TrustOS evidence and approval checklist.")))
    critical = any(item.action == "public_beta_launch" and item.decision == "hard_block" for item in impacts)
    provider_block = any(item.action in {"activate_provider", "use_credentials"} and item.decision == "hard_block" for item in impacts)
    ai_block = any(item.action in {"enable_live_model_calls", "run_provider_readonly_call", "run_provider_write_call"} and item.decision == "hard_block" for item in impacts)
    controls = build_trust_controls()
    coverage = tuple(SecurityControlCoverage(control.control_id, tuple(sorted({item.scanner_id for item in findings if control.control_id in {f"control-security_baseline-{key}" for key in ("secret_scan", "dependency_scan", "code_scan", "supply_chain", "sbom")} or control.control_id.endswith("security_evidence") or control.control_id.endswith("prompt_injection")})), sum(1 for item in evidence if item.control_id == control.control_id), "covered" if any(item.control_id == control.control_id for item in evidence) else "planned", not any(item.control_id == control.control_id for item in evidence)) for control in controls if control.category in {"security_baseline", "ai_agent_security", "public_launch_readiness", "client_trustos_service"})
    rules = tuple(SecurityScanNormalizationRule(f"normalize-{field}", field, field, "Copy bounded metadata only; truncate text and discard raw response shape.") for field in ("severity", "category", "title", "summary", "rule_id", "location_placeholder", "package_placeholder"))
    policy = SecurityScanRedactionPolicy("security-scanner-redaction-v1", tuple(sorted(SECRET_KEYS)), ("raw_html", "exploit_payload", "vulnerable_code"), "Reject unsafe fixtures; emit safe summaries only.", True)
    roadmap = tuple({"scanner_id": item.scanner_id, "next_mode": "run_ci_later" if item.safe_to_run_in_ci_later else "study_later", "activation_gate": "TrustOS security evidence and security-owner review"} for item in references)
    summaries = tuple(result.summary for result in ingestion)
    gate_results = tuple(item for result in ingestion for item in result.trustos_gate_results)
    exceptions = tuple(item for result in ingestion for item in result.exceptions)
    return SecurityScannerAdapterReport("security-scanner-evidence-adapter-v1", generated_at, references, tuple(fixtures), findings, summaries, coverage, evidence, risks, impacts, tuple(ingestion), policy, rules, "hard_block" if critical else "warn", "hard_block" if provider_block else "warn", "hard_block" if ai_block else "warn", ("gitleaks", "osv_scanner", "syft_sbom", "codeql_sarif", "pyr_it", "manual_security_review"), roadmap, SecurityScanSafetySummary(), "Keep scanner execution disabled; normalize approved fixture/output evidence and assign a security owner before future CI integration.", 0, 0, gate_results, exceptions)


__all__ = ["SCANNER_IDS", "CATEGORIES", "SEVERITIES", "INTEGRATION_MODES", "GATE_ACTIONS", "REDACTION_OUTCOMES", "SecurityScannerAdapterReport", "SecurityScannerReference", "SecurityScannerOutputContract", "SecurityScannerFixture", "SecurityScanFinding", "SecurityScanSummary", "SecurityFindingSeverity", "SecurityFindingCategory", "SecurityEvidenceMapping", "SecurityControlCoverage", "SecurityGateImpact", "SecurityScanNormalizationRule", "SecurityScanRedactionPolicy", "SecurityScanIngestionResult", "SecurityScanSafetySummary", "parse_security_fixture", "build_scanner_references", "build_security_scanner_report"]
