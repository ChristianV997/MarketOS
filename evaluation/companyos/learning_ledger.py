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

import hashlib
import math
from dataclasses import dataclass
from typing import Any, ClassVar, Mapping, Sequence

EVENT_TYPES = ("product_validation", "supplier_validation", "consumer_attention_test", "creative_test", "ad_experiment", "landing_page_test", "site_funnel_test", "sales_outreach_test", "provider_run", "model_routing_decision", "security_scan", "trustos_review", "companyos_review", "portfolio_decision", "kill_decision", "scale_decision", "runaway_guard_event", "client_export_review")
OUTCOMES = ("win", "loss", "inconclusive", "killed", "scaled", "paused", "iterated", "blocked", "needs_more_evidence", "invalid_test")
VISIBILITY = ("internal_only", "workspace_only", "client_visible_summary", "aggregated_safe_summary", "blocked")
FAILURE_REASONS = ("weak_demand", "weak_supplier_feasibility", "poor_margin", "high_shipping_risk", "low_attention", "low_click_through", "weak_conversion_intent", "poor_offer", "poor_creative_angle", "audience_mismatch", "price_mismatch", "landing_page_mismatch", "trust_blocker", "provider_blocker", "budget_cap", "model_cost_too_high", "insufficient_sample", "invalid_test_design", "runaway_guard_triggered", "missing_learning_capture")
SUCCESS_REASONS = ("strong_demand", "strong_supplier_fit", "strong_attention_signal", "clear_pain_point", "strong_hook", "high_margin", "fast_shipping", "low_competition", "good_offer_market_fit", "good_creative_market_fit", "good_landing_page_fit", "low_cpa_projection", "strong_portfolio_fit", "trustos_ready", "provider_ready", "budget_efficient")
BLOCK_BEHAVIORS = ("warn", "soft_block", "hard_block", "requires_approval")
LEARNING_TYPES = ("product_validation", "supplier_validation", "creative_test", "ad_experiment", "landing_page_test", "sales_outreach", "provider_run", "model_routing", "security_scan", "trustos_review")
GOVERNOR_EVIDENCE_MODES = ("actual", "simulated", "unavailable", "not_run")


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
    sample_size: int | None
    source: str
    def __post_init__(self) -> None:
        if not self.metric_id or not self.name: raise ValueError("learning metric identity and name are required")
        if any(value is not None and (isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value)) for value in (self.value, self.target)): raise ValueError("learning metric values must be finite numbers")
        if self.sample_size is not None and (isinstance(self.sample_size, bool) or not isinstance(self.sample_size, int) or self.sample_size < 0): raise ValueError("learning metric sample size must be a non-negative integer")
        if self.name in {"evidence_value", "schema_quality"} and any(value is not None and not 0 <= value <= 1 for value in (self.value, self.target)): raise ValueError(f"learning metric {self.name} must be between zero and one")
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
    evidence_value: float | None
    schema_quality: float | None
    blocked_reason: str
    terms_privacy_blocker: bool | None
    output_contract_blocker: bool | None
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
    source_event_id: str = ""
    def to_dict(self) -> dict[str, Any]: return _clean(self)


@dataclass(frozen=True)
class LearningGovernorInfluence:
    """Self-contained handoff record for `derive_governor_influence`.

    This is deliberately a second, narrower contract than `LearningDecisionInfluence`.
    Every field here is derived from the actual events and do-not-repeat rules in
    the report passed in. It carries plain strings/floats/tuples only, so the
    Resource & Execution Governor can
    consume it (via `to_governor_context()`) without this module importing
    Governor types, and without the Governor importing this module's
    types.

    `supports_scale` and `conflicting_evidence` are informational only --
    nothing in this module or in `apply_learning_influence` ever reads
    them to unlock an outcome. Only the negative signals
    (`do_not_repeat_blocked`, `hold_or_avoid`, `trustos_recurrence_blocked`,
    `kill_blocks_resumption`) are wired to actually tighten a Governor
    request, and only by requiring learning capture -- never by touching
    budgets, quotas, TrustOS/workspace decisions, or approval state.
    `recommended_provider_id`/`avoid_provider_ids` and
    `recommended_model_tier` are read only when the Governor caller
    explicitly opts in, and even then only ever move planning *away* from
    a flagged-bad choice -- never toward an unverified one.

    `supports_scale` additionally requires average `confidence` at or
    above `MIN_SCALE_CONFIDENCE` (`low_confidence_evidence` reports when
    that threshold was the reason it was withheld) and a real
    `candidate_id` rather than the `PLACEHOLDER_CANDIDATE_ID` sentinel
    (`fixture_only_evidence`) -- repeated wins for an unspecified,
    fixture-only candidate are not evidence about any real decision.
    """
    action_type: str
    candidate_id: str
    workspace_id: str
    evidence_mode: str
    confidence: float
    recency_label: str
    provenance: tuple[str, ...]
    win_count: int
    loss_count: int
    supports_scale: bool
    hold_or_avoid: bool
    do_not_repeat_blocked: bool
    do_not_repeat_overridden: bool
    do_not_repeat_rule_ids: tuple[str, ...]
    trustos_recurrence_blocked: bool
    recommended_model_tier: str
    deprioritize: bool
    rationale: tuple[str, ...]
    kill_blocks_resumption: bool = False
    conflicting_evidence: bool = False
    recommended_provider_id: str = ""
    avoid_provider_ids: tuple[str, ...] = ()
    iteration_recommendation: str = ""
    excluded_stale_event_ids: tuple[str, ...] = ()
    fingerprint: str = ""
    low_confidence_evidence: bool = False
    fixture_only_evidence: bool = False
    advisory_rule_ids: tuple[str, ...] = ()
    def __post_init__(self) -> None:
        if self.evidence_mode not in GOVERNOR_EVIDENCE_MODES: raise ValueError("invalid governor evidence mode")
    def to_dict(self) -> dict[str, Any]: return _clean(self)
    def to_governor_context(self) -> dict[str, Any]:
        """The narrow subset `apply_learning_influence` actually reads.
        Kept smaller than `to_dict()` on purpose: candidate_id, provenance,
        confidence, iteration_recommendation, and rationale stay
        ledger-side observability, not Governor-side inputs."""
        return {"do_not_repeat_blocked": self.do_not_repeat_blocked, "hold_or_avoid": self.hold_or_avoid, "trustos_recurrence_blocked": self.trustos_recurrence_blocked, "kill_blocks_resumption": self.kill_blocks_resumption, "recommended_model_tier": self.recommended_model_tier, "recommended_provider_id": self.recommended_provider_id, "avoid_provider_ids": self.avoid_provider_ids}


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
    provider_id: str = ""
    def __post_init__(self) -> None:
        if self.event_type not in EVENT_TYPES or self.outcome not in OUTCOMES or self.client_visibility not in VISIBILITY: raise ValueError("invalid learning event vocabulary")
        if any(reason not in FAILURE_REASONS for reason in self.failure_reasons): raise ValueError("invalid failure reason")
        if any(reason not in SUCCESS_REASONS for reason in self.success_reasons): raise ValueError("invalid success reason")
        if isinstance(self.cost_estimate, bool) or not math.isfinite(self.cost_estimate) or self.cost_estimate < 0: raise ValueError("learning cost must be a finite non-negative number")
        if isinstance(self.confidence, bool) or not math.isfinite(self.confidence) or not 0 <= self.confidence <= 1: raise ValueError("learning confidence must be between zero and one")
    def to_dict(self) -> dict[str, Any]: return _clean(self)


