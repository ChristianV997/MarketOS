"""Draft-only experiment contract. Planning and simulation layer only.

Never publishes ads, spends money, mutates campaigns, messages customers,
changes storefronts, places orders, or calls providers.
"""
from evaluation.commerce.experiment_draft_build import build_experiment_draft, reset_registry
from evaluation.commerce.experiment_draft_models import ExperimentDraft, SimulationReport
from evaluation.commerce.experiment_draft_sim import client_safe_report, simulate_experiment_draft
from evaluation.commerce.experiment_draft_types import ExperimentDraftError, SCHEMA, replay_hash

__all__ = [
    "ExperimentDraft",
    "ExperimentDraftError",
    "SCHEMA",
    "SimulationReport",
    "build_experiment_draft",
    "client_safe_report",
    "replay_hash",
    "reset_registry",
    "simulate_experiment_draft",
]
