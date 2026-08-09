from __future__ import annotations

import uuid

from .portfolio_actions import PortfolioAction
from .scenario import OptimizationScenario, PortfolioOptimizationPlan, ResourceConstraint
from .action_generator import generate_portfolio_actions
from .optimization_registry import get_optimization_registry


_ORDER = {"acquire_evidence": 1, "run_refinement_cycle": 2, "refresh_pipeline": 3, "run_source_calibration": 3, "run_validation_sprint": 4, "generate_deliverable": 5, "run_executive_cycle": 6}


def _utility(action: PortfolioAction, objective: str) -> float:
    if objective == "maximize_information_gain": return action.expected_information_gain / max(action.estimated_hours, 0.25)
    if objective == "maximize_confidence": return action.expected_confidence_delta + action.confidence_score * .25
    if objective == "minimize_cost": return (action.expected_information_gain + action.expected_confidence_delta) / max(action.estimated_cost + action.estimated_hours, 1)
    if objective == "reduce_risk": return action.expected_risk_reduction + action.risk_score
    if objective == "prepare_deliverables": return (100 if action.action_type == "generate_deliverable" else 40 if action.action_type == "run_validation_sprint" else 10) + action.leverage_score
    return action.total_action_score


def optimize_actions_for_constraint(actions: list[PortfolioAction], constraint: ResourceConstraint) -> OptimizationScenario:
    available = [x for x in actions if not x.blocked_reasons and x.status != "blocked"]
    ordered = sorted(available, key=lambda x: (-_utility(x, constraint.objective), _ORDER.get(x.action_type, 99), x.title, x.action_id))
    selected = []; rejected = []; cost = hours = info = confidence = risk = 0.0; selected_types = set()
    for action in ordered:
        prerequisite = _ORDER.get(action.action_type, 99)
        if any(_ORDER.get(item.action_type, 99) > prerequisite for item in selected):
            rejected.append(action.action_id); continue
        if len(selected) >= constraint.max_actions or cost + action.estimated_cost > constraint.budget or hours + action.estimated_hours > constraint.hours:
            rejected.append(action.action_id); continue
        selected.append(action); selected_types.add(action.action_type); cost += action.estimated_cost; hours += action.estimated_hours; info += action.expected_information_gain; confidence += action.expected_confidence_delta; risk += action.expected_risk_reduction
    selected.sort(key=lambda x: (_ORDER.get(x.action_type, 99), x.title, x.action_id))
    blocked = [x.action_id for x in actions if x.blocked_reasons or x.status == "blocked"]
    scenario = OptimizationScenario("scenario_" + uuid.uuid5(uuid.NAMESPACE_URL, f"{constraint.constraint_id}:{','.join(x.action_id for x in selected)}").hex[:16], actions[0].workspace_id if actions else "default", f"{constraint.objective} under ${constraint.budget:.0f}/{constraint.hours:.1f}h", constraint, [x.action_id for x in selected], rejected, blocked, min(cost, constraint.budget), min(hours, constraint.hours), min(info, 1000), min(confidence, 1000), min(risk, 1000), {"selected_action_count": len(selected), "simulated": True}, [f"Greedy deterministic selection for objective `{constraint.objective}`.", "Totals are estimates, not realized returns."], ["No live capital allocation occurred."])
    return scenario


def build_default_resource_constraints() -> list[ResourceConstraint]:
    return [ResourceConstraint("zero_budget", 0, 2, 5, "maximize_information_gain", "low"), ResourceConstraint("small_budget", 100, 4, 8, "minimize_cost", "low"), ResourceConstraint("balanced_500", 500, 8, 10, "balanced", "medium"), ResourceConstraint("confidence_1000", 1000, 16, 12, "maximize_confidence", "medium"), ResourceConstraint("balanced_5000", 5000, 40, 20, "balanced", "medium"), ResourceConstraint("deliverables_10000", 10000, 80, 25, "prepare_deliverables", "high"), ResourceConstraint("risk_reduction", 500, 12, 10, "reduce_risk", "low"), ResourceConstraint("fastest_progress", 0, 2, 3, "maximize_information_gain", "medium")]


def build_portfolio_optimization_plan(workspace_id="default", objective="Optimize next MarketOS actions under resource constraints", constraints=None):
    action_set = generate_portfolio_actions(workspace_id, 100); constraints = constraints or build_default_resource_constraints(); scenarios = [optimize_actions_for_constraint(action_set.actions, item) for item in constraints]
    preferred = [item for item in scenarios if item.constraint.objective == objective] if objective in {"maximize_information_gain", "maximize_confidence", "minimize_cost", "reduce_risk", "prepare_deliverables", "balanced"} else []
    candidates = preferred or [item for item in scenarios if item.constraint.objective == "balanced"] or scenarios
    recommended = max(candidates, key=lambda x: (sum(a.total_action_score for a in action_set.actions if a.action_id in x.selected_action_ids), -x.total_simulated_cost, x.scenario_id)) if candidates else optimize_actions_for_constraint([], ResourceConstraint("default", 0, 0, 0))
    selected = [x for x in action_set.actions if x.action_id in recommended.selected_action_ids]; plan = PortfolioOptimizationPlan("optimization_" + uuid.uuid5(uuid.NAMESPACE_URL, f"{workspace_id}:{recommended.scenario_id}").hex[:16], workspace_id, "Portfolio Optimization Plan", objective, action_set.action_set_id, scenarios, recommended.scenario_id, selected, action_set.blocked_actions, f"Selected {len(selected)} safe action(s) for the recommended simulated scenario.", [x.description for x in selected[:5]] or ["Run refinement to establish an evidence baseline."], metadata={"simulated_only": True, "no_real_spend": True})
    get_optimization_registry().register_plan(plan); return plan