@dataclass(frozen=True)
class LearningExperiment:
    experiment_id: str
    hypothesis: LearningHypothesis
    action_type: str
    budget_cap: float
    sample_size_target: int | None
    success_metric: str
    kill_threshold: float | None
    scale_threshold: float | None
    iteration_rule: str
    max_iterations: int
    learning_required: bool
    approval_required: bool
    event_refs: tuple[str, ...]
    status: str
    observed_sample_size: int | None = None
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
        lines += ["", "## Experiments", "", *[f"- `{item.experiment_id}`: {item.status}; metric `{item.success_metric}`; budget cap ${item.budget_cap:.2f}." for item in self.experiments], "", "## Wins and Losses", "", f"Success reasons: {', '.join(self.summary.top_success_reasons) or 'none'}.", f"Failure reasons: {', '.join(self.summary.top_failure_reasons) or 'none'}.", "", "## Kill / Scale Decisions", "", *[f"- {item.learning_event_id}: {item.outcome}; {item.resource_governor_influence}." for item in self.events if item.outcome in {"killed", "scaled"}], "", "## Do-Not-Repeat Rules", "", *[f"- **{item.severity} / {item.recommended_block_behavior}**: {item.condition}" for item in self.do_not_repeat_rules], "", "## Iteration Recommendations", "", *[f"- `{item.action_type}`: {item.recommendation}" for item in self.iteration_recommendations], "", "## Portfolio Learning", "", *[f"- `{item.portfolio_area}`: focus on {item.recommended_focus_area}; allocation: {item.recommended_allocation_change}." for item in self.portfolio_impacts], "", "## Model-Routing Learning", "", *[f"- `{item.task_type}` -> `{item.recommended_model_tier_next_time}`: {item.cost_savings_note}" for item in self.model_routing_impacts], "", "## Provider Learning", "", *[f"- `{item.provider_id}` / `{item.request_kind}`: evidence value {'not recorded' if item.evidence_value is None else f'{item.evidence_value:.2f}'}; {item.recommended_next_provider_action}." for item in self.provider_impacts], "", "## TrustOS / Security Learning", "", *[f"- `{item.blocker}` occurred {item.occurrences} time(s); next evidence: {', '.join(item.recommended_next_evidence)}." for item in self.trustos_impacts], "", "## Resource Governor Feedback", "", *[f"- `{item.action_type}`: modifier `{item.recommended_decision_modifier}`; {item.recommended_next_action}." for item in self.decision_influences], "", "## Safety Boundaries", "", "No database writes, model/provider calls, ads, publishing, orders, payments, messaging, auth, tenants, real client data, raw prompts, real metrics, or artifacts by default.", "", "## Next Best Action", "", self.next_best_action, ""]
        return "\n".join(lines)


def _hypothesis(event_type: str, statement: str) -> LearningHypothesis:
    return LearningHypothesis(f"hypothesis-{event_type}", statement, ("metric reaches target", "evidence remains valid"), "primary_metric", None)


def _metric(name: str, value: float | None, target: float | None, sample: int) -> LearningMetric:
    return LearningMetric(f"metric-{name}", name, value, target, "ratio", sample, "sanitized_fixture")


def _event(event_id: str, event_type: str, outcome: str, *, candidate: str = "candidate-placeholder", failures: Sequence[str] = (), successes: Sequence[str] = (), action: str | None = None, cost: float = 0.0, confidence: float = .8, metrics: Sequence[LearningMetric] = (), visibility: str = "internal_only", department: str = "management", provider: str = "", workspace_id: str = "internal-companyos", statement: str = "Tested a bounded hypothesis with sanitized evidence.", influence: str = "Record the outcome and use it in the next bounded decision.") -> LearningEvent:
    return LearningEvent(event_id, f"decision-{event_id}", "fixture_learning", department, workspace_id, visibility, event_type, _hypothesis(event_type, statement), (f"evidence-{event_id}",), action or event_type, cost, {"resource": "fixture_budget", "cap": cost}, tuple(metrics), outcome, confidence, tuple(failures), tuple(successes), (), (), (), (), "portfolio lesson captured", influence, "offline-deterministic", department, outcome in {"blocked", "loss", "killed"}, candidate, provider)


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
        _event("event-model-algorithmic", "model_routing_decision", "win", action="run_algorithmic_scoring", cost=0, successes=("budget_efficient",), influence="Retain deterministic scoring for repeatable rules."),
        _event("event-model-human-review", "model_routing_decision", "needs_more_evidence", action="run_human_review", failures=("insufficient_sample",), influence="Obtain the missing evidence before a professional conclusion."),
        _event("event-provider-blocked", "provider_run", "blocked", action="run_provider_data_pull", provider="dataforseo", cost=5, failures=("provider_blocker",), influence="Complete terms/privacy and output-contract evidence before live consideration."),
        _event("event-provider-dry-run", "provider_run", "win", action="run_provider_data_pull", provider="dataforseo", cost=0, metrics=(LearningMetric("metric-dataforseo-evidence", "evidence_value", .72, None, "ratio", None, "sanitized_fixture"), LearningMetric("metric-dataforseo-schema", "schema_quality", .85, None, "ratio", None, "sanitized_fixture")), successes=("provider_ready",), influence="Keep DataForSEO in fixture/dry-run mode until activation gates pass."),
        _event("event-provider-apify-blocked", "provider_run", "blocked", action="plan_public_extraction", provider="apify", metrics=(LearningMetric("metric-apify-evidence", "evidence_value", .35, None, "ratio", None, "sanitized_fixture"), LearningMetric("metric-apify-schema", "schema_quality", .5, None, "ratio", None, "sanitized_fixture")), failures=("provider_blocker",), influence="Keep this provider plan-only until its blocker is resolved."),
        _event("event-provider-manual-screen", "provider_run", "win", action="consume_manual_import", provider="manual_import", metrics=(LearningMetric("metric-manual-evidence", "evidence_value", .55, None, "ratio", None, "sanitized_fixture"), LearningMetric("metric-manual-schema", "schema_quality", .9, None, "ratio", None, "sanitized_fixture")), successes=("provider_ready",), influence="Use sanitized manual imports for early screening only."),
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


