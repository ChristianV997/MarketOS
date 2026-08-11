"""CompanyOS Department Layer v1.

This module is the deterministic internal operating spine for MarketOS. It
models departments, managers, workstreams, finance scenarios, ledger seeds,
sales drafts, approvals, and risks without granting external authority.
It deliberately produces planning records rather than executing work.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from typing import Any, Iterable, Mapping

from .accounting import AccountingLedgerSeed, build_accounting_ledger
from .finance import FinancePlan, build_finance_plan
from .sales import SalesPipelineSeed, build_sales_pipeline
from .service_catalog import ServicePackage, catalog_to_dict, load_service_catalog, package_map

DEPARTMENT_TYPES = frozenset({"management", "finance", "accounting", "sales", "intelligence", "supplier", "consumer_attention", "launch", "website_store_funnel", "operations", "risk_approval"})
TASK_STATUSES = frozenset({"not_started", "in_progress", "blocked", "ready_for_review", "complete"})
PRIORITIES = frozenset({"critical", "high", "medium", "low"})


def _safe(value: Any) -> Any:
    if is_dataclass(value):
        return {key: _safe(item) for key, item in asdict(value).items()}
    if isinstance(value, Mapping):
        return {str(key): _safe(item) for key, item in value.items()}
    if isinstance(value, (tuple, list, set)):
        return [_safe(item) for item in value]
    return value


def _text(value: Any, default: str = "TBD", limit: int = 240) -> str:
    value = " ".join(str(value or "").split())
    return (value or default)[:limit]


@dataclass(frozen=True)
class CompanyProfile:
    company_id: str
    name: str
    legal_name: str
    business_type: str
    country: str
    currency: str
    mission: str
    operating_mode: str
    evidence_mode: str
    context_status: str


@dataclass(frozen=True)
class DepartmentManager:
    manager_id: str
    name: str
    title: str
    decision_scope: tuple[str, ...]
    escalation_to: str
    human_approval_required: bool = True


@dataclass(frozen=True)
class Role:
    role_id: str
    name: str
    responsibilities: tuple[str, ...]
    decision_rights: tuple[str, ...]
    forbidden_actions: tuple[str, ...]


@dataclass(frozen=True)
class Workstream:
    workstream_id: str
    name: str
    department: str
    status: str
    priority: str
    owner_role: str
    dependencies: tuple[str, ...]
    next_action: str
    evidence_status: str


@dataclass(frozen=True)
class Task:
    task_id: str
    title: str
    department: str
    owner: str
    status: str
    priority: str
    due_date: str
    dependencies: tuple[str, ...]
    approval_required: bool
    next_action: str


@dataclass(frozen=True)
class Milestone:
    milestone_id: str
    name: str
    department: str
    target_date: str
    status: str
    exit_criteria: tuple[str, ...]


@dataclass(frozen=True)
class DepartmentScorecard:
    department: str
    status: str
    score: float
    completed_workstreams: int
    blocked_workstreams: int
    pending_approvals: int
    top_metric: str
    next_best_action: str


@dataclass(frozen=True)
class ApprovalRequest:
    approval_id: str
    subject_type: str
    subject_id: str
    requested_by: str
    approver_role: str
    status: str
    required_evidence: tuple[str, ...]
    forbidden_without_approval: tuple[str, ...]
    decision_deadline: str


@dataclass(frozen=True)
class DecisionRecord:
    decision_id: str
    decision: str
    rationale: str
    evidence_refs: tuple[str, ...]
    owner: str
    status: str = "draft"


@dataclass(frozen=True)
class OperatingEvent:
    event_id: str
    event_type: str
    department: str
    subject_id: str
    occurred_at: str
    payload_summary: dict[str, Any]
    advisory: bool = True
    authoritative: bool = False


@dataclass(frozen=True)
class RiskRegisterItem:
    risk_id: str
    department: str
    category: str
    description: str
    severity: str
    likelihood: str
    mitigation: str
    owner: str
    status: str
    escalation_required: bool


@dataclass(frozen=True)
class OperatingReview:
    review_id: str
    period: str
    ceo_summary: str
    priorities: tuple[str, ...]
    blocked_workstreams: tuple[str, ...]
    pending_approvals: tuple[str, ...]
    risk_escalations: tuple[str, ...]
    owner_assignments: dict[str, str]
    decisions_needed: tuple[str, ...]


@dataclass(frozen=True)
class Department:
    department_id: str
    name: str
    department_type: str
    manager: DepartmentManager
    roles: tuple[Role, ...]
    workstreams: tuple[Workstream, ...]
    tasks: tuple[Task, ...]
    scorecard: DepartmentScorecard
    risks: tuple[RiskRegisterItem, ...]
    approvals: tuple[ApprovalRequest, ...]
    operating_status: str
    next_best_action: str


@dataclass(frozen=True)
class CompanyScorecard:
    company_status: str
    score: float
    revenue_readiness: str
    delivery_readiness: str
    cash_control_status: str
    evidence_readiness: str
    safety_status: str
    blocked_departments: tuple[str, ...]
    next_best_action: str


@dataclass(frozen=True)
class ManagementPlan:
    org_chart: dict[str, Any]
    responsibilities: dict[str, tuple[str, ...]]
    manager_briefs: tuple[dict[str, Any], ...]
    weekly_operating_review: OperatingReview
    department_scorecards: tuple[DepartmentScorecard, ...]
    top_risks: tuple[RiskRegisterItem, ...]
    approval_queue: tuple[ApprovalRequest, ...]
    next_actions: tuple[Task, ...]


@dataclass(frozen=True)
class DepartmentOperatingModel:
    departments: tuple[Department, ...]
    shared_rules: tuple[str, ...]
    escalation_policy: tuple[str, ...]


@dataclass(frozen=True)
class WeeklyOperatingReview:
    period: str
    wins: tuple[str, ...]
    misses: tuple[str, ...]
    blockers: tuple[str, ...]
    decisions: tuple[str, ...]


@dataclass(frozen=True)
class ExecutiveDecision:
    decision_id: str
    question: str
    recommendation: str
    confidence: str
    approval_required: bool


@dataclass(frozen=True)
class ManagerBrief:
    manager_id: str
    department: str
    summary: str
    priorities: tuple[str, ...]
    blockers: tuple[str, ...]
    asks: tuple[str, ...]


@dataclass(frozen=True)
class TaskBacklog:
    tasks: tuple[Task, ...]
    status: str


@dataclass(frozen=True)
class ApprovalQueue:
    requests: tuple[ApprovalRequest, ...]
    pending_count: int
    status: str


@dataclass(frozen=True)
class Escalation:
    escalation_id: str
    risk_id: str
    reason: str
    owner: str
    status: str = "open"


@dataclass(frozen=True)
class CompanyOSReport:
    report_version: str
    generated_at: str
    company: CompanyProfile
    departments: tuple[Department, ...]
    management: ManagementPlan
    finance: Any
    accounting: Any
    sales: Any
    service_catalog: tuple[ServicePackage, ...]
    approval_queue: ApprovalQueue
    risk_register: tuple[RiskRegisterItem, ...]
    company_scorecard: CompanyScorecard
    source_reports: dict[str, str]
    next_best_actions: tuple[str, ...]
    safety_assertions: tuple[str, ...]
    read_only: bool = True
    network_calls: bool = False
    mutated: bool = False
    external_actions: bool = False
    live_messages_sent: bool = False
    payments_created: bool = False
    ads_launched: bool = False
    orders_created: bool = False
    publishing_done: bool = False

    def __post_init__(self) -> None:
        flags = (self.read_only, not self.network_calls, not self.mutated, not self.external_actions, not self.live_messages_sent, not self.payments_created, not self.ads_launched, not self.orders_created, not self.publishing_done)
        if not all(flags):
            raise ValueError("CompanyOS is planning-only; live-action flags must remain safe")

    def to_dict(self) -> dict[str, Any]:
        return _safe(self)

    def to_markdown(self) -> str:
        lines = ["# CompanyOS Department Layer", "", "## CEO Summary", "", self.management.weekly_operating_review.ceo_summary, "", f"- Company status: **{self.company_scorecard.company_status}**", f"- Operating score: **{self.company_scorecard.score}/100**", f"- Next action: {self.company_scorecard.next_best_action}", "", "## Department Registry", "", "| Department | Manager | Status | Score | Next action |", "|---|---|---|---:|---|"]
        lines.extend(f"| {item.name} | {item.manager.name} | {item.operating_status} | {item.scorecard.score} | {item.next_best_action} |" for item in self.departments)
        lines += ["", "## Management Operating Review", "", f"Period: {self.management.weekly_operating_review.period}", "", "### Weekly priorities"]
        lines.extend(f"- {item}" for item in self.management.weekly_operating_review.priorities)
        lines += ["", "### Blocked workstreams"]
        lines.extend(f"- {item}" for item in self.management.weekly_operating_review.blocked_workstreams or ("None recorded",))
        lines += ["", "### Pending approvals"]
        lines.extend(f"- {item}" for item in self.management.weekly_operating_review.pending_approvals or ("None",))
        lines += ["", "## Finance Plan", "", f"- Monthly revenue forecast: {self.finance.monthly_revenue_forecast_total if hasattr(self.finance, 'monthly_revenue_forecast_total') else round(sum(item.monthly_revenue for item in self.finance.monthly_revenue_forecast), 2)} {self.finance.currency}", f"- Monthly operating profit forecast: {self.finance.operating_profit_forecast} {self.finance.currency}", f"- Cash runway: {self.finance.cash_runway.runway_months if self.finance.cash_runway.runway_months is not None else 'not modeled'} months", "- Planning only; no payment or bank action is performed.", "", "## Accounting Ledger Seed", "", f"- Transactions: {len(self.accounting.transactions)}", f"- Reconciliation: {self.accounting.reconciliation.status}", f"- P&L status: {self.accounting.profit_and_loss.status}", "", "## Sales Pipeline Seed", "", f"- Leads: {len(self.sales.leads)}", f"- Deals: {len(self.sales.deals)}", f"- Recommended offer: {self.sales.brief.recommended_offer}", "- Messages remain drafts and require consent/human approval.", "", "## Service Catalog", "", "| Package | Price band | Owner | Handoff |", "|---|---:|---|---|"]
        lines.extend(f"| {item.name} | {item.price_min}-{item.price_max} | {item.department_owner} | {item.handoff_department} |" for item in self.service_catalog)
        lines += ["", "## Approval Queue", ""]
        lines.extend(f"- `{item.approval_id}` — {item.subject_type}/{item.subject_id}: **{item.status}**" for item in self.approval_queue.requests or ())
        if not self.approval_queue.requests:
            lines.append("- No pending approvals.")
        lines += ["", "## Risk Register", ""]
        lines.extend(f"- **{item.severity}** `{item.category}` — {item.description} (owner: {item.owner})" for item in self.risk_register)
        lines += ["", "## Next Best Actions", ""]
        lines.extend(f"{index}. {item}" for index, item in enumerate(self.next_best_actions, 1))
        lines += ["", "## Safety Boundaries", "", "- Offline deterministic planning only.", "- No credentials, external calls, messages, payments, ads, orders, publishing, or provider mutations.", "- Finance and accounting values are planning/ledger seeds, not tax or investment advice."]
        return "\n".join(lines) + "\n"


def _manager(department: str, title: str, scope: Iterable[str]) -> DepartmentManager:
    return DepartmentManager(f"manager-{department}", f"{title} manager", title, tuple(scope), "management", True)


def _role(department: str, name: str, responsibilities: Iterable[str]) -> Role:
    return Role(f"{department}-{name.lower().replace(' ', '-')}", name, tuple(responsibilities), ("prioritize work", "prepare decisions"), ("send messages", "spend money", "publish", "mutate external systems"))


def _task(task_id: str, title: str, department: str, status: str, priority: str, next_action: str, approval: bool = False) -> Task:
    return Task(task_id, title, department, f"manager-{department}", status, priority, "TBD", (), approval, next_action)


def _department(department: str, name: str, manager: DepartmentManager, roles: tuple[Role, ...], workstreams: tuple[Workstream, ...], tasks: tuple[Task, ...], risks: tuple[RiskRegisterItem, ...], approvals: tuple[ApprovalRequest, ...], next_action: str) -> Department:
    blocked = sum(item.status == "blocked" for item in workstreams)
    pending = len(approvals)
    score = round(max(0.0, min(100.0, 100.0 - blocked * 20 - pending * 10)), 2)
    status = "blocked" if blocked else "partially_ready" if pending else "ready"
    scorecard = DepartmentScorecard(department, status, score, sum(item.status == "complete" for item in workstreams), blocked, pending, f"{len(workstreams)} workstreams tracked", next_action)
    return Department(department, name, department, manager, roles, workstreams, tasks, scorecard, risks, approvals, status, next_action)


def _approval(subject_type: str, subject_id: str, requested_by: str, evidence: Iterable[str], forbidden: Iterable[str]) -> ApprovalRequest:
    return ApprovalRequest(f"approval-{subject_type}-{subject_id}", subject_type, subject_id, requested_by, "management", "pending", tuple(evidence), tuple(forbidden), "TBD")


def _risks(context: Mapping[str, Any], *, source_reports: Mapping[str, str], has_ledger: bool) -> list[RiskRegisterItem]:
    risks = [
        RiskRegisterItem("risk-supplier-proof", "supplier", "evidence", "Supplier proof is not live-validated by default.", "high", "high", "Run an explicitly approved read-only validation when credentials are configured.", "manager-supplier", "open", True),
        RiskRegisterItem("risk-approval-authority", "risk_approval", "governance", "No external action should proceed without recorded human approval.", "high", "medium", "Keep approval queue and forbidden-action list in every operating review.", "manager-risk_approval", "controlled", True),
        RiskRegisterItem("risk-cash-assumptions", "finance", "cash", "Forecast values are assumptions and may not reflect actual cash.", "medium", "medium", "Replace assumptions with accountant-reviewed records before spend decisions.", "manager-finance", "open", False),
        RiskRegisterItem("risk-ledger-unreconciled", "accounting", "reconciliation", "Ledger seed may contain unreconciled manual rows.", "medium", "medium", "Reconcile with an accountant; do not post automatically.", "manager-accounting", "open" if has_ledger else "not_configured", False),
        RiskRegisterItem("risk-outreach-consent", "sales", "consent", "Sales drafts may not be sent without channel consent and opt-out handling.", "high", "medium", "Track consent and do-not-contact before human-approved outreach.", "manager-sales", "controlled", True),
    ]
    if context.get("privacy_policy_status") not in {"approved", "present"}:
        risks.append(RiskRegisterItem("risk-policy-readiness", "website_store_funnel", "policy", "Policy status is not approved in company context.", "medium", "medium", "Obtain client-approved privacy/terms/returns text before publishing.", "manager-website_store_funnel", "open", True))
    return risks


def build_companyos_report(*, company_context: Mapping[str, Any] | None = None, finance_context: Mapping[str, Any] | None = None, sales_context: Mapping[str, Any] | None = None, service_catalog_seed: Mapping[str, Any] | None = None, source_reports: Mapping[str, Mapping[str, Any] | str] | None = None, accounting_csv: str | None = None) -> CompanyOSReport:
    context = company_context or {}
    generated_at = _text(context.get("generated_at"), "offline-deterministic")
    profile = CompanyProfile(_text(context.get("company_id"), "marketos"), _text(context.get("company_name"), "MarketOS"), _text(context.get("legal_name"), "TBD"), _text(context.get("business_type"), "consulting_first"), _text(context.get("country"), "TBD"), _text(context.get("currency"), "USD", 8), _text(context.get("mission"), "Turn evidence into approved, measurable operating decisions."), _text(context.get("operating_mode"), "offline_planning"), _text(context.get("evidence_mode"), "fixture_demo"), "configured" if context else "defaulted")
    packages = load_service_catalog(service_catalog_seed)
    reports = {key: (value if isinstance(value, str) else "available") for key, value in (source_reports or {}).items()}
    has_synthesis = "opportunity_synthesis" in reports
    has_launch = "launch_draft_pack" in reports
    has_site = "site_draft_pack" in reports
    risks = _risks(context, source_reports=reports, has_ledger=bool(accounting_csv))
    approvals: list[ApprovalRequest] = [_approval("department_layer", "companyos-v1", "management", ("company context reviewed",), ("external action", "spend", "publishing"))]
    if has_synthesis or has_launch or has_site:
        approvals.append(_approval("delivery_package", "commerce-to-site", "launch", ("source reports", "client scope", "client/service scope", "claims review"), ("publish", "send", "spend")))
    if not context.get("privacy_policy_status") in {"approved", "present"}:
        approvals.append(_approval("policy", "privacy-terms", "website_store_funnel", ("client-approved policy text",), ("publish", "collect data")))
    source_text = " and ".join(sorted(reports)) if reports else "no optional commerce report"
    core = {
        "management": ("department coordination", "weekly operating review", "approval queue"),
        "finance": ("scenario forecast", "budget caps", "cash runway"),
        "accounting": ("ledger-ready records", "reconciliation review", "period summaries"),
        "sales": ("qualified pipeline", "draft outreach", "delivery handoff"),
        "intelligence": ("marketplace and opportunity evidence",),
        "supplier": ("supplier feasibility and proof",),
        "consumer_attention": ("consumer attention and creative evidence",),
        "launch": ("launch draft assets",),
        "website_store_funnel": ("portable site/store/funnel drafts",),
        "operations": ("delivery handoffs and operating controls",),
        "risk_approval": ("risk register and human approval",),
    }
    names = {"management": "Management", "finance": "Finance", "accounting": "Accounting", "sales": "Sales", "intelligence": "Intelligence", "supplier": "Supplier", "consumer_attention": "Consumer Attention", "launch": "Launch", "website_store_funnel": "Website / Store / Funnel", "operations": "Operations", "risk_approval": "Risk & Approval"}
    departments: list[Department] = []
    for department, responsibilities in core.items():
        manager = _manager(department, names[department], responsibilities)
        role = _role(department, "Manager", responsibilities)
        status = "blocked" if department == "supplier" else "partially_ready" if department in {"finance", "accounting", "sales", "website_store_funnel"} else "ready"
        evidence = "live proof required" if department == "supplier" else "offline planning" if department in {"finance", "accounting", "sales"} else "fixture/demo capable"
        workstreams = (Workstream(f"{department}-core", responsibilities[0], department, status, "high" if department in {"management", "supplier", "sales"} else "medium", role.role_id, (), f"Review {department} operating brief", evidence),)
        tasks = (_task(f"{department}-review", f"Review {names[department]} operating brief", department, "blocked" if status == "blocked" else "ready_for_review", "high" if department in {"management", "supplier"} else "medium", f"Assign a human owner for {department} review", department in {"supplier", "sales"}),)
        department_risks = tuple(item for item in risks if item.department == department)
        department_approvals = tuple(item for item in approvals if item.subject_type in {"department_layer", "delivery_package", "policy"} and department in {"management", "launch", "website_store_funnel"})
        departments.append(_department(department, names[department], manager, (role,), workstreams, tasks, department_risks, department_approvals, f"Review {names[department]} brief and record next decision."))
    finance = build_finance_plan(context=finance_context or context, packages=packages, candidate_ids=(str(item) for item in context.get("candidate_ids", ())))
    accounting = build_accounting_ledger(csv_text=accounting_csv)
    sales = build_sales_pipeline(context=sales_context or {}, packages=package_map(packages))
    pending = tuple(approvals)
    review = OperatingReview("weekly-review-offline", _text(context.get("review_period"), "current planning period"), f"MarketOS is operating in offline planning mode across {len(departments)} departments. Sources: {source_text}. No external authority is enabled.", ("Complete the highest-value evidence or client-delivery review.", "Protect cash and record assumptions.", "Keep all outreach and publishing as drafts."), tuple(item.workstreams[0].name for item in departments if item.operating_status == "blocked"), tuple(item.approval_id for item in pending), tuple(item.risk_id for item in risks if item.escalation_required), {item.department_id: item.manager.manager_id for item in departments}, ("Confirm supplier proof path.", "Confirm client/service scope before delivery."))
    scorecards = tuple(item.scorecard for item in departments)
    management = ManagementPlan({"company": profile.name, "departments": [{"id": item.department_id, "manager": item.manager.manager_id} for item in departments]}, {key: tuple(value) for key, value in core.items()}, tuple(ManagerBrief(item.manager.manager_id, item.department_id, f"{item.name} is {item.operating_status} with score {item.scorecard.score}.", (item.next_best_action,), tuple(risk.description for risk in item.risks), ("Record a decision or escalation.",)) for item in departments), review, scorecards, tuple(risks), pending, tuple(task for item in departments for task in item.tasks))
    blocked = tuple(item.department_id for item in departments if item.operating_status == "blocked")
    company_status = "blocked" if blocked else "partially_ready" if pending or any(item.operating_status == "partially_ready" for item in departments) else "ready"
    score = round(max(0.0, min(100.0, 100.0 - len(blocked) * 12 - len(pending) * 4 - sum(item.severity == "high" for item in risks) * 3)), 2)
    scorecard = CompanyScorecard(company_status, score, "partially_ready" if not has_synthesis else "evidence_linked", "scenario_only", "review_required" if accounting.reconciliation.unreconciled_count else "seed_ready", "review_required" if pending else "controlled", "controlled", blocked, "Resolve supplier proof and human approvals before external action.")
    actions = ("Review supplier proof readiness and configure only approved read-only validation when available.", "Approve one client/service scope and assign a delivery owner.", "Reconcile accounting seed records before using forecasts for spend decisions.", "Review consent and do-not-contact fields before any outreach.")
    return CompanyOSReport("companyos-department-layer-v1", generated_at, profile, tuple(departments), management, finance, accounting, sales, tuple(packages), ApprovalQueue(pending, len(pending), "pending" if pending else "clear"), tuple(risks), scorecard, reports, actions, ("All records are offline, advisory, and non-authoritative.", "Human approval is required before outreach, spend, publishing, payments, orders, or platform/provider actions.", "Finance scenarios are not tax, accounting, investment, or legal advice."))


__all__ = ["DEPARTMENT_TYPES", "TASK_STATUSES", "PRIORITIES", "CompanyProfile", "DepartmentManager", "Role", "Workstream", "Task", "Milestone", "OperatingEvent", "ApprovalRequest", "DecisionRecord", "RiskRegisterItem", "OperatingReview", "DepartmentScorecard", "Department", "CompanyScorecard", "ManagementPlan", "DepartmentOperatingModel", "WeeklyOperatingReview", "ExecutiveDecision", "ManagerBrief", "TaskBacklog", "ApprovalQueue", "Escalation", "CompanyOSReport", "build_companyos_report"]
