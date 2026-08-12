"""Public launch readiness projections over TrustOS gates."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .control_plane import _clean, build_default_evidence, build_trust_controls
from .gate_runner import evaluate_action

DECISIONS = ("go_for_internal_dry_run", "go_for_private_beta", "blocked_for_public_beta", "blocked_for_live_provider_activation", "blocked_for_customer_facing_launch", "needs_professional_review")
AREAS = ("security", "privacy", "legal", "tax", "ai_governance", "provider_activation", "credential_safety", "approval_controls", "client_workspace_isolation", "incident_response", "financial_controls")


@dataclass(frozen=True)
class LaunchReadinessArea:
    area_id: str
    name: str
    status: str
    score: float
    blockers: tuple[str, ...]
    required_evidence: tuple[str, ...]
    owner_department: str
    professional_review_required: bool

    def to_dict(self) -> dict[str, Any]:
        return _clean(self)


@dataclass(frozen=True)
class LaunchBlocker:
    blocker_id: str
    area_id: str
    message: str
    severity: str
    next_action: str

    def to_dict(self) -> dict[str, Any]:
        return _clean(self)


@dataclass(frozen=True)
class LaunchWarning:
    warning_id: str
    area_id: str
    message: str
    next_action: str

    def to_dict(self) -> dict[str, Any]:
        return _clean(self)


@dataclass(frozen=True)
class LaunchRequiredEvidence:
    evidence_id: str
    area_id: str
    description: str
    status: str
    owner: str
    professional_review_required: bool

    def to_dict(self) -> dict[str, Any]:
        return _clean(self)


@dataclass(frozen=True)
class LaunchException:
    exception_id: str
    area_id: str
    review_role: str
    status: str
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return _clean(self)


@dataclass(frozen=True)
class LaunchReadinessScore:
    score: float
    grade: str
    areas_scored: int
    hard_blockers: int
    professional_review_areas: int
    assumptions: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return _clean(self)


@dataclass(frozen=True)
class LaunchGoNoGoDecision:
    decision: str
    rationale: str
    blocking_areas: tuple[str, ...]
    next_best_action: str

    def __post_init__(self) -> None:
        if self.decision not in DECISIONS:
            raise ValueError(f"unsupported launch decision: {self.decision}")

    def to_dict(self) -> dict[str, Any]:
        return _clean(self)


@dataclass(frozen=True)
class PublicLaunchReadinessReport:
    report_version: str
    generated_at: str
    areas: tuple[LaunchReadinessArea, ...]
    blockers: tuple[LaunchBlocker, ...]
    warnings: tuple[LaunchWarning, ...]
    required_evidence: tuple[LaunchRequiredEvidence, ...]
    exceptions: tuple[LaunchException, ...]
    score: LaunchReadinessScore
    decision: LaunchGoNoGoDecision
    safety_summary: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return _clean(self)

    def to_markdown(self) -> str:
        lines = ["# Public Launch Readiness", "", "## Decision", "", f"- Decision: **{self.decision.decision}**", f"- Score: **{self.score.score:.1f}/100 ({self.score.grade})**", f"- Rationale: {self.decision.rationale}", "", "## Areas", "", "| Area | Status | Score | Blockers |", "|---|---|---:|---:|"]
        lines += [f"| {area.name} | {area.status} | {area.score:.1f} | {len(area.blockers)} |" for area in self.areas]
        lines += ["", "## Blockers", ""] + [f"- {item.message} — {item.next_action}" for item in self.blockers] + ["", "## Required Evidence", ""] + [f"- {item.area_id}: {item.description} ({item.status})" for item in self.required_evidence] + ["", "## Safety Boundaries", "", "No scan, provider call, credential read, legal conclusion, tax conclusion, or launch action occurred.", ""]
        return "\n".join(lines)


def build_public_launch_readiness(*, generated_at: str = "offline-deterministic", context: Mapping[str, Any] | None = None) -> PublicLaunchReadinessReport:
    ctx = dict(context or {})
    gate = evaluate_action("public_beta_launch", context=ctx, generated_at=generated_at)
    area_specs = {
        "security": ("Security", ("security_evidence_present", "secret_scan_clean", "dependency_scan_clean"), "security", False),
        "privacy": ("Privacy", ("privacy_review_complete",), "risk_approval", True),
        "legal": ("Legal", ("lawyer_review", "policies_present"), "risk_approval", True),
        "tax": ("Tax", ("accounting_review",), "accounting", True),
        "ai_governance": ("AI Governance", ("model_spend_controls",), "risk_approval", True),
        "provider_activation": ("Provider Activation", ("provider_registered", "credential_reference_exists", "approval_recorded", "terms_review_complete", "privacy_review_complete"), "intelligence", False),
        "credential_safety": ("Credential Safety", ("credential_reference_exists",), "risk_approval", False),
        "approval_controls": ("Approval Controls", ("approval_recorded",), "risk_approval", False),
        "client_workspace_isolation": ("Client Workspace Isolation", ("client_isolated", "internal_notes_excluded"), "risk_approval", False),
        "incident_response": ("Incident Response", ("incident_response_present",), "operations", False),
        "financial_controls": ("Financial Controls", ("accounting_review",), "finance", True),
    }
    areas: list[LaunchReadinessArea] = []
    blockers: list[LaunchBlocker] = []
    required: list[LaunchRequiredEvidence] = []
    for area_id, (name, keys, owner, professional) in area_specs.items():
        missing = tuple(key for key in keys if not ctx.get(key, False))
        score = round((len(keys) - len(missing)) / max(1, len(keys)) * 100, 1)
        status = "ready" if not missing else "needs_professional_review" if professional else "blocked"
        areas.append(LaunchReadinessArea(area_id, name, status, score, tuple(f"{key} required" for key in missing), tuple(f"{key}_evidence" for key in keys), owner, professional))
        for key in keys:
            required.append(LaunchRequiredEvidence(f"evidence-{area_id}-{key}", area_id, f"Evidence for {key.replace('_', ' ')}", "present" if ctx.get(key, False) else "missing", owner, professional))
        for key in missing:
            blockers.append(LaunchBlocker(f"blocker-{area_id}-{key}", area_id, f"{name}: {key.replace('_', ' ')} is missing", "high" if not professional else "professional_review", f"Obtain {key.replace('_', ' ')} evidence or review."))
    warnings = (LaunchWarning("warning-offline", "provider_activation", "All provider and scanner checks are metadata-only.", "Keep live activation disabled."), LaunchWarning("warning-assumptions", "tax", "TrustOS is not legal or tax advice.", "Ask the appropriate professional to review."))
    hard = len(blockers)
    score = round(sum(area.score for area in areas) / len(areas), 1)
    grade = "A" if score >= 90 else "B" if score >= 75 else "C" if score >= 60 else "D"
    readiness_score = LaunchReadinessScore(score, grade, len(areas), hard, sum(area.professional_review_required for area in areas if area.status != "ready"), ("No live scans or provider calls were made.",))
    decision = LaunchGoNoGoDecision("blocked_for_public_beta", "Public launch requires reviewed security, privacy, legal, tax, AI-governance, approval, and isolation evidence.", tuple(sorted({item.area_id for item in blockers})), "Complete the missing evidence checklist with security, legal, privacy, tax, and operations owners.")
    exceptions = tuple(LaunchException(f"exception-{area.area_id}", area.area_id, "lawyer" if area.area_id in {"privacy", "legal"} else "accountant" if area.area_id in {"tax", "financial_controls"} else "security_owner", "requested" if area.professional_review_required else "none", "Professional review placeholder; no conclusion is made.") for area in areas if area.professional_review_required)
    return PublicLaunchReadinessReport("trustos-public-launch-v1", generated_at, tuple(areas), tuple(blockers), warnings, tuple(required), exceptions, readiness_score, decision, {"read_only": True, "network_calls": False, "scanner_runs": False, "live_launch": False})


__all__ = ["DECISIONS", "AREAS", "PublicLaunchReadinessReport", "LaunchReadinessArea", "LaunchBlocker", "LaunchWarning", "LaunchRequiredEvidence", "LaunchException", "LaunchReadinessScore", "LaunchGoNoGoDecision", "build_public_launch_readiness"]
