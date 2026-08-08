from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any

from backend.governance.approval_policy import evaluate_proposal_approval
from backend.governance.decision import GovernanceDecision
from backend.governance.proposal import Proposal
from backend.governance.registry import get_governance_registry
from backend.obsidian.sync import sync_proposal_note
from .org_registry import get_organization_registry
from .service_adapters import execute_governed_service


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
    if not isinstance(inputs, dict): inputs = {}
    org = get_organization_registry()
    if not org.list_departments(): org.bootstrap_defaults()
    department = org.get_department(department_id)
    proposed_by = planner_agent_id or executor_agent_id or (department.manager_agent_id if department else "")
    role = org.get_agent(proposed_by)
    proposal = Proposal(workspace_id=_workspace_id(workspace), department_id=department_id,
                        proposed_by_agent_id=proposed_by, title=objective, summary=objective,
                        service_name=service_name, inputs=inputs)
    gov = get_governance_registry()
    proposal.mark_proposed(); gov.register_proposal(proposal)
    approval = evaluate_proposal_approval(proposal, role, workspace, live_action_requested,
                                          prior_decisions=gov.list_decisions(proposal.proposal_id))
    execution: dict[str, Any] = {"service_name": service_name, "status": "not_run", "dry_run": True}
    live_input_requested = any(bool(inputs.get(key)) for key in {"live", "confirm_live", "live_action_requested", "execute_live", "send_message", "place_order"}) or inputs.get("dry_run") is False or inputs.get("read_only") is False
    if live_input_requested:
        approval["allowed"] = False
        approval["blocked_reasons"] = list(dict.fromkeys([*approval.get("blocked_reasons", []), "live_execution_forbidden_in_governance_loop"]))

    if not approval["allowed"]:
        proposal.mark_blocked("; ".join(approval["blocked_reasons"]))
        decision = GovernanceDecision(proposal_id=proposal.proposal_id, workspace_id=proposal.workspace_id,
                                      department_id=department_id, decided_by_agent_id=reviewer_agent_id or proposed_by,
                                      decision="blocked", reason="; ".join(approval["blocked_reasons"]))
    elif not department or not department.allows_service(service_name):
        proposal.mark_blocked("service_not_allowed_for_department")
        decision = GovernanceDecision(proposal_id=proposal.proposal_id, workspace_id=proposal.workspace_id,
                                      department_id=department_id, decided_by_agent_id=reviewer_agent_id or proposed_by,
                                      decision="blocked", reason="service_not_allowed_for_department")
    else:
        proposal.mark_under_review(); proposal.mark_approved(); proposal.mark_executing()
        result = execute_governed_service(service_name, department_id, inputs, workspace, live_action_requested)
        execution = result.to_dict()
        if result.status == "completed":
            proposal.linked_experiment_id = result.experiment_id
            proposal.mark_completed()
            decision_value, reason = "approved", "dry_run_read_only_execution"
        else:
            proposal.mark_blocked("; ".join(result.blocked_reasons or result.errors or [result.status]))
            decision_value, reason = "blocked", "; ".join(result.blocked_reasons or result.errors or [result.status])
        decision = GovernanceDecision(proposal_id=proposal.proposal_id, workspace_id=proposal.workspace_id,
                                      department_id=department_id, decided_by_agent_id=reviewer_agent_id or proposed_by,
                                      decision=decision_value, reason=reason)
    gov.register_proposal(proposal); gov.register_decision(decision)
    obsidian = sync_proposal_note(proposal, approval, decision, execution)
    return {"proposal": _safe(proposal), "approval": _safe(approval), "decision": _safe(decision),
            "execution": _safe(execution), "experiment_id": proposal.linked_experiment_id,
            "obsidian": _safe(obsidian), "status": proposal.status}
