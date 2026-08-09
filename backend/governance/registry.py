from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

from .decision import GovernanceDecision
from .proposal import Proposal


class GovernanceRegistry:
    def __init__(self, path: str | os.PathLike[str] | None = None) -> None:
        self.path = Path(path or os.getenv("MARKETOS_GOVERNANCE_STATE", "state/governance_registry.json"))
        self.proposals: dict[str, Proposal] = {}; self.decisions: dict[str, GovernanceDecision] = {}; self._lock = threading.RLock(); self.load()
    def register_proposal(self, proposal: Proposal) -> Proposal:
        with self._lock: self.proposals[proposal.proposal_id] = proposal; self.save()
        return proposal
    def register_decision(self, decision: GovernanceDecision) -> GovernanceDecision:
        with self._lock: self.decisions[decision.decision_id] = decision; self.save()
        return decision
    def get_proposal(self, proposal_id: str) -> Proposal | None: return self.proposals.get(proposal_id)
    def list_proposals(self, workspace_id: str | None = None, status: str | None = None) -> list[Proposal]:
        return [p for p in self.proposals.values() if (workspace_id is None or p.workspace_id == workspace_id) and (status is None or p.status == status)]
    def list_decisions(self, proposal_id: str | None = None) -> list[GovernanceDecision]:
        return [d for d in self.decisions.values() if proposal_id is None or d.proposal_id == proposal_id]
    def load(self) -> None:
        try:
            if not self.path.exists(): return
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            self.proposals = {k: Proposal.from_dict(v) for k, v in raw.get("proposals", {}).items() if isinstance(v, dict)}
            self.decisions = {k: GovernanceDecision.from_dict(v) for k, v in raw.get("decisions", {}).items() if isinstance(v, dict)}
        except Exception: self.proposals, self.decisions = {}, {}
    def save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True); tmp = self.path.with_suffix(self.path.suffix + ".tmp")
            tmp.write_text(json.dumps({"proposals": {k: p.to_dict() for k, p in self.proposals.items()}, "decisions": {k: d.to_dict() for k, d in self.decisions.items()}}, indent=2), encoding="utf-8"); tmp.replace(self.path)
        except Exception: pass


_singleton: GovernanceRegistry | None = None; _lock = threading.Lock()
def get_governance_registry() -> GovernanceRegistry:
    global _singleton
    if _singleton is None:
        with _lock:
            if _singleton is None: _singleton = GovernanceRegistry()
    return _singleton