def _has_observed_metric_value(event: LearningEvent) -> bool:
    return any(metric.value is not None for metric in event.metrics)


def _recommendation(event: LearningEvent, index: int) -> LearningIterationRecommendation:
    """Iteration-recommendation action/text/expected-signal, per
    `event.failure_reasons[0]`. `poor_offer`, `poor_margin`, `trust_blocker`,
    and `invalid_test_design` are explicit entries here (previously only
    `poor_margin`/`trust_blocker` had do-not-repeat rule text, not
    iteration-recommendation text, and `poor_offer`/`invalid_test_design`
    had neither) -- covering this mission's required "offer", "economics",
    and "TrustOS evidence" iteration-recommendation categories."""
    mapping = {"low_click_through": ("generate_creative_batch", "change the hook or audience while preserving the validated problem", "attention signal"), "landing_page_mismatch": ("generate_site_draft", "test a clearer offer/page structure before more traffic", "page conversion fit"), "weak_supplier_feasibility": ("request_supplier_proof", "obtain supplier, shipping, and landed-cost evidence", "supplier feasibility"), "model_cost_too_high": ("run_cheap_llm_task", "route routine work to algorithmic/local/cheap tiers", "quality at lower cost"), "provider_blocker": ("run_provider_data_pull", "complete terms/privacy and output-contract review in dry-run mode", "provider readiness"), "missing_learning_capture": ("run_companyos_review", "record the prior lesson before another experiment", "learning completeness"), "insufficient_sample": (event.action_taken, "collect a bounded sample without changing external execution mode", "evidence strength"), "poor_offer": ("iterate_offer_draft", "test a clearer value proposition, price, or bundle before more traffic", "offer market fit"), "poor_margin": ("run_unit_economics_review", "revisit landed cost, price, or fee assumptions before promoting", "economics viability"), "trust_blocker": ("run_trustos_control_plane", "attach TrustOS evidence and isolation review before the export", "TrustOS readiness"), "invalid_test_design": ("run_companyos_review", "define a hypothesis, kill rule, and sample-size target before relaunching", "experiment design quality")}
    if not event.failure_reasons:
        action = "run_companyos_review"
        if event.outcome in {"loss", "blocked", "killed"}:
            recommendation = "record the failure reason and supporting evidence before selecting an iteration"
            expected = "failure cause and next-step evidence"
            rationale = f"Prior event `{event.learning_event_id}` recorded `{event.outcome}` without a failure reason; the cause is unknown."
        elif _has_observed_metric_value(event):
            recommendation = "review the recorded outcome metrics and supporting evidence before selecting an iteration"
            expected = "interpretation of recorded outcome metrics and next-step evidence"
            rationale = f"Prior event `{event.learning_event_id}` recorded `{event.outcome}` without a failure reason; outcome metrics were recorded and need interpretation."
        else:
            recommendation = "record the missing outcome metrics and supporting evidence before selecting an iteration"
            expected = "outcome metric and next-step evidence"
            rationale = f"Prior event `{event.learning_event_id}` recorded `{event.outcome}` without a failure reason or outcome metric."
        return LearningIterationRecommendation(f"iteration-{index}-{event.learning_event_id}", event.learning_event_id, action, recommendation, rationale, expected, "high", event.client_visibility in {"client_visible_summary", "aggregated_safe_summary"})
    reason = event.failure_reasons[0]
    action, recommendation, expected = mapping.get(reason, (event.action_taken, "repeat only with changed evidence and the prior lesson attached", "decision quality"))
    return LearningIterationRecommendation(f"iteration-{index}-{event.learning_event_id}", event.learning_event_id, action, recommendation, f"Prior event `{event.learning_event_id}` recorded failure reason `{reason}`.", expected, "high" if event.outcome in {"loss", "blocked", "killed"} else "medium", event.client_visibility in {"client_visible_summary", "aggregated_safe_summary"})


