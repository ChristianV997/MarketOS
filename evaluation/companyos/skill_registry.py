"""Curated, testable CompanyOS skills; no public skill hub ingestion."""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from typing import Any, Mapping

VERIFICATION_STATUSES = frozenset({"verified", "needs_review", "experimental", "blocked"})


@dataclass(frozen=True)
class SkillVersion:
    version: str
    changelog: str
    verified_at: str
    owner: str


@dataclass(frozen=True)
class SkillTrigger:
    phrase: str
    intent: str
    confirmation_required: bool


@dataclass(frozen=True)
class SkillScope:
    departments: tuple[str, ...]
    client_data_allowed: bool
    external_data_allowed: bool
    max_records: int


@dataclass(frozen=True)
class SkillInputContract:
    required: tuple[str, ...]
    optional: tuple[str, ...]
    provenance_required: bool


@dataclass(frozen=True)
class SkillOutputContract:
    outputs: tuple[str, ...]
    schema_version: str
    human_review: bool


@dataclass(frozen=True)
class SkillBoundary:
    forbidden_outputs: tuple[str, ...]
    forbidden_actions: tuple[str, ...]
    approval_requirements: tuple[str, ...]


@dataclass(frozen=True)
class SkillTestCase:
    test_id: str
    input_summary: str
    expected: str
    safety_assertions: tuple[str, ...]


@dataclass(frozen=True)
class SkillInstallSource:
    source_type: str
    reference: str
    trusted: bool
    network_required: bool


@dataclass(frozen=True)
class SkillVerificationStatus:
    status: str
    verified_by: str
    notes: tuple[str, ...]


@dataclass(frozen=True)
class SkillDefinition:
    skill_id: str
    name: str
    department_owner: str
    description: str
    trigger_phrases: tuple[str, ...]
    allowed_inputs: tuple[str, ...]
    required_context: tuple[str, ...]
    allowed_outputs: tuple[str, ...]
    forbidden_outputs: tuple[str, ...]
    allowed_tools: tuple[str, ...]
    forbidden_actions: tuple[str, ...]
    approval_requirements: tuple[str, ...]
    acceptance_tests: tuple[SkillTestCase, ...]
    boundary_tests: tuple[SkillTestCase, ...]
    last_verified: str
    verification_status: str
    version: SkillVersion
    scope: SkillScope
    input_contract: SkillInputContract
    output_contract: SkillOutputContract
    install_source: SkillInstallSource


@dataclass(frozen=True)
class SkillRegistryReport:
    report_version: str
    generated_at: str
    skills: tuple[SkillDefinition, ...]
    policy: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_SKILLS = (("weekly_operating_review", "weekly operating review", "management"), ("department_scorecard", "department scorecard", "management"), ("capital_allocation_plan", "capital allocation plan", "finance"), ("cash_runway_forecast", "cash runway forecast", "finance"), ("ad_budget_cap_review", "ad budget cap review", "finance"), ("transaction_categorization", "transaction categorization", "accounting"), ("ledger_reconciliation_review", "ledger reconciliation review", "accounting"), ("lead_scoring", "lead scoring", "sales"), ("cold_email_draft", "cold email draft", "sales"), ("dm_draft", "DM draft", "sales"), ("whatsapp_followup_draft", "WhatsApp follow-up draft", "sales"), ("call_script_draft", "call script draft", "sales"), ("proposal_draft", "proposal draft", "sales"), ("objection_handling", "objection handling", "sales"), ("approval_gate_review", "approval gate review", "risk_approval"), ("claim_compliance_review", "claim compliance review", "risk_approval"), ("spend_cap_review", "spend cap review", "finance"), ("model_cost_review", "model cost review", "finance"), ("site_draft_review", "site draft review", "website_store_funnel"), ("launch_draft_review", "launch draft review", "launch"), ("supplier_proof_review", "supplier proof review", "supplier"))


def _skill(item: tuple[str, str, str]) -> SkillDefinition:
    skill_id, name, department = item
    messaging = department == "sales" and any(word in skill_id for word in ("email", "dm", "whatsapp", "call"))
    tests = (SkillTestCase(f"{skill_id}-happy", "sanitized structured context", "deterministic schema-valid draft", ("no_live_action", "no_secret_leakage")),)
    boundaries = (SkillTestCase(f"{skill_id}-boundary", "request external action", "blocked or approval request", ("approval_required_when_needed", "no_live_action")),)
    return SkillDefinition(skill_id, name, department, f"Produce a bounded {name} artifact.", (f"run {name}", name), ("sanitized context", "approved reports"), ("company context", "source evidence"), ("draft output", "scorecard", "approval request"), ("guaranteed result", "unapproved claim", "live action"), ("read_file",), ("send message", "create payment", "publish", "place order", "mutate accounting platform"), ("human review",), tests, boundaries, "offline-deterministic", "verified", SkillVersion("1.0.0", "Initial curated registry", "offline-deterministic", "MarketOS"), SkillScope((department,), False, False, 100), SkillInputContract(("sanitized context",), ("source evidence",), True), SkillOutputContract(("structured draft", "warnings", "approval blockers"), "companyos-skill-v1", True), SkillInstallSource("repository", "evaluation/companyos", True, False))


def build_skill_registry(*, generated_at: str = "offline-deterministic", seed: Mapping[str, Any] | None = None) -> SkillRegistryReport:
    skills = [_skill(item) for item in _SKILLS]
    overrides = {str(item.get("skill_id")): item for item in (seed or {}).get("skills", []) if isinstance(item, Mapping)}
    normalized: list[SkillDefinition] = []
    for skill in skills:
        status = str(overrides.get(skill.skill_id, {}).get("verification_status", skill.verification_status))
        if status not in VERIFICATION_STATUSES:
            status = "needs_review"
        normalized.append(replace(skill, verification_status=status))
    return SkillRegistryReport("companyos-skill-registry-v1", generated_at, tuple(normalized), "Skills are curated in-repo, versioned, acceptance-tested, boundary-tested, and never installed from public hubs automatically.")


__all__ = ["VERIFICATION_STATUSES", "SkillDefinition", "SkillVersion", "SkillTrigger", "SkillScope", "SkillInputContract", "SkillOutputContract", "SkillBoundary", "SkillTestCase", "SkillInstallSource", "SkillVerificationStatus", "SkillRegistryReport", "build_skill_registry"]
