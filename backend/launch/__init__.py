"""backend.launch — multi-platform campaign launch (Pipeline 4 of the
dropship spine: Discover → Validate → Create → Launch → Optimize).

Public surface:
    launch_product(build, budget_daily, platforms) → per-platform campaign IDs
"""
from backend.launch.orchestrator import launch_product

__all__ = ["launch_product"]