def _portfolio_impacts(events: Sequence[LearningEvent]) -> tuple[LearningPortfolioImpact, ...]:
    areas = {
        "product_validation": "product-category",
        "portfolio_decision": "product-category",
        "supplier_validation": "supplier-feasibility",
        "creative_test": "creative-hooks",
        "ad_experiment": "creative-hooks",
        "consumer_attention_test": "consumer-attention",
        "landing_page_test": "landing-pages",
        "site_funnel_test": "landing-pages",
        "sales_outreach_test": "sales-outreach",
    }
    grouped: dict[str, list[LearningEvent]] = {}
    for event in events:
        area = areas.get(event.event_type)
        if area:
            grouped.setdefault(area, []).append(event)

    impacts = []
    for area, records in sorted(grouped.items()):
        positive = [
            f"{event.candidate_id} ({event.learning_event_id}): {reason.replace('_', ' ')}"
            for event in records
            for reason in event.success_reasons
        ]
        negative = [
            f"{event.candidate_id} ({event.learning_event_id}): {reason.replace('_', ' ')}"
            for event in records
            for reason in event.failure_reasons
        ]
        if not positive:
            positive = [
                f"{event.candidate_id} ({event.learning_event_id}): recorded {event.outcome}"
                for event in records
                if event.outcome in {"win", "scaled"}
            ]
        if not negative:
            negative = [
                f"{event.candidate_id} ({event.learning_event_id}): recorded outcome {event.outcome}"
                for event in records
                if event.outcome in {"loss", "blocked", "killed"}
            ]
        if positive and negative:
            allocation = "Reconcile the recorded positive and negative signals before the next allocation review."
        elif positive:
            allocation = "Carry the recorded signals into a bounded planning review; no scale authority is implied."
        elif negative:
            allocation = "Address the recorded blockers before repeating; no spend or launch authority is implied."
        else:
            allocation = "No directional outcome is recorded; collect evidence before allocation."
        focus = sorted({reason.replace("_", " ") for event in records for reason in (*event.success_reasons, *event.failure_reasons)})
        if not focus:
            focus = sorted({event.event_type.replace("_", " ") for event in records})
        impacts.append(LearningPortfolioImpact(
            area,
            tuple(sorted(set(positive))),
            tuple(sorted(set(negative))),
            allocation,
            "Review only candidates linked to recorded failures before repeating." if negative else "No recorded failure supports deprioritization.",
            ", ".join(focus),
            round(sum(event.confidence for event in records) / len(records), 4),
        ))
    return tuple(impacts)


def _model_impacts(events: Sequence[LearningEvent]) -> tuple[LearningModelRoutingImpact, ...]:
    route_ids = {"run_frontier_llm_synthesis": "frontier-reasoning", "run_cheap_llm_task": "cheap-api", "run_algorithmic_scoring": "algorithmic", "run_human_review": "human-review"}
    grouped: dict[str, list[LearningEvent]] = {}
    for event in events:
        if event.event_type == "model_routing_decision":
            grouped.setdefault(route_ids.get(event.action_taken, event.action_taken), []).append(event)

    impacts = []
    for route_id, records in sorted(grouped.items()):
        outcomes = sorted({event.outcome for event in records})
        failures = sorted({reason for event in records for reason in event.failure_reasons})
        successes = sorted({reason for event in records for reason in event.success_reasons})
        if len(outcomes) > 1:
            next_tier = "review_conflicting_outcomes"
            cost_note = f"Conflicting outcomes were recorded for {route_id} ({', '.join(event.learning_event_id for event in records)}); reconcile them before choosing a route."
        elif "model_cost_too_high" in failures:
            next_tier = "algorithmic_or_cheap_llm"
            cost_note = f"Recorded model-cost failure in {', '.join(event.learning_event_id for event in records if 'model_cost_too_high' in event.failure_reasons)}; consider a cheaper planning route before repeating."
        elif "budget_efficient" in successes and "win" in outcomes:
            next_tier = "cheap_llm" if route_id == "cheap-api" else "algorithmic" if route_id == "algorithmic" else "retain_recorded_route"
            cost_note = f"Recorded budget-efficient outcome in {', '.join(event.learning_event_id for event in records if 'budget_efficient' in event.success_reasons)}; keep as planning evidence only."
        elif route_id == "human-review" and "needs_more_evidence" in outcomes:
            next_tier = "human_review"
            cost_note = "Human review was recorded, but the outcome still needs more evidence; no professional conclusion is implied."
        else:
            next_tier = "review_before_repeating"
            cost_note = "No cost-specific model evidence was recorded."
        risk_note = f"Recorded failure reasons: {', '.join(failures)}." if failures else "No model-quality risk reason was recorded."
        impacts.append(LearningModelRoutingImpact(
            route_id,
            ", ".join(sorted({event.event_type for event in records})),
            outcomes[0] if len(outcomes) == 1 else "mixed",
            next_tier,
            cost_note,
            risk_note,
            round(sum(event.confidence for event in records) / len(records), 4),
        ))
    return tuple(impacts)


def _provider_impacts(events: Sequence[LearningEvent]) -> tuple[LearningProviderImpact, ...]:
    grouped: dict[str, list[LearningEvent]] = {}
    for event in events:
        provider_id = event.provider_id.strip()
        if event.event_type == "provider_run" and provider_id:
            grouped.setdefault(provider_id, []).append(event)

    def observed_metric(records: Sequence[LearningEvent], name: str) -> float | None:
        values = [metric.value for event in records for metric in event.metrics if metric.name == name and metric.value is not None]
        return round(sum(values) / len(values), 4) if values else None

    impacts = []
    for provider_id, records in sorted(grouped.items()):
        blockers = sorted({reason for event in records for reason in event.failure_reasons})
        if provider_id == "apify" and blockers:
            action = f"Keep this provider plan-only until recorded blocker(s) ({', '.join(blockers)}) are resolved; no live call is authorized."
        elif provider_id == "manual_import" and any(event.outcome == "win" for event in records):
            action = "Use the sanitized manual-import fixture for early screening only; do not infer live-provider readiness."
        elif blockers:
            action = f"Resolve recorded blocker(s) ({', '.join(blockers)}) in offline evidence before any provider activation; no live call is authorized."
        elif any(event.outcome == "win" for event in records):
            action = "Retain as a fixture-backed provider lesson only; no live readiness is implied."
        else:
            action = "Capture a provider outcome and supporting evidence before recommending another route."
        request_kinds = sorted({event.action_taken or event.event_type for event in records})
        blocked_reason = "; ".join(blockers)
        if not blocked_reason and any(event.outcome in {"loss", "blocked", "killed"} for event in records):
            blocked_reason = "negative outcome recorded without a specific blocker"
        impacts.append(LearningProviderImpact(
            provider_id,
            ", ".join(request_kinds),
            max((event.cost_estimate for event in records), default=0.0),
            observed_metric(records, "evidence_value"),
            observed_metric(records, "schema_quality"),
            blocked_reason,
            None,
            None,
            action,
        ))
    return tuple(impacts)


