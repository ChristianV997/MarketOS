"""Combined TrustOS report assembly."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .client_trustops_report import ClientTrustOpsReport, build_client_trustos_report
from .control_plane import TrustOSReport, _clean, _client_safe_scrub, build_trustos_report
from .public_launch_readiness import PublicLaunchReadinessReport, build_public_launch_readiness


@dataclass(frozen=True)
class TrustOSCombinedReport:
    report_version: str
    generated_at: str
    control_plane: TrustOSReport
    public_launch_readiness: PublicLaunchReadinessReport
    client_trustos_report: ClientTrustOpsReport
    integration_decisions: tuple[dict[str, Any], ...]
    service_package_opportunities: tuple[str, ...]
    next_best_action: str
    safety_summary: dict[str, Any]

    def to_dict(self, *, client_safe: bool = False) -> dict[str, Any]:
        data = {
            "report_version": self.report_version,
            "generated_at": self.generated_at,
            "control_count": len(self.control_plane.controls),
            "policy_pack_count": len(self.control_plane.policy_packs),
            "evidence_record_count": len(self.control_plane.evidence_records),
            "gate_count": len(self.control_plane.gates),
            "hard_blocker_count": self.control_plane.hard_blocker_count,
            "soft_blocker_count": self.control_plane.soft_blocker_count,
            "warning_count": self.control_plane.warning_count,
            "exception_count": len(self.control_plane.exceptions),
            "controls": [_clean(item) for item in self.control_plane.controls],
            "policy_packs": [_clean(item) for item in self.control_plane.policy_packs],
            "evidence_records": [_clean(item) for item in self.control_plane.evidence_records],
            "gates": [_clean(item) for item in self.control_plane.gates],
            "gate_results": [_clean(item) for item in self.control_plane.gate_results],
            "readiness_scores": [_clean(item) for item in self.control_plane.scorecards],
            "trust_scorecard": _clean(self.control_plane.scorecards[0]) if self.control_plane.scorecards else {},
            "public_launch_decision": self.public_launch_readiness.decision.decision,
            "provider_activation_decision": self.control_plane.readiness.provider_activation,
            "client_workspace_export_decision": next((item.decision for item in self.control_plane.gate_results if item.action == "client_workspace_export"), "hard_block"),
            "public_launch_readiness": _clean(self.public_launch_readiness),
            "client_trustos_report": self.client_trustos_report.to_dict(client_safe=client_safe),
            "integration_decisions": [_clean(item) for item in self.integration_decisions],
            "top_blockers": list(self.control_plane.readiness.blockers),
            "top_missing_evidence": [item.control_id for item in self.control_plane.evidence_records if item.status != "present"],
            "service_package_opportunities": list(self.service_package_opportunities),
            "next_best_action": self.next_best_action,
            "safety_summary": self.safety_summary,
        }
        if client_safe:
            data.pop("controls", None)
            data.pop("gates", None)
            data.pop("gate_results", None)
            data.pop("integration_decisions", None)
            data = _client_safe_scrub(data)
        return data

    def to_markdown(self, *, client_safe: bool = False) -> str:
        text = self.control_plane.to_markdown(client_safe=client_safe)
        text += "\n## Public Launch Readiness\n\n" + self.public_launch_readiness.to_markdown()
        text += "\n## Client-safe TrustOps Summary\n\n" + self.client_trustos_report.to_markdown(client_safe=True)
        text += "\n## Service Opportunities\n\n" + "\n".join(f"- {item}" for item in self.service_package_opportunities) + "\n"
        return text


def build_trustos_combined_report(*, generated_at: str = "offline-deterministic", context: Mapping[str, Any] | None = None, client_safe: bool = False) -> TrustOSCombinedReport:
    core = build_trustos_report(generated_at=generated_at, action_context=context)
    launch = build_public_launch_readiness(generated_at=generated_at, context=context)
    client = build_client_trustos_report(generated_at=generated_at, evidence=core.evidence_records, risks=core.risks)
    decisions = (
        {"action": "activate_provider", "decision": core.readiness.provider_activation, "reason": "Approval, credential, terms, privacy, budget, and output evidence are incomplete."},
        {"action": "public_beta_launch", "decision": launch.decision.decision, "reason": launch.decision.rationale},
        {"action": "client_workspace_export", "decision": next((item.decision for item in core.gate_results if item.action == "client_workspace_export"), "hard_block"), "reason": "Client-safe isolation and internal-note exclusion are required."},
    )
    return TrustOSCombinedReport("trustos-control-plane-v1", generated_at, core, launch, client, decisions, core.service_package_opportunities, core.next_best_action, core.safety_summary.to_dict())


__all__ = ["TrustOSCombinedReport", "build_trustos_combined_report"]
