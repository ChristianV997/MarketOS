"""backend.identity.operator_gates -- route gates for operator runtime control and commerce execution.

Each gate is ``require_workspace_permission(OWNER_TYPE, <permission>)``: the caller's sole
``internal`` membership, whose role must grant the permission. Anonymous -> 401, a
``client_viewer`` or any role without the permission -> 403, and no configured verifier or
repository -> 503. A route must depend on its gate, so a refused request runs no handler code
and makes no outbound call or state change.
"""
from __future__ import annotations

from .http import require_workspace_permission
from .repository import OWNER_TYPE
from .roles import COMMERCE_EXECUTION_WRITE, RUNTIME_CONTROL_WRITE

runtime_control_gate = require_workspace_permission(OWNER_TYPE, RUNTIME_CONTROL_WRITE)
commerce_execution_gate = require_workspace_permission(OWNER_TYPE, COMMERCE_EXECUTION_WRITE)

__all__ = ["commerce_execution_gate", "runtime_control_gate"]
