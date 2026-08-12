"""Client-safe TrustOps projections with strict internal/external separation."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from .control_plane import TrustEvidenceRecord, TrustRiskItem, _clean


@dataclass(frozen=True)
class ClientSafeControl:
    control_id: str
    name: str
    status: str
    blocker: str
    next_action: str

    def to_dict(self) -> dict[str, Any]:
        return _clean(self)


@dataclass(frozen=True)
class ClientSafeEvidenceChecklist:
    items: tuple[dict[str, Any], ...]
    client_visible_only: bool = True

    def to_dict(self) -> dict[str, Any]:
        return _clean(self)


@dataclass(frozen=True)
class ClientSafeRiskRegister:
    items: tuple[dict[str, Any], ...]
    professional_review_note: str

    def to_dict(self) -> dict[str, Any]:
        return _clean(self)


@dataclass(frozen=True)
class LawyerReadyPacket:
    title: str
    requested_review: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    disclaimers: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return _clean(self)


@dataclass(frozen=True)
class AccountantReadyPacket:
    title: str
    requested_review: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    disclaimers: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return _clean(self)


@dataclass(frozen=True)
class SecurityReviewerPacket:
    title: str
    requested_review: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    disclaimers: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return _clean(self)


@dataclass(frozen=True)
class InternalTrustOpsNotes:
    notes: tuple[str, ...]
    excluded_from_client_export: bool = True

    def to_dict(self) -> dict[str, Any]:
        return _clean(self)


@dataclass(frozen=True)
class ExternalTrustOpsSummary:
    status: str
    blockers: tuple[str, ...]
    evidence_required: tuple[str, ...]
    approvals_required: tuple[str, ...]
    next_actions: tuple[str, ...]
    export_packet: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return _clean(self)


@dataclass(frozen=True)
class ClientTrustOpsReport:
    report_version: str
    generated_at: str
    client_id: str
    controls: tuple[ClientSafeControl, ...]
    evidence_checklist: ClientSafeEvidenceChecklist
    risk_register: ClientSafeRiskRegister
    lawyer_packet: LawyerReadyPacket
    accountant_packet: AccountantReadyPacket
    security_packet: SecurityReviewerPacket
    internal_notes: InternalTrustOpsNotes
    external_summary: ExternalTrustOpsSummary
    safety_summary: dict[str, Any]

    def to_dict(self, *, client_safe: bool = False) -> dict[str, Any]:
        data = _clean(self)
        if client_safe:
            data.pop("internal_notes", None)
        return data

    def to_markdown(self, *, client_safe: bool = False) -> str:
        lines = ["# Client TrustOps Readiness Report", "", "## External Summary", "", f"- Status: **{self.external_summary.status}**", "", "### Blockers"]
        lines += [f"- {item}" for item in self.external_summary.blockers] + ["", "### Evidence Required"] + [f"- {item}" for item in self.external_summary.evidence_required] + ["", "### Approvals Required"] + [f"- {item}" for item in self.external_summary.approvals_required] + ["", "### Next Actions"] + [f"- {item}" for item in self.external_summary.next_actions] + ["", "## Professional Review Packets", "", f"- Lawyer-ready: {len(self.lawyer_packet.requested_review)} review items", f"- Accountant-ready: {len(self.accountant_packet.requested_review)} review items", f"- Security reviewer: {len(self.security_packet.requested_review)} review items", "", "## Safety Boundaries", "", "This is a readiness checklist, not legal, tax, security, or compliance advice."]
        if not client_safe:
            lines += ["", "## Internal TrustOps Notes", ""] + [f"- {note}" for note in self.internal_notes.notes]
        return "\n".join(lines) + "\n"


def build_client_trustos_report(*, generated_at: str = "offline-deterministic", client_id: str = "client-placeholder", evidence: Sequence[TrustEvidenceRecord] = (), risks: Sequence[TrustRiskItem] = ()) -> ClientTrustOpsReport:
    safe_evidence = tuple(item for item in evidence if item.client_visible and not item.internal_only)
    controls = tuple(ClientSafeControl(item.control_id, item.control_id.replace("-", " ").title(), "ready" if item.status in {"present", "passed", "not_applicable"} else "blocked", "Evidence required" if item.status not in {"present", "passed", "not_applicable"} else "", "Review or provide the referenced evidence.") for item in safe_evidence)
    checklist = ClientSafeEvidenceChecklist(tuple({"evidence_id": item.evidence_id, "control_id": item.control_id, "summary": item.summary, "status": item.status, "professional_review_required": item.professional_review_required} for item in safe_evidence))
    safe_risks = tuple({"risk_id": item.risk_id, "domain": item.domain, "title": item.title, "status": item.status, "mitigation": item.mitigation} for item in risks)
    risk_register = ClientSafeRiskRegister(safe_risks, "Ask the appropriate professional to review applicable legal, tax, privacy, or security matters.")
    lawyer = LawyerReadyPacket("Lawyer-ready TrustOS packet", ("privacy policy", "terms of service", "data processing/vendor terms", "public launch claims"), tuple(item.evidence_id for item in safe_evidence if item.professional_review_required), ("No legal conclusion is provided.",))
    accountant = AccountantReadyPacket("Accountant-ready TrustOS packet", ("tax jurisdiction classification", "invoice requirements", "CFDI/VAT/GST/HST review", "financial controls"), tuple(item.evidence_id for item in safe_evidence if item.control_id in {"tax-review", "financial_controls"}), ("No tax advice or filing is provided.",))
    security = SecurityReviewerPacket("Security reviewer TrustOS packet", ("secret/dependency/code scan results", "incident response contact", "rate limiting", "AI tool boundary tests"), tuple(item.evidence_id for item in safe_evidence if item.control_id == "security-scan"), ("No scan was run by this report.",))
    blockers = tuple(item.summary for item in safe_evidence if item.status in {"missing", "draft", "requires_review"})
    external = ExternalTrustOpsSummary("blocked_pending_review", blockers, tuple(item.summary for item in safe_evidence if item.status != "present"), ("human approval", "professional review where applicable"), ("assign evidence owners", "review blockers", "update the readiness report"), ("lawyer_ready_packet", "accountant_ready_packet", "security_reviewer_packet"))
    internal = InternalTrustOpsNotes(("Internal prompts, scoring formulas, provider heuristics, source code, and cross-client learnings are excluded.", "Use the Approval Ledger for all future external actions."))
    return ClientTrustOpsReport("trustos-client-report-v1", generated_at, client_id, controls, checklist, risk_register, lawyer, accountant, security, internal, external, {"read_only": True, "network_calls": False, "client_data_present": False, "internal_notes_excluded": True})


__all__ = ["ClientTrustOpsReport", "ClientSafeControl", "ClientSafeEvidenceChecklist", "ClientSafeRiskRegister", "LawyerReadyPacket", "AccountantReadyPacket", "SecurityReviewerPacket", "InternalTrustOpsNotes", "ExternalTrustOpsSummary", "build_client_trustos_report"]
