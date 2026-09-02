"""Deterministic, offline learning memory for CompanyOS decisions and experiments.

Client-visibility vocabulary note (recovery pass): `VISIBILITY` below is
parallel to, but not byte-identical with,
`evaluation.trustos.client_workspace_isolation.ACCESS_MODES`. Three values
match exactly (`internal_only`, `workspace_only`, `blocked`); two are
near-misses (`client_visible_summary` here vs `client_visible` there;
`aggregated_safe_summary` here vs `aggregated_safe_summary_only` there);
and `redacted_summary_only` has no counterpart here. This module still
enforces its own visibility gating and rejects client-private and
secret-like input, so the drift is a consistency gap rather than a leak
path -- it is recorded here rather than silently renamed, because
renaming would change this module's recovered schema and the semantics
its tests encode. Reconciling the two vocabularies deliberately is a
follow-up for a lane that owns both modules.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar, Mapping, Sequence

EVENT_TYPES = ("product_validation", "supplier_validation", "consumer_attention_test", "creative_test", "ad_experiment", "landing_page_test", "site_funnel_test", "sales_outreach_test", "provider_run", "model_routing_decision", "security_scan", "trustos_review", "companyos_review", "portfolio_decision", "kill_decision", "scale_decision", "runaway_guard_event", "client_export_review")
OUTCOMES = ("win", "loss", "inconclusive", "killed", "scaled", "paused", "iterated", "blocked", "needs_more_evidence", "invalid_test")
VISIBILITY = ("internal_only", "workspace_only", "client_visible_summary", "aggregated_safe_summary", "blocked")
FAILURE_REASONS = ("weak_demand", "weak_supplier_feasibility", "poor_margin", "high_shipping_risk", "low_attention", "low_click_through", "weak_conversion_intent", "poor_offer", "poor_creative_angle", "audience_mismatch", "price_mismatch", "landing_page_mismatch", "trust_blocker", "provider_blocker", "budget_cap", "model_cost_too_high", "insufficient_sample", "invalid_test_design", "runaway_guard_triggered", "missing_learning_capture")
SUCCESS_REASONS = ("strong_demand", "strong_supplier_fit", "strong_attention_signal", "clear_pain_point", "strong_hook", "high_margin", "fast_shipping", "low_competition", "good_offer_market_fit", "good_creative_market_fit", "good_landing_page_fit", "low_cpa_projection", "strong_portfolio_fit", "trustos_ready", "provider_ready", "budget_efficient")
BLOCK_BEHAVIORS = ("warn", "soft_block", "hard_block", "requires_approval")
LEARNING_TYPES = ("product_validation", "supplier_validation", "creative_test", "ad_experiment", "landing_page_test", "sales_outreach", "provider_run", "model_routing", "security_scan", "trustos_review")


def _clean(value: Any) -> Any:
    if hasattr(value, "__dataclass_fields__"):
        return {key: _clean(getattr(value, key)) for key in value.__dataclass_fields__}
    if hasattr(value, "to_dict"):
        return value.to_dict()
    if isinstance(value, Mapping):
        return {str(key): _clean(item) for key, item in value.items()}
    if isinstance(value, (tuple, list, set)):
        return [_clean(item) for item in value]
    return value


@dataclass(frozen=True)
class LearningHypothesis:
    hypothesis_id: str
    statement: str
    success_criteria: tuple[str, ...]
    target_metric: str
    target_value: float | None
    def to_dict(self) -> dict[str, Any]: return _clean(self)


@dataclass(frozen=True)
class LearningMetric:
    metric_id: str
    name: str
    value: float | None
    target: float | None
    unit: str
    sample_size: int
    source: str
    def to_dict(self) -> dict[str, Any]: return _clean(self)


@dataclass(frozen=True)
class LearningResult:
    result_id: str
    outcome: str
    summary: str
    metric_values: tuple[LearningMetric, ...]
    evidence_strength: float
    def __post_init__(self) -> None:
        if self.outcome not in OUTCOMES: raise ValueError("invalid learning outcome")
    def to_dict(self) -> dict[str, Any]: return _clean(self)


@dataclass(frozen=True)
class LearningAttribution:
    attribution_id: str
    factors: tuple[str, ...]
    confidence: float
    method: str
    limitations: tuple[str, ...]
    def to_dict(self) -> dict[str, Any]: return _clean(self)


@dataclass(frozen=True)
class LearningLesson:
    lesson_id: str
    title: str
    lesson_type: str
    statement: str
    evidence_refs: tuple[str, ...]
    confidence: float
    client_visibility: str
    def __post_init__(self) -> None:
        if self.client_visibility not in VISIBILITY: raise ValueError("invalid lesson visibility")
    def to_dict(self) -> dict[str, Any]: return _clean(self)


@dataclass(frozen=True)
class LearningDoNotRepeatRule:
    rule_id: str
    source_event_id: str
    applies_to_action_types: tuple[str, ...]
    applies_to_departments: tuple[str, ...]
    condition: str
    severity: str
    recommended_block_behavior: str
    expiry_or_review_period: str
    client_visible: bool
    def __post_init__(self) -> None:
        if self.recommended_block_behavior not in BLOCK_BEHAVIORS: raise ValueError("invalid block behavior")
    def to_dict(self) -> dict[str, Any]: return _clean(self)


@dataclass(frozen=True)
class LearningIterationRecommendation:
    recommendation_id: str
    source_event_id: str
    action_type: str
    recommendation: str
    rationale: str
    expected_learning: str
    priority: str
    client_visible: bool
    def to_dict(self) -> dict[str, Any]: return _clean(self)


@dataclass(frozen=True)
class LearningPortfolioImpact:
    portfolio_area: str
    positive_signals: tuple[str, ...]
    negative_signals: tuple[str, ...]
    recommended_allocation_change: str
    recommended_deprioritization: str
    recommended_focus_area: str
    confidence: float
    def to_dict(self) -> dict[str, Any]: return _clean(self)


@dataclass(frozen=True)
class LearningModelRoutingImpact:
    model_route_id: str
    task_type: str
    observed_outcome: str
    recommended_model_tier_next_time: str
    cost_savings_note: str
    quality_risk_note: str
    confidence: float
    def to_dict(self) -> dict[str, Any]: return _clean(self)


@dataclass(frozen=True)
class LearningProviderImpact:
    provider_id: str
    request_kind: str
    cost_estimate: float
    evidence_value: float
    schema_quality: float
    blocked_reason: str
    terms_privacy_blocker: bool
    output_contract_blocker: bool
    recommended_next_provider_action: str
    def to_dict(self) -> dict[str, Any]: return _clean(self)


@dataclass(frozen=True)
class LearningTrustOSImpact:
    blocker: str
    occurrences: int
    recommended_control_improvements: tuple[str, ...]
    recommended_next_evidence: tuple[str, ...]
    confidence: float
    def to_dict(self) -> dict[str, Any]: return _clean(self)


@dataclass(frozen=True)
class LearningDecisionInfluence:
    action_type: str
    candidate_id: str
    workspace_id: str
    positive_prior_score: float
    negative_prior_score: float
    do_not_repeat_blockers: tuple[str, ...]
    missing_learning_blockers: tuple[str, ...]
    recommended_decision_modifier: str
    recommended_next_action: str
    def to_dict(self) -> dict[str, Any]: return _clean(self)


@dataclass(frozen=True)
class LearningEvent:
    learning_event_id: str
    source_decision_id: str
    source_module: str
    source_department: str
    workspace_id: str
    client_visibility: str
    event_type: str
    hypothesis: LearningHypothesis
    input_evidence_refs: tuple[str, ...]
    action_taken: str
    cost_estimate: float
    budget_context: dict[str, Any]
    metrics: tuple[LearningMetric, ...]
    outcome: str
    confidence: float
    failure_reasons: tuple[str, ...]
    success_reasons: tuple[str, ...]
    winner_attributes: tuple[str, ...]
    loser_attributes: tuple[str, ...]
    do_not_repeat_rules: tuple[str, ...]
    iteration_recommendations: tuple[str, ...]
    portfolio_impact: str
    resource_governor_influence: str
    created_at: str
    owner_department: str
    review_required: bool
    candidate_id: str = "candidate-placeholder"
    def __post_init__(self) -> None:
        if self.event_type not in EVENT_TYPES or self.outcome not in OUTCOMES or self.client_visibility not in VISIBILITY: raise ValueError("invalid learning event vocabulary")
        if any(reason not in FAILURE_REASONS for reason in self.failure_reasons): raise ValueError("invalid failure reason")
        if any(reason not in SUCCESS_REASONS for reason in self.success_reasons): raise ValueError("invalid success reason")
        if self.cost_estimate < 0: raise ValueError("learning cost cannot be negative")
    def to_dict(self) -> dict[str, Any]: return _clean(self)


@dataclass(frozen=True)
class LearningExperiment:
    experiment_id: str
    hypothesis: LearningHypothesis
    action_type: str
    budget_cap: float
    sample_size_target: int
    success_metric: str
    kill_threshold: float | None
    scale_threshold: float | None
    iteration_rule: str
    max_iterations: int
    learning_required: bool
    approval_required: bool
    event_refs: tuple[str, ...]
    status: str
    def to_dict(self) -> dict[str, Any]: return _clean(self)


@dataclass(frozen=True)
class LearningLedgerSummary:
    top_success_reasons: tuple[str, ...]
    top_failure_reasons: tuple[str, ...]
    top_do_not_repeat_rules: tuple[str, ...]
    top_iteration_recommendations: tuple[str, ...]
    recurring_blockers: tuple[str, ...]
    what_to_repeat: tuple[str, ...]
    what_to_avoid: tuple[str, ...]
    def to_dict(self) -> dict[str, Any]: return _clean(self)


@dataclass(frozen=True)
class LearningLedgerSafetySummary:
    read_only: bool = True
    database_writes: bool = False
    model_calls: bool = False
    provider_calls: bool = False
    ads_launched: bool = False
    sites_published: bool = False
    orders_created: bool = False
    payments_created: bool = False
    messages_sent: bool = False
    auth_calls: bool = False
    tenant_created: bool = False
    client_data_present: bool = False
    raw_prompts_present: bool = False
    real_metrics_present: bool = False
    artifacts_written: bool = False
    def __post_init__(self) -> None:
        if not self.read_only or any(value for key, value in _clean(self).items() if key != "read_only"): raise ValueError("learning ledger must remain offline and read-only")
    def to_dict(self) -> dict[str, Any]: return _clean(self)


@dataclass(frozen=True)
class LearningLedgerReport:
    report_version: str
    generated_at: str
    events: tuple[LearningEvent, ...]
    experiments: tuple[LearningExperiment, ...]
    results: tuple[LearningResult, ...]
    lessons: tuple[LearningLesson, ...]
    do_not_repeat_rules: tuple[LearningDoNotRepeatRule, ...]
    iteration_recommendations: tuple[LearningIterationRecommendation, ...]
    portfolio_impacts: tuple[LearningPortfolioImpact, ...]
    model_routing_impacts: tuple[LearningModelRoutingImpact, ...]
    provider_impacts: tuple[LearningProviderImpact, ...]
    trustos_impacts: tuple[LearningTrustOSImpact, ...]
    decision_influences: tuple[LearningDecisionInfluence, ...]
    summary: LearningLedgerSummary
    safety_summary: LearningLedgerSafetySummary
    next_best_action: str
    def to_dict(self) -> dict[str, Any]:
        data = _clean(self)
        outcomes = [item.outcome for item in self.events]
        data.update({"learning_event_count": len(self.events), "experiment_count": len(self.experiments), "win_count": outcomes.count("win"), "loss_count": outcomes.count("loss"), "kill_count": outcomes.count("killed"), "scale_count": outcomes.count("scaled"), "paused_count": outcomes.count("paused"), "inconclusive_count": outcomes.count("inconclusive"), "do_not_repeat_rule_count": len(self.do_not_repeat_rules), "iteration_recommendation_count": len(self.iteration_recommendations), "portfolio_impact_count": len(self.portfolio_impacts), "model_routing_impact_count": len(self.model_routing_impacts), "provider_impact_count": len(self.provider_impacts), "trustos_impact_count": len(self.trustos_impacts), "decision_influence_count": len(self.decision_influences), "resource_governor_feedback": _clean(self.decision_influences)})
        return data
    def to_markdown(self) -> str:
        data = self.to_dict(); lines = ["# Learning Ledger", "", "## Executive Summary", "", f"- Events: **{data['learning_event_count']}**", f"- Wins: **{data['win_count']}**", f"- Losses: **{data['loss_count']}**", f"- Killed: **{data['kill_count']}**", f"- Scaled: **{data['scale_count']}**", f"- Do-not-repeat rules: **{data['do_not_repeat_rule_count']}**", "- Mode: **offline deterministic fixture aggregation**", "", "## Learning Events", "", "| Event | Type | Outcome | Confidence |", "|---|---|---|---|"]
        lines.extend(f"| {item.learning_event_id} | {item.event_type} | **{item.outcome}** | {item.confidence:.2f} |" for item in self.events)
        lines += ["", "## Experiments", "", *[f"- `{item.experiment_id}`: {item.status}; metric `{item.success_metric}`; budget cap ${item.budget_cap:.2f}." for item in self.experiments], "", "## Wins and Losses", "", f"Success reasons: {', '.join(self.summary.top_success_reasons) or 'none'}.", f"Failure reasons: {', '.join(self.summary.top_failure_reasons) or 'none'}.", "", "## Kill / Scale Decisions", "", *[f"- {item.learning_event_id}: {item.outcome}; {item.resource_governor_influence}." for item in self.events if item.outcome in {"killed", "scaled"}], "", "## Do-Not-Repeat Rules", "", *[f"- **{item.severity} / {item.recommended_block_behavior}**: {item.condition}" for item in self.do_not_repeat_rules], "", "## Iteration Recommendations", "", *[f"- `{item.action_type}`: {item.recommendation}" for item in self.iteration_recommendations], "", "## Portfolio Learning", "", *[f"- `{item.portfolio_area}`: focus on {item.recommended_focus_area}; allocation: {item.recommended_allocation_change}." for item in self.portfolio_impacts], "", "## Model-Routing Learning", "", *[f"- `{item.task_type}` -> `{item.recommended_model_tier_next_time}`: {item.cost_savings_note}" for item in self.model_routing_impacts], "", "## Provider Learning", "", *[f"- `{item.provider_id}` / `{item.request_kind}`: evidence value {item.evidence_value:.2f}; {item.recommended_next_provider_action}." for item in self.provider_impacts], "", "## TrustOS / Security Learning", "", *[f"- `{item.blocker}` occurred {item.occurrences} time(s); next evidence: {', '.join(item.recommended_next_evidence)}." for item in self.trustos_impacts], "", "## Resource Governor Feedback", "", *[f"- `{item.action_type}`: modifier `{item.recommended_decision_modifier}`; {item.recommended_next_action}." for item in self.decision_influences], "", "## Safety Boundaries", "", "No database writes, model/provider calls, ads, publishing, orders, payments, messaging, auth, tenants, real client data, raw prompts, real metrics, or artifacts by default.", "", "## Next Best Action", "", self.next_best_action, ""]
        return "\n".join(lines)


def _hypothesis(event_type: str, statement: str) -> LearningHypothesis:
    return LearningHypothesis(f"hypothesis-{event_type}", statement, ("metric reaches target", "evidence remains valid"), "primary_metric", None)


def _metric(name: str, value: float | None, target: float | None, sample: int) -> LearningMetric:
    return LearningMetric(f"metric-{name}", name, value, target, "ratio", sample, "sanitized_fixture")


def _event(event_id: str, event_type: str, outcome: str, *, candidate: str = "candidate-placeholder", failures: Sequence[str] = (), successes: Sequence[str] = (), action: str | None = None, cost: float = 0.0, confidence: float = .8, metrics: Sequence[LearningMetric] = (), visibility: str = "internal_only", department: str = "management", provider: str = "", statement: str = "Tested a bounded hypothesis with sanitized evidence.", influence: str = "Record the outcome and use it in the next bounded decision.") -> LearningEvent:
    return LearningEvent(event_id, f"decision-{event_id}", "fixture_learning", department, "internal-companyos", visibility, event_type, _hypothesis(event_type, statement), (f"evidence-{event_id}",), action or event_type, cost, {"resource": "fixture_budget", "cap": cost}, tuple(metrics), outcome, confidence, tuple(failures), tuple(successes), (), (), (), (), "portfolio lesson captured", influence, "offline-deterministic", department, outcome in {"blocked", "loss", "killed"}, candidate)


def _default_events() -> tuple[LearningEvent, ...]:
    return (
        _event("event-ad-winner", "ad_experiment", "win", candidate="mini-thermal-printer", action="launch_ad_experiment", cost=18, metrics=(_metric("conversion_rate", .06, .05, 140),), successes=("strong_hook", "good_creative_market_fit", "budget_efficient"), statement="A bounded creative angle can produce efficient qualified demand.", influence="Support controlled scale after learning capture."),
        _event("event-ad-loser", "ad_experiment", "loss", candidate="portable-espresso-maker", action="launch_ad_experiment", cost=22, metrics=(_metric("conversion_rate", .01, .05, 120),), failures=("low_click_through", "poor_creative_angle", "audience_mismatch"), statement="The selected creative angle will reach and convert the target audience.", influence="Soft-block another creative batch until the lesson is captured."),
        _event("event-product-failure", "product_validation", "loss", candidate="portable-espresso-maker", action="deep_validate_product", cost=0, failures=("poor_margin", "weak_demand"), statement="This product has sufficient demand and economics for a bounded test.", influence="Reduce promotion priority and review economics."),
        _event("event-product-winner", "product_validation", "win", candidate="mini-thermal-printer", action="deep_validate_product", cost=0, successes=("strong_demand", "high_margin", "strong_portfolio_fit"), statement="This product clears demand, supplier, and unit-economics thresholds.", influence="Increase priority for a small controlled launch draft."),
        _event("event-supplier-failure", "supplier_validation", "blocked", candidate="portable-espresso-maker", action="request_supplier_proof", failures=("weak_supplier_feasibility", "high_shipping_risk"), influence="Prioritize supplier proof before promotion."),
        _event("event-creative-iteration", "creative_test", "iterated", candidate="mini-thermal-printer", action="generate_creative_batch", failures=("low_click_through",), successes=("strong_hook",), influence="Change the hook while preserving the validated pain point."),
        _event("event-landing-page", "landing_page_test", "inconclusive", candidate="mini-thermal-printer", action="generate_site_draft", failures=("landing_page_mismatch", "insufficient_sample"), influence="Iterate page/offer before more traffic."),
        _event("event-model-waste", "model_routing_decision", "loss", action="run_frontier_llm_synthesis", cost=12, failures=("model_cost_too_high",), influence="Route similar low-evidence work to algorithmic or cheap tiers."),
        _event("event-model-cheap", "model_routing_decision", "win", action="run_cheap_llm_task", cost=0.12, successes=("budget_efficient",), influence="Prefer cheap tier for routine structured drafting."),
        _event("event-provider-blocked", "provider_run", "blocked", action="run_provider_data_pull", provider="dataforseo", cost=5, failures=("provider_blocker",), influence="Complete terms/privacy and output-contract evidence before live consideration."),
        _event("event-provider-dry-run", "provider_run", "win", action="run_provider_data_pull", provider="dataforseo", cost=0, successes=("provider_ready",), influence="Keep DataForSEO in fixture/dry-run mode until activation gates pass."),
        _event("event-trustos-recurrence", "trustos_review", "blocked", action="generate_client_export", failures=("trust_blocker",), influence="Complete isolation and redaction evidence before export."),
        _event("event-security-scan", "security_scan", "needs_more_evidence", action="run_security_scan", failures=("insufficient_sample",), influence="Obtain sanitized scanner evidence before public launch decisions."),
        _event("event-runaway", "runaway_guard_event", "killed", action="spawn_agent_workflow", failures=("runaway_guard_triggered",), influence="Keep workflow and retry caps enforced."),
        _event("event-missing-learning", "creative_test", "blocked", candidate="portable-espresso-maker", action="generate_creative_batch", failures=("missing_learning_capture",), influence="Require previous iteration learning before new creative spend."),
        _event("event-sales", "sales_outreach_test", "inconclusive", action="generate_sales_sequence", failures=("insufficient_sample",), influence="Keep outreach as a draft and collect consent-aware evidence."),
        _event("event-portfolio", "portfolio_decision", "win", candidate="mini-thermal-printer", successes=("strong_portfolio_fit",), influence="Prefer existing category expansion over a new brand."),
        _event("event-client-review", "client_export_review", "win", visibility="client_visible_summary", successes=("trustos_ready",), action="generate_client_export", influence="Allow only the reviewed client-safe summary projection."),
        _event("event-attention", "consumer_attention_test", "win", successes=("strong_attention_signal",), action="screen_product_opportunities"),
        _event("event-site-funnel", "site_funnel_test", "inconclusive", failures=("insufficient_sample",), action="generate_site_draft"),
        _event("event-company-review", "companyos_review", "win", successes=("budget_efficient",), action="run_companyos_review"),
        _event("event-kill", "kill_decision", "killed", failures=("low_click_through",), action="kill_ad_experiment"),
        _event("event-scale", "scale_decision", "scaled", successes=("low_cpa_projection",), action="scale_ad_budget"),
    )


def _rule(event: LearningEvent, index: int) -> LearningDoNotRepeatRule | None:
    """Do-not-repeat condition text and blocked-action set, per
    `event.failure_reasons[0]`. Two named categories this mission requires
    (`absorbable new website`, `scale without evidence`) have no distinct
    entry in `FAILURE_REASONS` -- they are compound conditions over
    `event.action_taken` instead, checked before the reason-keyed map so a
    `create_new_website`/`scale_ad_budget` event gets the specific text
    rather than falling through to the generic fallback."""
    if not event.failure_reasons: return None
    reason = event.failure_reasons[0]
    if event.action_taken == "create_new_website":
        condition = "an existing brand or category can absorb this opportunity without a new site"
        return LearningDoNotRepeatRule(f"rule-{index}-{reason}", event.learning_event_id, ("create_new_website",), (event.owner_department,), condition, "medium", "soft_block", "review after new evidence or 30 days", event.client_visibility in {"client_visible_summary", "aggregated_safe_summary"})
    if event.action_taken == "scale_ad_budget" and (reason == "insufficient_sample" or event.outcome in {"loss", "blocked", "killed", "inconclusive"}):
        condition = "prior scale decision lacked sufficient sample size or confidence evidence before increasing spend"
        return LearningDoNotRepeatRule(f"rule-{index}-{reason}", event.learning_event_id, ("scale_ad_budget",), (event.owner_department,), condition, "high", "hard_block", "review after new evidence or 30 days", event.client_visibility in {"client_visible_summary", "aggregated_safe_summary"})
    if reason == "runaway_guard_triggered" and event.action_taken == "run_provider_data_pull":
        condition = "provider retry cap was exceeded without new evidence"
        return LearningDoNotRepeatRule(f"rule-{index}-{reason}", event.learning_event_id, ("run_provider_data_pull",), (event.owner_department,), condition, "high", "hard_block", "review after new evidence or 30 days", event.client_visibility in {"client_visible_summary", "aggregated_safe_summary"})
    condition_map = {"poor_margin": "product is below the approved margin threshold without a documented compensating economics case", "missing_learning_capture": "previous experiment learning is missing", "poor_creative_angle": "creative angle has not met the required attention or conversion threshold", "model_cost_too_high": "similar low-evidence task requests frontier reasoning", "provider_blocker": "provider activation lacks terms/privacy or output-contract evidence", "trust_blocker": "client-facing export lacks isolation, redaction, or TrustOS evidence", "runaway_guard_triggered": "workflow exceeds retry, agent, or step limits", "weak_supplier_feasibility": "supplier proof is incomplete", "landing_page_mismatch": "page/offer fit is not validated", "invalid_test_design": "ad experiment design lacked a hypothesis, kill rule, or sample-size target before launch"}
    condition = condition_map.get(reason, f"the same failure reason `{reason}` recurs without changed evidence")
    actions = ("launch_ad_experiment", "generate_creative_batch") if reason in {"poor_creative_angle", "missing_learning_capture", "invalid_test_design"} else ("run_frontier_llm_synthesis",) if reason == "model_cost_too_high" else ("run_provider_data_pull",) if reason == "provider_blocker" else ("generate_client_export",) if reason == "trust_blocker" else ("spawn_agent_workflow",) if reason == "runaway_guard_triggered" else ("increase_inventory_exposure", "promote_product_candidate") if reason in {"poor_margin", "weak_supplier_feasibility"} else (event.action_taken,)
    behavior = "hard_block" if reason in {"trust_blocker", "runaway_guard_triggered", "provider_blocker"} else "soft_block"
    return LearningDoNotRepeatRule(f"rule-{index}-{reason}", event.learning_event_id, actions, (event.owner_department,), condition, "high" if behavior == "hard_block" else "medium", behavior, "review after new evidence or 30 days", event.client_visibility in {"client_visible_summary", "aggregated_safe_summary"})


def _recommendation(event: LearningEvent, index: int) -> LearningIterationRecommendation:
    """Iteration-recommendation action/text/expected-signal, per
    `event.failure_reasons[0]`. `poor_offer`, `poor_margin`, `trust_blocker`,
    and `invalid_test_design` are explicit entries here (previously only
    `poor_margin`/`trust_blocker` had do-not-repeat rule text, not
    iteration-recommendation text, and `poor_offer`/`invalid_test_design`
    had neither) -- covering this mission's required "offer", "economics",
    and "TrustOS evidence" iteration-recommendation categories."""
    mapping = {"low_click_through": ("generate_creative_batch", "change the hook or audience while preserving the validated problem", "attention signal"), "landing_page_mismatch": ("generate_site_draft", "test a clearer offer/page structure before more traffic", "page conversion fit"), "weak_supplier_feasibility": ("request_supplier_proof", "obtain supplier, shipping, and landed-cost evidence", "supplier feasibility"), "model_cost_too_high": ("run_cheap_llm_task", "route routine work to algorithmic/local/cheap tiers", "quality at lower cost"), "provider_blocker": ("run_provider_data_pull", "complete terms/privacy and output-contract review in dry-run mode", "provider readiness"), "missing_learning_capture": ("run_companyos_review", "record the prior lesson before another experiment", "learning completeness"), "insufficient_sample": (event.action_taken, "collect a bounded sample without changing external execution mode", "evidence strength"), "poor_offer": ("iterate_offer_draft", "test a clearer value proposition, price, or bundle before more traffic", "offer market fit"), "poor_margin": ("run_unit_economics_review", "revisit landed cost, price, or fee assumptions before promoting", "economics viability"), "trust_blocker": ("run_trustos_control_plane", "attach TrustOS evidence and isolation review before the export", "TrustOS readiness"), "invalid_test_design": ("run_companyos_review", "define a hypothesis, kill rule, and sample-size target before relaunching", "experiment design quality")}
    reason = event.failure_reasons[0] if event.failure_reasons else "success"
    action, recommendation, expected = mapping.get(reason, (event.action_taken, "repeat only with changed evidence and the prior lesson attached", "decision quality"))
    return LearningIterationRecommendation(f"iteration-{index}-{event.learning_event_id}", event.learning_event_id, action, recommendation, f"Prior event `{event.learning_event_id}` recorded `{reason}`.", expected, "high" if event.outcome in {"loss", "blocked", "killed"} else "medium", event.client_visibility in {"client_visible_summary", "aggregated_safe_summary"})


def _portfolio_impacts(events: Sequence[LearningEvent]) -> tuple[LearningPortfolioImpact, ...]:
    return (LearningPortfolioImpact("product-category", ("mini-thermal-printer has strong demand and margin signals",), ("portable-espresso-maker has weak economics and demand",), "allocate the next bounded validation slot to validated high-fit candidates", "deprioritize categories with repeated margin/supplier failures", "validated products with supplier proof and strong portfolio fit", .8), LearningPortfolioImpact("creative-hooks", ("strong hook produced efficient conversion",), ("generic angle produced weak click-through",), "allocate creative iteration to pain-point hooks", "avoid repeating the losing angle without changed evidence", "pain-point and demonstrated-use hooks", .78), LearningPortfolioImpact("landing-pages", ("no stable winner yet",), ("page/offer fit remains inconclusive",), "reserve capacity for one structured page iteration", "avoid increasing traffic before page evidence improves", "offer clarity and proof structure", .65))


def _model_impacts(events: Sequence[LearningEvent]) -> tuple[LearningModelRoutingImpact, ...]:
    return (LearningModelRoutingImpact("frontier-reasoning", "low-evidence synthesis", "loss", "algorithmic_or_cheap_llm", "Avoid repeated frontier spend; expected savings versus fixture waste.", "Quality may require human review for high-stakes synthesis.", .9), LearningModelRoutingImpact("cheap-api", "routine structured drafting", "win", "cheap_llm", "Keep routine drafting on the cheaper route.", "Verify schema and groundedness before reuse.", .85), LearningModelRoutingImpact("algorithmic", "deterministic scoring", "win", "algorithmic", "No token cost for repeatable scoring.", "Escalate only when evidence synthesis is genuinely needed.", .9), LearningModelRoutingImpact("human-review", "legal/tax/security final decisions", "needs_more_evidence", "human_review", "Human review is required rather than model substitution.", "No professional conclusion is generated by this ledger.", .9))


def _provider_impacts(events: Sequence[LearningEvent]) -> tuple[LearningProviderImpact, ...]:
    return (LearningProviderImpact("dataforseo", "serp_snapshot", 0.0, .72, .85, "", False, False, "Keep fixture/dry-run coverage; activate only after approval, credential, terms/privacy, and output tests."), LearningProviderImpact("apify", "public_extraction_plan", 0.0, .35, .5, "live mode not enabled", True, True, "Keep plan-only and use manual imports for early screens."), LearningProviderImpact("manual_import", "early_screen", 0.0, .55, .9, "", False, False, "Use sanitized manual imports while live providers remain blocked."))


def _trustos_impacts(events: Sequence[LearningEvent]) -> tuple[LearningTrustOSImpact, ...]:
    counts: dict[str, int] = {}
    for event in events:
        for reason in event.failure_reasons:
            if reason == "trust_blocker": counts["missing client isolation"] = counts.get("missing client isolation", 0) + 1
            if reason == "provider_blocker": counts["terms/privacy or provider activation"] = counts.get("terms/privacy or provider activation", 0) + 1
            if reason == "missing_learning_capture": counts["missing learning capture"] = counts.get("missing learning capture", 0) + 1
    return tuple(LearningTrustOSImpact(blocker, count, ("attach the relevant TrustOS evidence requirement to the next decision",), ("reviewed control evidence", "Approval Ledger state"), .8) for blocker, count in sorted(counts.items()))


def _influences(events: Sequence[LearningEvent], rules: Sequence[LearningDoNotRepeatRule]) -> tuple[LearningDecisionInfluence, ...]:
    def build(action: str, candidate: str, positive: float, negative: float, blockers: Sequence[str], missing: Sequence[str], modifier: str, next_action: str) -> LearningDecisionInfluence:
        return LearningDecisionInfluence(action, candidate, "internal-companyos", positive, negative, tuple(blockers), tuple(missing), modifier, next_action)
    return (build("launch_ad_experiment", "portable-espresso-maker", 0.1, .9, ("previous poor creative angle and weak click-through",), ("previous learning capture",), "soft_block_until_learning_captured", "record a changed hypothesis and creative lesson"), build("generate_creative_batch", "portable-espresso-maker", .1, .85, ("missing learning capture",), ("prior iteration lesson",), "requires_learning_capture", "capture the losing angle and do-not-repeat rule"), build("run_frontier_llm_synthesis", "candidate-placeholder", .1, .9, ("frontier model waste on low-evidence work",), ("evidence threshold",), "hard_block_or_route_cheaper", "use algorithmic/local/cheap route unless evidence improves"), build("create_new_website", "portable-espresso-maker", .2, .7, ("prior landing-page fit is inconclusive",), ("page learning",), "soft_block_until_page_learning", "run one bounded page/offer iteration"), build("request_supplier_proof", "portable-espresso-maker", .75, .1, (), (), "prioritize_supplier_validation", "obtain supplier and shipping evidence"), build("scale_ad_budget", "mini-thermal-printer", .9, .1, (), (), "allow_controlled_scale", "scale within the approved increment and keep measuring"), build("generate_client_export", "candidate-placeholder", .4, .6, ("client isolation and redaction evidence required",), ("workspace review",), "requires_workspace_review", "complete leakage check and TrustOS approval"))


def _from_mapping(item: Mapping[str, Any], index: int) -> LearningEvent:
    event_type = str(item.get("event_type", "companyos_review")); outcome = str(item.get("outcome", "inconclusive")); failures = tuple(str(x) for x in item.get("failure_reasons", ())); successes = tuple(str(x) for x in item.get("success_reasons", ()))
    return _event(str(item.get("learning_event_id", f"fixture-event-{index}")), event_type, outcome, candidate=str(item.get("candidate_id", "candidate-placeholder")), failures=failures, successes=successes, action=str(item.get("action_taken", event_type)), cost=float(item.get("cost_estimate", 0.0)), confidence=float(item.get("confidence", .7)), visibility=str(item.get("client_visibility", "internal_only")), department=str(item.get("owner_department", "management")), statement=str(item.get("hypothesis", "Sanitized fixture hypothesis.")), influence=str(item.get("resource_governor_influence", "Record the result before the next decision.")))


def _load_events(context: Mapping[str, Any] | None) -> tuple[LearningEvent, ...]:
    if not context or not context.get("events"): return _default_events()
    return tuple(_from_mapping(item, index) for index, item in enumerate(context.get("events", ()), 1) if isinstance(item, Mapping))


def build_learning_ledger_report(*, generated_at: str = "offline-deterministic", context: Mapping[str, Any] | None = None, events: Sequence[LearningEvent] | None = None, event_type: str | None = None, event_types: Sequence[str] | None = None) -> LearningLedgerReport:
    """`event_types` (plural) filters by a set of types before any derived
    aggregate is computed, so lessons, do-not-repeat rules, iteration
    recommendations, impacts, influences, and the summary all stay
    consistent with the events actually reported. A caller that filtered
    events *after* building a full report would leave every aggregate
    describing events the report no longer shows."""
    context = context or {}; raw = tuple(events or _load_events(context))
    if event_type:
        if event_type not in EVENT_TYPES: raise ValueError("unsupported learning event type")
        raw = tuple(item for item in raw if item.event_type == event_type)
    if event_types:
        allowed = tuple(event_types)
        for candidate in allowed:
            if candidate not in EVENT_TYPES: raise ValueError("unsupported learning event type")
        raw = tuple(item for item in raw if item.event_type in set(allowed))
    rules = tuple(rule for index, event in enumerate(raw, 1) if (rule := _rule(event, index)) is not None)
    recommendations = tuple(_recommendation(event, index) for index, event in enumerate(raw, 1) if event.outcome in {"loss", "blocked", "inconclusive", "killed", "iterated", "needs_more_evidence"})
    results = tuple(LearningResult(f"result-{item.learning_event_id}", item.outcome, f"{item.event_type} recorded as {item.outcome}.", item.metrics, item.confidence) for item in raw)
    experiments = tuple(LearningExperiment(f"experiment-{item.learning_event_id}", item.hypothesis, item.action_taken, item.cost_estimate, max((metric.sample_size for metric in item.metrics), default=0), item.metrics[0].name if item.metrics else "primary_metric", item.metrics[0].target if item.metrics else None, item.metrics[0].target if item.metrics else None, "capture learning before iteration", 3, True, item.action_taken in {"launch_ad_experiment", "scale_ad_budget", "run_provider_data_pull", "generate_client_export"}, (item.learning_event_id,), item.outcome) for item in raw if item.event_type in {"ad_experiment", "creative_test", "landing_page_test", "site_funnel_test", "product_validation", "provider_run"})
    successes = [reason for item in raw for reason in item.success_reasons]; failures = [reason for item in raw for reason in item.failure_reasons]
    top_success = tuple(dict.fromkeys(successes))[:8]; top_failure = tuple(dict.fromkeys(failures))[:8]
    summary = LearningLedgerSummary(top_success, top_failure, tuple(item.condition for item in rules)[:8], tuple(item.recommendation for item in recommendations)[:8], tuple(item.blocker for item in _trustos_impacts(raw)), tuple(item.hypothesis.statement for item in raw if item.outcome == "win")[:5], tuple(item.condition for item in rules)[:5])
    return LearningLedgerReport("learning-ledger-v1", generated_at, raw, experiments, results, tuple(LearningLesson(f"lesson-{item.learning_event_id}", f"{item.event_type} lesson", "success" if item.outcome == "win" else "failure" if item.outcome in {"loss", "blocked", "killed"} else "iteration", item.resource_governor_influence, item.input_evidence_refs, item.confidence, item.client_visibility) for item in raw), rules, recommendations, _portfolio_impacts(raw), _model_impacts(raw), _provider_impacts(raw), _trustos_impacts(raw), _influences(raw, rules), summary, LearningLedgerSafetySummary(), "Attach captured lessons to the next Resource Governor decision; do not repeat blocked patterns without new evidence.")


__all__ = ["EVENT_TYPES", "OUTCOMES", "VISIBILITY", "FAILURE_REASONS", "SUCCESS_REASONS", "BLOCK_BEHAVIORS", "LearningLedgerReport", "LearningEvent", "LearningExperiment", "LearningHypothesis", "LearningMetric", "LearningResult", "LearningOutcome", "LearningAttribution", "LearningLesson", "LearningDoNotRepeatRule", "LearningIterationRecommendation", "LearningPortfolioImpact", "LearningModelRoutingImpact", "LearningProviderImpact", "LearningTrustOSImpact", "LearningDecisionInfluence", "LearningLedgerSummary", "LearningLedgerSafetySummary", "build_learning_ledger_report"]


@dataclass(frozen=True)
class LearningOutcome:
    """Validated outcome value with a stable class-level vocabulary."""

    outcome: str
    values: ClassVar[tuple[str, ...]] = OUTCOMES

    def __post_init__(self) -> None:
        if self.outcome not in self.values:
            raise ValueError("invalid learning outcome")

    def to_dict(self) -> dict[str, Any]:
        return {"outcome": self.outcome}