def _trustos_impacts(events: Sequence[LearningEvent]) -> tuple[LearningTrustOSImpact, ...]:
    grouped: dict[str, list[LearningEvent]] = {}
    reason_to_blocker = {"trust_blocker": "missing client isolation", "provider_blocker": "terms/privacy or provider activation", "missing_learning_capture": "missing learning capture"}
    for event in events:
        blockers = {reason_to_blocker[reason] for reason in event.failure_reasons if reason in reason_to_blocker}
        for blocker in blockers:
            grouped.setdefault(blocker, []).append(event)
    return tuple(LearningTrustOSImpact(blocker, len(records), ("attach the relevant TrustOS evidence requirement to the next decision",), ("reviewed control evidence", "Approval Ledger state"), round(sum(event.confidence for event in records) / len(records), 4)) for blocker, records in sorted(grouped.items()))


def _influences(events: Sequence[LearningEvent], rules: Sequence[LearningDoNotRepeatRule], recommendations: Sequence[LearningIterationRecommendation]) -> tuple[LearningDecisionInfluence, ...]:
    rules_by_event: dict[str, list[LearningDoNotRepeatRule]] = {}
    for rule in rules:
        rules_by_event.setdefault(rule.source_event_id, []).append(rule)
    recommendations_by_event = {item.source_event_id: item for item in recommendations}

    influences = []
    for event in events:
        event_rules = rules_by_event.get(event.learning_event_id, [])
        event_recommendation = recommendations_by_event.get(event.learning_event_id)
        positive = event.confidence if event.outcome in {"win", "scaled"} else 0.0
        negative = event.confidence if event.outcome in {"loss", "blocked", "killed"} or event.failure_reasons else 0.0
        blockers = tuple(rule.condition for rule in event_rules)
        missing = []
        if event.outcome in {"loss", "blocked", "killed"} and not event.failure_reasons:
            missing.append("failure cause was not recorded")
        if "missing_learning_capture" in event.failure_reasons:
            missing.append("previous iteration lesson was not captured")
        if event.outcome in {"inconclusive", "needs_more_evidence", "invalid_test"} and not _has_observed_metric_value(event):
            missing.append("outcome metrics were not recorded")

        if "model_cost_too_high" in event.failure_reasons:
            modifier = "route_to_cheaper_tier_before_repeat"
        elif "missing_learning_capture" in event.failure_reasons or {"poor_creative_angle", "low_click_through"} & set(event.failure_reasons):
            modifier = "soft_block_until_learning_is_captured"
        elif any(rule.recommended_block_behavior in {"hard_block", "requires_approval"} for rule in event_rules):
            modifier = "hard_block_recorded_pattern"
        elif event_rules:
            modifier = "soft_block_recorded_pattern"
        elif positive and negative:
            modifier = "conflicting_recorded_signals_require_review"
        elif event.outcome == "scaled":
            modifier = "recorded_scale_outcome_only_existing_gates_apply"
        elif positive:
            modifier = "recorded_positive_signal_only"
        elif negative:
            modifier = "review_recorded_failure_before_repeat"
        else:
            modifier = "collect_more_evidence_before_change"

        if event_recommendation:
            next_action = event_recommendation.recommendation
        elif event.outcome == "scaled":
            next_action = "Review the recorded scale outcome under existing Resource Governor gates before another increment."
        elif positive:
            next_action = "Carry the recorded success reasons into a bounded hypothesis; no execution authorization is implied."
        else:
            next_action = "Capture missing outcome evidence before selecting another iteration."
        influences.append(LearningDecisionInfluence(
            event.action_taken,
            event.candidate_id,
            event.workspace_id,
            positive,
            negative,
            blockers,
            tuple(missing),
            modifier,
            next_action,
            event.learning_event_id,
        ))
    return tuple(influences)


_MAX_MATCHING_EVENTS = 25
MIN_SCALE_CONFIDENCE = 0.6
PLACEHOLDER_CANDIDATE_ID = "candidate-placeholder"


