from __future__ import annotations

import importlib
from dataclasses import asdict, is_dataclass
from typing import Any

from backend.governance.approval_policy import evaluate_proposal_approval
from backend.governance.decision import GovernanceDecision
from backend.governance.proposal import Proposal
from backend.governance.registry import get_governance_registry
from backend.obsidian.sync import sync_proposal_note
from .org_registry import get_organization_registry


SERVICE_TARGETS = {
    "product_research": ("services.product_research.audit", "run_product_audit"),
    "unit_economics": ("services.unit_economics.analyzer", "run_unit_economics"),
    "creative_growth": ("services.creative_growth.plan", "build_creative_growth_plan"),
    "customer_intelligence": ("services.customer_intelligence.sprint", "build_customer_intelligence_sprint"),
    "profit_stack_advisor": ("services.profit_stack_advisor.advisor", "run_profit_stack_advisor"),
}
_LIVE_INPUT_KEYS = {"live", "confirm_live", "live_action_requested", "execute_live", "send_message", "place_order"}


def _safe(value: Any) -> Any:
    if hasattr(value, "to_dict"): return _safe(value.to_dict())
    if is_dataclass(value): return _safe(asdict(value))
    if isinstance(value, dict): return {str(k): _safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)): return [_safe(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None: return value
    return str(value)


def _workspace_id(workspace: Any) -> str:
    if isinstance(workspace, str): return workspace
    if isinstance(workspace, dict): return str(workspace.get("workspace_id", ""))
    return str(getattr(workspace, "workspace_id", ""))


def run_planner_executor_reviewer(objective: str, workspace, department_id: str, service_name: str,
                                  inputs: dict, planner_agent_id: str = "", executor_agent_id: str = "",
                                  reviewer_agent_id: str = "", live_action_requested: bool = False) -> dict:
    if not isinstance(inputs, dict):
        inputs = {}
    org = get_organization_registry()
    if not org.list_departments(): org.bootstrap_defaults()
    department = org.get_department(department_id)
    proposed_by = planner_agent_id or executor_agent_id
    if not proposed_by and department: proposed_by = department.manager_agent_id
    role = org.get_agent(proposed_by)
    proposal = Proposal(workspace_id=_workspace_id(workspace), department_id=department_id,
                        proposed_by_agent_id=proposed_by, title=objective, summary=objective,
                        service_name=service_name, inputs=inputs or {})
    gov = get_governance_registry(); proposal.mark_proposed(); gov.register_proposal(proposal)
    approval = evaluate_proposal_approval(proposal, role, workspace, live_action_requested)
    execution: dict[str, Any] = {"status": "not_run", "dry_run": True}
    live_input_requested = any(bool((inputs or {}).get(key)) for key in _LIVE_INPUT_KEYS if key in (inputs or {})) or (inputs or {}).get("dry_run") is False
    if live_input_requested:
        approval["allowed"] = False
        approval["blocked_reasons"].append("live_execution_forbidden_in_governance_loop")
    if not approval["allowed"]:
        proposal.mark_blocked("; ".join(approval["blocked_reasons"])); decision = GovernanceDecision(proposal_id=proposal.proposal_id, workspace_id=proposal.workspace_id, department_id=department_id, decided_by_agent_id=reviewer_agent_id or proposed_by, decision="blocked", reason="; ".join(approval["blocked_reasons"]))
    elif not department or not department.allows_service(service_name):
        proposal.mark_blocked("service_not_allowed_for_department"); decision = GovernanceDecision(proposal_id=proposal.proposal_id, workspace_id=proposal.workspace_id, department_id=department_id, decided_by_agent_id=reviewer_agent_id or proposed_by, decision="blocked", reason="service_not_allowed_for_department")
    elif service_name not in SERVICE_TARGETS:
        proposal.mark_blocked("unsupported_service"); decision = GovernanceDecision(proposal_id=proposal.proposal_id, workspace_id=proposal.workspace_id, department_id=department_id, decided_by_agent_id=reviewer_agent_id or proposed_by, decision="blocked", reason="unsupported_service")
    else:
        proposal.mark_under_review(); proposal.mark_approved(); proposal.mark_executing()
        module_name, function_name = SERVICE_TARGETS[service_name]
        try:
            module = importlib.import_module(module_name); fn = getattr(module, function_name)
            safe_inputs = {k: v for k, v in (inputs or {}).items() if k not in _LIVE_INPUT_KEYS and k != "dry_run"}
            safe_inputs["dry_run"] = True
            # A target must explicitly accept the dry-run contract. Never
            # retry without it: that would turn a signature mismatch into a
            # possible live-action escape hatch.
            import inspect
            signature = inspect.signature(fn)
            accepts_dry_run = "dry_run" in signature.parameters or any(
                parameter.kind == inspect.Parameter.VAR_KEYWORD for parameter in signature.parameters.values()
            )
            if not accepts_dry_run:
                raise RuntimeError("service_dry_run_contract_missing")
            result = fn(**safe_inputs)
            execution = {"status": "completed", "dry_run": True, "result": _safe(result)}
            experiment_id = _safe(result).get("experiment_id") if isinstance(_safe(result), dict) else None
            proposal.mark_completed(); proposal.linked_experiment_id = experiment_id
            decision = GovernanceDecision(proposal_id=proposal.proposal_id, workspace_id=proposal.workspace_id, department_id=department_id, decided_by_agent_id=reviewer_agent_id or proposed_by, decision="approved", reason="dry_run_read_only_execution")
        except ModuleNotFoundError:
            proposal.mark_blocked("service_module_unavailable"); decision = GovernanceDecision(proposal_id=proposal.proposal_id, workspace_id=proposal.workspace_id, department_id=department_id, decided_by_agent_id=reviewer_agent_id or proposed_by, decision="blocked", reason="service_module_unavailable")
        except Exception as exc:
            proposal.mark_blocked("service_execution_failed"); execution = {"status": "error", "dry_run": True, "error_type": type(exc).__name__}; decision = GovernanceDecision(proposal_id=proposal.proposal_id, workspace_id=proposal.workspace_id, department_id=department_id, decided_by_agent_id=reviewer_agent_id or proposed_by, decision="blocked", reason="service_execution_failed")
    gov.register_proposal(proposal); gov.register_decision(decision)
    obsidian = sync_proposal_note(proposal, approval, decision, execution)
    return {"proposal": _safe(proposal), "approval": _safe(approval), "decision": _safe(decision), "execution": _safe(execution), "experiment_id": proposal.linked_experiment_id, "obsidian": _safe(obsidian), "status": proposal.status}
