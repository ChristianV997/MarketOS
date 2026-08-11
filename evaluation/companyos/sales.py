"""Consent-aware, draft-only sales planning for CompanyOS."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class ICP:
    name: str
    business_type: str
    pain_points: tuple[str, ...]
    buying_triggers: tuple[str, ...]
    disqualifiers: tuple[str, ...]


@dataclass(frozen=True)
class Persona:
    name: str
    role: str
    goals: tuple[str, ...]
    objections: tuple[str, ...]


@dataclass(frozen=True)
class BuyingIntent:
    level: str
    signals: tuple[str, ...]
    evidence_mode: str


@dataclass(frozen=True)
class LeadScore:
    score: float
    grade: str
    reasons: tuple[str, ...]
    next_action: str


@dataclass(frozen=True)
class PipelineStage:
    stage_id: str
    name: str
    order: int
    exit_criteria: tuple[str, ...]


@dataclass(frozen=True)
class Lead:
    lead_id: str
    account_id: str
    name: str
    source: str
    consent_status: str
    do_not_contact: bool
    buying_intent: BuyingIntent
    score: LeadScore
    recommended_package_id: str


@dataclass(frozen=True)
class Account:
    account_id: str
    name: str
    industry: str
    country: str
    status: str


@dataclass(frozen=True)
class Contact:
    contact_id: str
    account_id: str
    display_name: str
    channel: str
    contact_value_redacted: str
    consent_status: str


@dataclass(frozen=True)
class Deal:
    deal_id: str
    account_id: str
    package_id: str
    stage: str
    value_min: float
    value_max: float
    probability: float
    next_action: str
    approval_required: bool = True


@dataclass(frozen=True)
class OutreachSequenceDraft:
    sequence_id: str
    steps: tuple[str, ...]
    channel: str
    consent_gate: str
    status: str = "draft"


@dataclass(frozen=True)
class MessageDraft:
    channel: str
    subject_or_title: str
    body: str
    status: str = "draft"
    send_authorized: bool = False
    unsubscribe_note: str = "Include opt-out handling before any approved outreach."


@dataclass(frozen=True)
class ConversationThreadDraft:
    thread_id: str
    opening_message: MessageDraft
    likely_objections: tuple[str, ...]
    handoff_trigger: str


@dataclass(frozen=True)
class CallScriptDraft:
    opening: str
    discovery_questions: tuple[str, ...]
    objection_responses: tuple[str, ...]
    next_step: str
    status: str = "draft"


@dataclass(frozen=True)
class SalesBrief:
    target_icp: ICP
    persona: Persona
    recommended_offer: str
    value_proposition: str
    proof_points: tuple[str, ...]
    risks: tuple[str, ...]


@dataclass(frozen=True)
class ObjectionHandlingCard:
    objection: str
    response: str
    evidence_required: str
    escalation: str


@dataclass(frozen=True)
class AppointmentDraft:
    appointment_id: str
    purpose: str
    proposed_windows: tuple[str, ...]
    booking_status: str = "not_booked"


@dataclass(frozen=True)
class ReminderDraft:
    reminder_id: str
    timing: str
    message: str
    status: str = "draft"


@dataclass(frozen=True)
class ProposalDraft:
    package_id: str
    scope: tuple[str, ...]
    price_band: tuple[float, float]
    assumptions: tuple[str, ...]
    approval_terms: tuple[str, ...]
    status: str = "draft"


@dataclass(frozen=True)
class HandoffPacket:
    account_id: str
    package_id: str
    approved_scope_required: bool
    delivery_owner: str
    source_evidence: tuple[str, ...]
    open_questions: tuple[str, ...]
    status: str = "draft"


@dataclass(frozen=True)
class LostReason:
    code: str
    label: str


@dataclass(frozen=True)
class ClosePlan:
    deal_id: str
    milestones: tuple[str, ...]
    blockers: tuple[str, ...]
    next_action: str


@dataclass(frozen=True)
class SalesPipelineSeed:
    icp: ICP
    leads: tuple[Lead, ...]
    accounts: tuple[Account, ...]
    contacts: tuple[Contact, ...]
    deals: tuple[Deal, ...]
    stages: tuple[PipelineStage, ...]
    brief: SalesBrief
    messages: tuple[MessageDraft, ...]
    call_script: CallScriptDraft
    proposal: ProposalDraft
    handoffs: tuple[HandoffPacket, ...]
    objections: tuple[ObjectionHandlingCard, ...]
    appointments: tuple[AppointmentDraft, ...]
    reminders: tuple[ReminderDraft, ...]
    warnings: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _score_lead(value: Mapping[str, Any]) -> LeadScore:
    intent = str(value.get("buying_intent") or "unknown").lower()
    consent = str(value.get("consent_status") or "unknown").lower()
    score = {"high": 75.0, "medium": 50.0, "low": 25.0}.get(intent, 10.0)
    reasons = [f"buying_intent={intent}"]
    if consent not in {"opt_in", "client_provided", "unknown"}:
        score -= 20
        reasons.append("consent requires review")
    if value.get("do_not_contact"):
        score = 0
        reasons.append("do_not_contact is true")
    score = round(max(0.0, min(100.0, score)), 2)
    return LeadScore(score, "A" if score >= 70 else "B" if score >= 45 else "C", tuple(reasons), "human review before any outreach" if score else "do not contact")


def build_sales_pipeline(*, context: Mapping[str, Any] | None = None, packages: Mapping[str, Any] | None = None) -> SalesPipelineSeed:
    context = context or {}
    package_id = str(context.get("recommended_package_id") or "product-opportunity-report")
    lead_input = context.get("lead", {}) if isinstance(context.get("lead", {}), Mapping) else {}
    account_id = "account-demo"; lead_id = "lead-demo"
    account = Account(account_id, str(context.get("account_name") or "Prospective client"), str(context.get("industry") or "ecommerce"), str(context.get("country") or "TBD"), "prospect")
    lead = Lead(lead_id, account_id, str(lead_input.get("name") or "Prospective buyer"), str(lead_input.get("source") or "manual_context"), str(lead_input.get("consent_status") or "unknown"), bool(lead_input.get("do_not_contact", False)), BuyingIntent(str(lead_input.get("buying_intent") or "unknown"), tuple(str(item) for item in (lead_input.get("signals") or ())), "manual_context"), _score_lead(lead_input), package_id)
    contact = Contact("contact-demo", account_id, str(lead_input.get("name") or "Prospective buyer"), str(lead_input.get("channel") or "email"), "[redacted]", lead.consent_status)
    icp = ICP(str(context.get("icp_name") or "Evidence-led ecommerce or service operator"), str(context.get("business_type") or "ecommerce_operator"), tuple(context.get("pain_points") or ("unclear next validation step", "limited delivery capacity")), tuple(context.get("buying_triggers") or ("needs a prioritized plan", "wants implementation-ready drafts")), tuple(context.get("disqualifiers") or ("no consent", "unsafe claims")))
    persona = Persona(str(context.get("persona_name") or "Owner-operator"), str(context.get("persona_role") or "Founder or marketing lead"), tuple(context.get("persona_goals") or ("make a confident next decision", "reduce wasted build effort")), tuple(context.get("objections") or ("Can the evidence support this?", "What remains to validate?")))
    package = (packages or {}).get(package_id)
    low, high = (float(getattr(package, "price_min", 500)), float(getattr(package, "price_max", 1000))) if package else (500.0, 1000.0)
    stages = tuple(PipelineStage(code, label, index, criteria) for index, (code, label, criteria) in enumerate((("new", "New", ("fit identified",)), ("qualified", "Qualified", ("consent and need reviewed",)), ("discovery", "Discovery", ("scope and budget discussed",)), ("proposal", "Proposal", ("draft proposal approved for review",)), ("won", "Won", ("client approval recorded",)), ("lost", "Lost", ("lost reason recorded",))), 1))
    deal = Deal("deal-demo", account_id, package_id, "qualified" if lead.score.score >= 45 else "new", low, high, .25 if lead.score.score >= 45 else .10, "Review fit and obtain human approval for a discovery step.")
    brief = SalesBrief(icp, persona, str(getattr(package, "name", "Product Opportunity Report")), "Turn scattered evidence into one prioritized, human-reviewed operating decision.", ("Offline evidence stack", "Explicit assumptions and blockers", "Implementation-ready next steps"), ("Supplier proof may still be missing.", "Fixture evidence is not launch authorization."))
    messages = (MessageDraft("email", "Draft: evidence-led validation review", "Hi — I prepared a draft outline for an evidence-led validation review. If this is relevant, we can confirm scope and the next human-reviewed step.", unsubscribe_note="Confirm consent and opt-out handling before sending."), MessageDraft("dm", "Draft: validation workflow", "Draft only: would a short evidence review help prioritize your next product or growth decision?", unsubscribe_note="Do not send without explicit opt-in."), MessageDraft("whatsapp_sms", "Draft: follow-up", "Draft only: following up on the proposed validation review. Reply only if you opted in to this channel.", unsubscribe_note="Do not send without channel consent or opt-in."))
    objections = tuple(ObjectionHandlingCard(item, "Acknowledge the question, show the relevant evidence source, and keep the unknown explicit.", "approved source report", "escalate to manager if evidence is absent") for item in persona.objections)
    proposal = ProposalDraft(package_id, ("Review supplied context", "Produce an evidence-backed report", "Deliver prioritized next actions"), (low, high), ("Price and scope are planning bands.", "No guarantee of profit or launch performance."), ("Client approves scope.", "Claims and source evidence are reviewed."))
    handoff = HandoffPacket(account_id, package_id, True, "delivery_owner_tbd", ("lead context", "service catalog"), ("client goals", "approved scope", "delivery deadline"))
    call = CallScriptDraft("Thanks for making time. I want to understand the decision you need to make.", ("What would make this review valuable?", "Which evidence is already trusted?", "What must remain human-approved?"), tuple(card.response for card in objections), "Agree on one scoped, approval-gated deliverable.")
    return SalesPipelineSeed(icp, (lead,), (account,), (contact,), (deal,), stages, brief, messages, call, proposal, (handoff,), objections, (AppointmentDraft("appointment-demo", "Scope review", ("TBD",)),), (ReminderDraft("reminder-demo", "after human-approved appointment", "Draft reminder only; do not send automatically."),), ("Sales artifacts are drafts only.", "No CRM, email, messaging, voice, booking, invoice, or payment action is performed.", "Consent and do-not-contact status must be reviewed by a human."))


__all__ = ["ICP", "Persona", "BuyingIntent", "LeadScore", "PipelineStage", "Lead", "Account", "Contact", "Deal", "OutreachSequenceDraft", "MessageDraft", "ConversationThreadDraft", "CallScriptDraft", "SalesBrief", "ObjectionHandlingCard", "AppointmentDraft", "ReminderDraft", "ProposalDraft", "HandoffPacket", "LostReason", "ClosePlan", "SalesPipelineSeed", "build_sales_pipeline"]