def _governor_influence_fingerprint(*parts: Any) -> str:
    """A stable, deterministic identity for one `LearningGovernorInfluence`
    -- stdlib `hashlib` only, no new dependency. `repr()` of the plain
    strings/bools/floats/tuples used here is stable within a Python
    version, which is all determinism this offline module ever promises
    elsewhere (see `generated_at`)."""
    canonical = "|".join(repr(part) for part in parts)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def derive_governor_influence(report: "LearningLedgerReport", *, action_type: str, candidate_id: str = "candidate-placeholder", workspace_id: str = "internal-companyos", proposed_hypothesis: str = "", stale_event_ids: Sequence[str] = ()) -> LearningGovernorInfluence:
    """Derive a `LearningGovernorInfluence` for one action/candidate pair
    from a real, already-built `LearningLedgerReport` -- the events and do-not-repeat rules the report actually contains. Its portfolio, model, provider, and decision summaries are likewise derived from those records.

    Every match (events, do-not-repeat rules) is scoped to `workspace_id`
    first, always -- a lesson recorded under one workspace can never
    influence a decision in another, even when action_type and
    candidate_id happen to coincide. Matching then prefers events for this
    exact `candidate_id`; if none exist, it falls back to every event
    sharing `action_type` *within the same workspace* (a general,
    not-candidate-specific lesson) and records that in `recency_label`.
    No matching event at all yields `evidence_mode="not_run"` and every
    boolean signal `False` -- a caller with nothing on record gets no
    influence, by construction.

    `stale_event_ids` lets a caller declare specific events expired
    (e.g. by a retention policy this offline module has no clock to
    compute itself) -- they are excluded from every computation below,
    not just flagged, so stale evidence (positive or negative) cannot
    shape the result. Matching events are also capped at
    `_MAX_MATCHING_EVENTS`, keeping the influence a bounded-size record
    regardless of ledger history length.

    Positive evidence (`supports_scale`) is computed but never consumed by
    `apply_learning_influence`: only repeated failure, a single kill, an
    unresolved do-not-repeat rule, or a recurring TrustOS/security blocker
    ever tighten a Governor request, and only via the existing
    `previous_learning_required` gate `evaluate_execution_request` already
    enforces. Conflicting evidence (both wins and losses for the same
    scope) is flagged explicitly and can never produce `supports_scale`.
    """
    workspace_events = tuple(event for event in report.events if event.workspace_id == workspace_id)
    candidate_events = tuple(event for event in workspace_events if event.action_taken == action_type and event.candidate_id == candidate_id)
    same_workspace_match = candidate_events or tuple(event for event in workspace_events if event.action_taken == action_type)
    excluded_stale_event_ids = tuple(event.learning_event_id for event in same_workspace_match if event.learning_event_id in stale_event_ids)
    matching_events = tuple(event for event in same_workspace_match if event.learning_event_id not in stale_event_ids)[-_MAX_MATCHING_EVENTS:]
    if not matching_events:
        return LearningGovernorInfluence(action_type, candidate_id, workspace_id, "not_run", 0.0, "no_matching_event", (), 0, 0, False, False, False, False, (), False, "", False, ("no learning event references this action",), excluded_stale_event_ids=excluded_stale_event_ids, fingerprint=_governor_influence_fingerprint(action_type, candidate_id, workspace_id, "not_run", excluded_stale_event_ids))
    outcomes = [event.outcome for event in matching_events]
    wins = outcomes.count("win")
    losses = sum(1 for outcome in outcomes if outcome in {"loss", "blocked", "killed"})
    conflicting_evidence = wins > 0 and losses > 0
    ambiguous_only = all(outcome in {"inconclusive", "needs_more_evidence", "invalid_test"} for outcome in outcomes)
    evidence_mode = "unavailable" if ambiguous_only else "simulated"
    confidence = round(sum(event.confidence for event in matching_events) / len(matching_events), 4)
    provenance = tuple(event.learning_event_id for event in matching_events)
    recency_label = "current_fixture_cycle" if candidate_events else "action_type_only_match"

    events_by_id = {event.learning_event_id: event for event in workspace_events}
    matching_rules = tuple(rule for rule in report.do_not_repeat_rules if action_type in rule.applies_to_action_types and rule.source_event_id in events_by_id)
    # Severity-aware, matching this contract's own BLOCK_BEHAVIORS ladder
    # (warn < soft_block/hard_block/requires_approval): a "warn"-severity
    # rule is recorded and surfaced, but -- unlike the others -- never
    # forces previous_learning_required on its own. No rule in this
    # module's own fixtures currently reaches "warn", but the field is
    # part of the existing contract's vocabulary and a future one might.
    blocking_rules = tuple(rule for rule in matching_rules if rule.recommended_block_behavior != "warn")
    advisory_rules = tuple(rule for rule in matching_rules if rule.recommended_block_behavior == "warn")
    do_not_repeat_present = bool(blocking_rules)
    do_not_repeat_overridden = do_not_repeat_present and bool(proposed_hypothesis.strip())
    do_not_repeat_blocked = do_not_repeat_present and not do_not_repeat_overridden

    trustos_blocker_count = sum(1 for event in matching_events if event.outcome == "blocked" and "trust_blocker" in event.failure_reasons)
    trustos_recurrence_blocked = trustos_blocker_count >= 2

    kill_blocks_resumption = any(event.outcome == "killed" for event in matching_events)
    hold_or_avoid = losses >= 2
    clean_repeated_wins = wins >= 2 and losses == 0 and not conflicting_evidence and not trustos_recurrence_blocked and not do_not_repeat_blocked and not kill_blocks_resumption
    low_confidence_evidence = confidence < MIN_SCALE_CONFIDENCE
    fixture_only_evidence = candidate_id == PLACEHOLDER_CANDIDATE_ID
    supports_scale = clean_repeated_wins and not low_confidence_evidence and not fixture_only_evidence

    recommended_model_tier = ""; deprioritize = False
    if action_type == "run_frontier_llm_synthesis" and any("model_cost_too_high" in event.failure_reasons for event in matching_events):
        recommended_model_tier = "cheap_llm"; deprioritize = True
    elif action_type == "run_cheap_llm_task" and wins and not losses:
        recommended_model_tier = "cheap_llm"

    avoid_provider_ids = tuple(sorted({event.provider_id.strip() for event in matching_events if event.event_type == "provider_run" and event.provider_id.strip() and "provider_blocker" in event.failure_reasons}))
    ready_provider_ids = tuple(sorted({event.provider_id.strip() for event in matching_events if event.event_type == "provider_run" and event.provider_id.strip() and event.outcome == "win"} - set(avoid_provider_ids)))
    recommended_provider_id = ready_provider_ids[0] if ready_provider_ids else ""
    if avoid_provider_ids: deprioritize = True

    matching_recommendations = tuple(rec for rec in report.iteration_recommendations if rec.action_type == action_type and rec.source_event_id in events_by_id)
    iteration_recommendation = matching_recommendations[0].recommendation if matching_recommendations else ""

    rationale: list[str] = []
    if do_not_repeat_blocked: rationale.append(f"{len(blocking_rules)} do-not-repeat rule(s) apply to {action_type} and no new hypothesis was supplied")
    if do_not_repeat_overridden: rationale.append(f"{len(blocking_rules)} do-not-repeat rule(s) matched but were overridden by an explicit new hypothesis")
    if advisory_rules: rationale.append(f"{len(advisory_rules)} warn-severity do-not-repeat rule(s) apply to {action_type} but do not force learning capture")
    if kill_blocks_resumption: rationale.append(f"a kill decision was recorded for {action_type} and blocks automatic resumption")
    if hold_or_avoid: rationale.append(f"{losses} matching failed/blocked/killed event(s) recorded for {action_type}")
    if conflicting_evidence: rationale.append(f"{wins} win(s) and {losses} failure(s) recorded for the same action/candidate -- treated as inconclusive, not scale-supporting")
    if trustos_recurrence_blocked: rationale.append("a recurring TrustOS/security blocker was recorded for this action and remains a hard blocker")
    if clean_repeated_wins and low_confidence_evidence: rationale.append(f"{wins} matching win(s) recorded but average confidence {confidence} is below the {MIN_SCALE_CONFIDENCE} scale-authorization threshold")
    if clean_repeated_wins and fixture_only_evidence: rationale.append("matching evidence is only for the placeholder candidate, not a specific candidate -- scale is withheld")
    if supports_scale: rationale.append(f"{wins} matching win(s) recorded with no offsetting failure")
    if recommended_model_tier: rationale.append(f"model lesson recommends the {recommended_model_tier} tier as planning metadata only")
    if avoid_provider_ids: rationale.append(f"provider lesson flags {', '.join(avoid_provider_ids)} to avoid as planning metadata only")
    if recommended_provider_id: rationale.append(f"provider lesson prefers {recommended_provider_id} as planning metadata only")
    if excluded_stale_event_ids: rationale.append(f"{len(excluded_stale_event_ids)} caller-declared stale event(s) were excluded from this evidence")
    if not rationale: rationale.append("no actionable learning signal beyond the matched evidence")

    advisory_rule_ids = tuple(rule.rule_id for rule in advisory_rules)
    fingerprint = _governor_influence_fingerprint(action_type, candidate_id, workspace_id, evidence_mode, wins, losses, supports_scale, hold_or_avoid, do_not_repeat_blocked, do_not_repeat_overridden, tuple(rule.rule_id for rule in blocking_rules), advisory_rule_ids, trustos_recurrence_blocked, kill_blocks_resumption, conflicting_evidence, low_confidence_evidence, fixture_only_evidence, recommended_model_tier, recommended_provider_id, avoid_provider_ids, excluded_stale_event_ids)
    return LearningGovernorInfluence(action_type, candidate_id, workspace_id, evidence_mode, confidence, recency_label, provenance, wins, losses, supports_scale, hold_or_avoid, do_not_repeat_blocked, do_not_repeat_overridden, tuple(rule.rule_id for rule in blocking_rules), bool(trustos_recurrence_blocked), recommended_model_tier, deprioritize, tuple(rationale), kill_blocks_resumption=kill_blocks_resumption, conflicting_evidence=conflicting_evidence, recommended_provider_id=recommended_provider_id, avoid_provider_ids=avoid_provider_ids, iteration_recommendation=iteration_recommendation, excluded_stale_event_ids=excluded_stale_event_ids, fingerprint=fingerprint, low_confidence_evidence=low_confidence_evidence, fixture_only_evidence=fixture_only_evidence, advisory_rule_ids=advisory_rule_ids)


