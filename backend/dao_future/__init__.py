"""backend.dao_future — placeholder schemas for a possible future DAO-style
business-automation governance layer.

Nothing in this package is imported by any live code path. No behavior, no
persistence, no validation, no blockchain dependency. See
docs/DAO_FUTURE_ARCHITECTURE.md for the full design mapping this exists to
support — this module only fixes a shared vocabulary (field names) so a
future implementation doesn't have to invent them from scratch.
"""
from .schemas import (
    BusinessCell,
    CapitalAllocationRequest,
    GovernanceDecision,
    OperatorRole,
    Proposal,
    RevenueShareRule,
)

__all__ = [
    "BusinessCell",
    "Proposal",
    "GovernanceDecision",
    "CapitalAllocationRequest",
    "OperatorRole",
    "RevenueShareRule",
]
