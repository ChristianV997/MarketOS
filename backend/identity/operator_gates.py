"""backend.identity.operator_gates -- route gates for operator-only intelligence runs.

Each gate is ``require_workspace_permission(OWNER_TYPE, <permission>)``: the caller's sole ``internal``
membership, whose role must grant the permission. Anonymous -> 401, a ``client_viewer`` or any role without
the permission -> 403, and no configured verifier or repository -> 503. A route must depend on its gate, so
a refused request runs no handler code and changes no state.
"""
from __future__ import annotations

from .http import require_workspace_permission
from .repository import OWNER_TYPE
from .roles import COMMERCIAL_INTELLIGENCE_RUN, CREATIVE_INTELLIGENCE_RUN, INTELLIGENCE_RUN

intelligence_run_gate = require_workspace_permission(OWNER_TYPE, INTELLIGENCE_RUN)
creative_intelligence_run_gate = require_workspace_permission(OWNER_TYPE, CREATIVE_INTELLIGENCE_RUN)
commercial_intelligence_run_gate = require_workspace_permission(OWNER_TYPE, COMMERCIAL_INTELLIGENCE_RUN)

__all__ = [
    "commercial_intelligence_run_gate",
    "creative_intelligence_run_gate",
    "intelligence_run_gate",
]