def _optional_metric_float(metric: Mapping[str, Any], field: str) -> float | None:
    value = metric.get(field)
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError(f"learning metric {field} must be numeric")
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"learning metric {field} must be numeric") from exc
    if not math.isfinite(parsed):
        raise ValueError(f"learning metric {field} must be finite")
    return parsed


def _optional_metric_sample_size(metric: Mapping[str, Any]) -> int | None:
    value = metric.get("sample_size")
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError("learning metric sample_size must be an integer")
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("learning metric sample_size must be an integer") from exc
    if str(value).strip() not in {str(parsed), f"{parsed}.0"} or parsed < 0:
        raise ValueError("learning metric sample_size must be a non-negative integer")
    return parsed


def _mapping_metrics(item: Mapping[str, Any], event_id: str) -> tuple[LearningMetric, ...]:
    raw_metrics = item.get("metrics", ())
    if raw_metrics is None:
        return ()
    if not isinstance(raw_metrics, Sequence) or isinstance(raw_metrics, (str, bytes)):
        raise ValueError("learning event metrics must be a sequence")
    metrics: list[LearningMetric] = []
    for index, raw_metric in enumerate(raw_metrics, 1):
        if isinstance(raw_metric, LearningMetric):
            metrics.append(raw_metric)
            continue
        if not isinstance(raw_metric, Mapping):
            raise ValueError("learning event metrics must contain mappings")
        name = str(raw_metric.get("name", "")).strip()
        if not name:
            raise ValueError("learning metric name is required")
        raw_metric_id = raw_metric.get("metric_id")
        metric_id = f"metric-{event_id}-{index}-{name}" if raw_metric_id is None or not str(raw_metric_id).strip() else str(raw_metric_id).strip()
        metric_value = _optional_metric_float(raw_metric, "value")
        metric_target = _optional_metric_float(raw_metric, "target")
        if name in {"evidence_value", "schema_quality"} and any(value is not None and not 0 <= value <= 1 for value in (metric_value, metric_target)):
            raise ValueError(f"learning metric {name} must be between zero and one")
        raw_unit = raw_metric.get("unit")
        unit = "unknown" if raw_unit is None or not str(raw_unit).strip() else str(raw_unit).strip()
        raw_source = raw_metric.get("source")
        source = "fixture" if raw_source is None or not str(raw_source).strip() else str(raw_source).strip()
        metrics.append(LearningMetric(
            metric_id,
            name,
            metric_value,
            metric_target,
            unit,
            _optional_metric_sample_size(raw_metric),
            source,
        ))
    return tuple(metrics)


def _event_float(item: Mapping[str, Any], field: str, default: float) -> float:
    value = item.get(field, default)
    if isinstance(value, bool):
        raise ValueError(f"learning event {field} must be numeric")
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"learning event {field} must be numeric") from exc
    if not math.isfinite(parsed):
        raise ValueError(f"learning event {field} must be finite")
    return parsed


