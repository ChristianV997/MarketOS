"""services.ecommerce_operator — own/client e-commerce launch validation:
launch readiness gate, contribution-profit reconciliation, kill/scale
decisions driven by contribution profit rather than ROAS alone."""
from .contribution_profit import reconcile_contribution_profit
from .experiment import create_commerce_experiment
from .launch_guard import evaluate_launch_readiness
from .report import render_commerce_experiment_markdown
from .scale_decision import make_kill_scale_decision
from .schemas import DECISIONS, ContributionProfitResult, LaunchReadiness, ScaleDecision

__all__ = [
    "create_commerce_experiment",
    "evaluate_launch_readiness",
    "reconcile_contribution_profit",
    "make_kill_scale_decision",
    "render_commerce_experiment_markdown",
    "LaunchReadiness",
    "ContributionProfitResult",
    "ScaleDecision",
    "DECISIONS",
]
