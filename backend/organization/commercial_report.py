from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass
class CommercialReport:
    report_id: str
    workspace_id: str
    proposal_id: str
    experiment_id: str
    service_name: str
    title: str
    summary: str
    findings: list[dict[str, Any]] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)
    risk_flags: list[str] = field(default_factory=list)
    next_actions: list[str] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    status: str = "blocked"
    created_at: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {key: getattr(self, key) for key in self.__dataclass_fields__}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CommercialReport":
        return cls(**{key: data[key] for key in cls.__dataclass_fields__ if key in data})

    def to_markdown(self) -> str:
        findings = "\n".join(f"- **{item.get('name', 'Finding')}**: {item.get('value')}" for item in self.findings) or "- No supported findings were produced."
        bullets = lambda values: "\n".join(f"- {value}" for value in values) or "- None recorded."
        return f"# {self.title}\n\n**Status:** `{self.status}`  \n**Service:** `{self.service_name}`  \n**Workspace:** `{self.workspace_id}`  \n**Report ID:** `{self.report_id}`\n\n## Summary\n\n{self.summary}\n\n## Findings\n\n{findings}\n\n## Recommendations\n\n{bullets(self.recommendations)}\n\n## Risk flags\n\n{bullets(self.risk_flags)}\n\n## Next actions\n\n{bullets(self.next_actions)}\n\n## Metrics\n\n```json\n{json.dumps(self.metrics, indent=2, default=str)}\n```\n"


def build_report_from_execution(proposal, execution_result, decision=None) -> CommercialReport:
    p = proposal.to_dict() if hasattr(proposal, "to_dict") else dict(proposal)
    execution = execution_result.to_dict() if hasattr(execution_result, "to_dict") else dict(execution_result or {})
    output = execution.get("output") or execution.get("result") or {}
    output = output if isinstance(output, dict) else {"value": output}
    status = "completed" if execution.get("status") == "completed" else "unavailable" if execution.get("status") == "service_module_unavailable" else "blocked"
    seed = f"{p.get('proposal_id', '')}:{execution.get('service_name', p.get('service_name', ''))}:{execution.get('status', '')}"
    report_id = f"report_{uuid.uuid5(uuid.NAMESPACE_URL, seed).hex[:16]}"
    findings = [{"name": key, "value": value} for key, value in output.items() if key not in {"next_actions", "risk_flags", "recommendation", "provenance"}]
    summary = str(output.get("summary") or ("Completed deterministic read-only analysis." if status == "completed" else f"Service execution was {status}; no commercial conclusion was produced."))
    decision_data = decision.to_dict() if hasattr(decision, "to_dict") else decision or {}
    risks = list(output.get("risk_flags") or []) + list(execution.get("blocked_reasons") or []) + list(execution.get("errors") or [])
    recommendations = [str(output["recommendation"])] if output.get("recommendation") else []
    recommendations += [str(item) for item in output.get("rationale", [])]
    return CommercialReport(report_id, str(p.get("workspace_id", "")), str(p.get("proposal_id", "")), str(execution.get("experiment_id") or ""), str(execution.get("service_name") or p.get("service_name", "")), str(p.get("title") or "Commercial analysis report"), summary, findings, recommendations, risks, [str(item) for item in output.get("next_actions", [])], {key: output[key] for key in ("demand_signal", "competition_signal", "pricing_signal", "cost_assumptions") if key in output}, status, metadata={"provenance": output.get("provenance", {}), "decision_reason": decision_data.get("reason", "")})