def _from_mapping(item: Mapping[str, Any], index: int) -> LearningEvent:
    if "learning_event_id" in item:
        raw_event_id = item["learning_event_id"]
        event_id = str(raw_event_id)
        if raw_event_id is None or not event_id.strip():
            raise ValueError("learning event identity must be a non-empty string")
    else:
        event_id = f"fixture-event-{index}"
    raw_event_type = item.get("event_type")
    event_type = "companyos_review" if raw_event_type is None or not str(raw_event_type).strip() else str(raw_event_type).strip()
    raw_outcome = item.get("outcome")
    outcome = "inconclusive" if raw_outcome is None or not str(raw_outcome).strip() else str(raw_outcome).strip()
    raw_failures = item.get("failure_reasons")
    failures = tuple(str(x) for x in raw_failures) if raw_failures is not None else ()
    raw_successes = item.get("success_reasons")
    successes = tuple(str(x) for x in raw_successes) if raw_successes is not None else ()
    raw_candidate = item.get("candidate_id")
    candidate = "candidate-placeholder" if raw_candidate is None or not str(raw_candidate).strip() else str(raw_candidate).strip()
    raw_action = item.get("action_taken")
    action = event_type if raw_action is None or not str(raw_action).strip() else str(raw_action).strip()
    raw_provider = item.get("provider_id")
    provider = "" if raw_provider is None else str(raw_provider).strip()
    raw_visibility = item.get("client_visibility")
    visibility = "internal_only" if raw_visibility is None or not str(raw_visibility).strip() else str(raw_visibility).strip()
    raw_department = item.get("owner_department")
    department = "management" if raw_department is None or not str(raw_department).strip() else str(raw_department).strip()
    raw_workspace = item.get("workspace_id")
    workspace_id = "internal-companyos" if raw_workspace is None or not str(raw_workspace).strip() else str(raw_workspace).strip()
    raw_statement = item.get("hypothesis")
    statement = "Sanitized fixture hypothesis." if raw_statement is None or not str(raw_statement).strip() else str(raw_statement).strip()
    raw_influence = item.get("resource_governor_influence")
    influence = "Record the result before the next decision." if raw_influence is None or not str(raw_influence).strip() else str(raw_influence).strip()
    return _event(event_id, event_type, outcome, candidate=candidate, failures=failures, successes=successes, action=action, cost=_event_float(item, "cost_estimate", 0.0), confidence=_event_float(item, "confidence", .7), metrics=_mapping_metrics(item, event_id), visibility=visibility, department=department, provider=provider, workspace_id=workspace_id, statement=statement, influence=influence)


def _load_events(context: Mapping[str, Any] | None) -> tuple[LearningEvent, ...]:
    if context is None or "events" not in context: return _default_events()
    items = context["events"]
    if not isinstance(items, Sequence) or isinstance(items, (str, bytes)): raise ValueError("learning events must be a sequence")
    if any(not isinstance(item, Mapping) for item in items): raise ValueError("learning events must contain mappings")
    return tuple(_from_mapping(item, index) for index, item in enumerate(items, 1))


def _canonical_events(events: Sequence[LearningEvent]) -> tuple[LearningEvent, ...]:
    by_id: dict[str, LearningEvent] = {}
    for event in events:
        event_id = event.learning_event_id
        if not isinstance(event_id, str) or not event_id.strip(): raise ValueError("learning event identity must be a non-empty string")
        previous = by_id.get(event_id)
        if previous is not None and previous != event:
            raise ValueError(f"conflicting learning event identity: {event_id}")
        by_id[event_id] = event
    return tuple(by_id[event_id] for event_id in sorted(by_id))


def build_learning_ledger_report(*, generated_at: str = "offline-deterministic", context: Mapping[str, Any] | None = None, events: Sequence[LearningEvent] | None = None, event_type: str | None = None, event_types: Sequence[str] | None = None) -> LearningLedgerReport:
    """`event_types` (plural) filters by a set of types before any derived
    aggregate is computed, so lessons, do-not-repeat rules, iteration
    recommendations, impacts, influences, and the summary all stay
    consistent with the events actually reported. A caller that filtered
    events *after* building a full report would leave every aggregate
    describing events the report no longer shows."""
    context = context or {}; raw = _canonical_events(tuple(_load_events(context) if events is None else events))
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
    experiments = tuple(LearningExperiment(f"experiment-{item.learning_event_id}", item.hypothesis, item.action_taken, item.cost_estimate, None, item.metrics[0].name if item.metrics else "primary_metric", item.metrics[0].target if item.metrics else None, item.metrics[0].target if item.metrics else None, "capture learning before iteration", 3, True, item.action_taken in {"launch_ad_experiment", "scale_ad_budget", "run_provider_data_pull", "generate_client_export"}, (item.learning_event_id,), item.outcome, max((metric.sample_size for metric in item.metrics if metric.sample_size is not None), default=None)) for item in raw if item.event_type in {"ad_experiment", "creative_test", "landing_page_test", "site_funnel_test", "product_validation", "provider_run"})
    successes = [reason for item in raw for reason in item.success_reasons]; failures = [reason for item in raw for reason in item.failure_reasons]
    top_success = tuple(dict.fromkeys(successes))[:8]; top_failure = tuple(dict.fromkeys(failures))[:8]
    summary = LearningLedgerSummary(top_success, top_failure, tuple(item.condition for item in rules)[:8], tuple(item.recommendation for item in recommendations)[:8], tuple(item.blocker for item in _trustos_impacts(raw)), tuple(item.hypothesis.statement for item in raw if item.outcome == "win")[:5], tuple(item.condition for item in rules)[:5])
    return LearningLedgerReport("learning-ledger-v1", generated_at, raw, experiments, results, tuple(LearningLesson(f"lesson-{item.learning_event_id}", f"{item.event_type} lesson", "success" if item.outcome == "win" else "failure" if item.outcome in {"loss", "blocked", "killed"} else "iteration", item.resource_governor_influence, item.input_evidence_refs, item.confidence, item.client_visibility) for item in raw), rules, recommendations, _portfolio_impacts(raw), _model_impacts(raw), _provider_impacts(raw), _trustos_impacts(raw), _influences(raw, rules, recommendations), summary, LearningLedgerSafetySummary(), "No learning events were recorded; provide an offline fixture batch before drawing conclusions." if not raw else "Use only the recorded iteration recommendations and do-not-repeat rules in the next Resource Governor review; execution still requires existing gates." if recommendations or rules else "Retain the recorded evidence; no new action is supported by this batch.")


__all__ = ["EVENT_TYPES", "OUTCOMES", "VISIBILITY", "FAILURE_REASONS", "SUCCESS_REASONS", "BLOCK_BEHAVIORS", "GOVERNOR_EVIDENCE_MODES", "MIN_SCALE_CONFIDENCE", "PLACEHOLDER_CANDIDATE_ID", "LearningLedgerReport", "LearningEvent", "LearningExperiment", "LearningHypothesis", "LearningMetric", "LearningResult", "LearningOutcome", "LearningAttribution", "LearningLesson", "LearningDoNotRepeatRule", "LearningIterationRecommendation", "LearningPortfolioImpact", "LearningModelRoutingImpact", "LearningProviderImpact", "LearningTrustOSImpact", "LearningDecisionInfluence", "LearningGovernorInfluence", "derive_governor_influence", "LearningLedgerSummary", "LearningLedgerSafetySummary", "build_learning_ledger_report"]


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
