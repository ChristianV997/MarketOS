"""backend.dao_future.schemas — placeholder dataclasses only.

See docs/DAO_FUTURE_ARCHITECTURE.md for the concept mapping each of these
is meant to eventually formalize (BusinessCell -> ClientWorkspace,
Proposal/Evidence -> CommercialRunEnvelope, etc.). No field here is
validated or enforced; no instance of these classes is created or
persisted anywhere in the live codebase today.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class BusinessCell:
    """A workspace with governance attached. See backend.workspaces.client_workspace.ClientWorkspace."""
    cell_id: str = ""
    workspace_id: str = ""
    name: str = ""
    enabled_services: list[str] = field(default_factory=list)
    operator_ids: list[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)


@dataclass
class Proposal:
    """A pre-execution deliberation record for a would-be CommercialRunEnvelope.
    See backend.experiments.envelope.CommercialRunEnvelope for the
    post-approval execution/evidence record this would lead into."""
    proposal_id: str = ""
    cell_id: str = ""
    proposed_by_operator_id: str = ""
    summary: str = ""
    requested_budget: float = 0.0
    status: str = "proposed"  # proposed | voting | approved | rejected | executing
    linked_experiment_id: str = ""  # set once approved and an envelope is created
    created_at: float = field(default_factory=time.time)


@dataclass
class GovernanceDecision:
    """A recorded human approval/rejection of a Proposal. Not a real voting
    mechanism — no quorum/weighting logic exists anywhere in this codebase."""
    decision_id: str = ""
    proposal_id: str = ""
    decided_by_operator_id: str = ""
    decision: str = "pending"  # pending | approved | rejected
    reason: str = ""
    decided_at: float = field(default_factory=time.time)


@dataclass
class CapitalAllocationRequest:
    """A cell's request for how much budget it should be allowed to
    allocate this period — the input a real allocate_capital() call would
    be gated behind, not a replacement for it."""
    request_id: str = ""
    cell_id: str = ""
    period: str = ""  # e.g. "2026-Q3"
    requested_amount: float = 0.0
    approved_amount: float | None = None
    status: str = "pending"  # pending | approved | rejected


@dataclass
class OperatorRole:
    """A human's role/permission within a cell. No authn/authz exists
    anywhere in this codebase today — see docs/SERVICE_MODULES.md's
    SaaS-lite readiness notes for that gap."""
    operator_id: str = ""
    cell_id: str = ""
    role: str = "member"  # member | proposer | approver | admin
    reputation_score: float = 0.0


@dataclass
class RevenueShareRule:
    """A rule for splitting audited contribution profit
    (services.ecommerce_operator.contribution_profit.ContributionProfitResult)
    across operators. No payment execution implied — this is a ledger
    entry shape, not a payout mechanism."""
    rule_id: str = ""
    cell_id: str = ""
    operator_id: str = ""
    share_pct: float = 0.0
    applies_to_experiment_id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
