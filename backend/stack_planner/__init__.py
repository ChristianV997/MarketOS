"""backend.stack_planner — the Stack Planner.

Composes backend.providers and backend.costs; purely advisory (no live
mutation, no spend). See docs/STACK_PLANNER.md.
"""
from __future__ import annotations

from .planner import recommend_stack
from .schemas import BusinessStackRecommendation, BusinessStackRequest
from .strategies import ALL_STRATEGIES, DEFERRED_STRATEGIES, REACHABLE_STRATEGIES, is_deferred_strategy, select_strategy

__all__ = [
    "recommend_stack",
    "BusinessStackRequest",
    "BusinessStackRecommendation",
    "select_strategy",
    "is_deferred_strategy",
    "ALL_STRATEGIES",
    "REACHABLE_STRATEGIES",
    "DEFERRED_STRATEGIES",
]
