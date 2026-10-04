"""Read-only product/campaign evaluation and launch-readiness decisions."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Iterable, Protocol
from .contracts import CampaignCandidate, CampaignObservation, ProductCandidate, SupplierOffer
from .economics import UnitEconomics, calculate_unit_economics
from .experiments import ExperimentResult, evaluate_experiment
from .quality import quality_reasons


class LearningInfluence(Protocol):
    @property
    def action_type(self) -> str: ...

    @property
    def candidate_id(self) -> str: ...

    @property
    def recency_label(self) -> str: ...

    @property
    def workspace_id(self) -> str: ...

    @property
    def provenance(self) -> tuple[str, ...]: ...

    @property
    def iteration_recommendation_source_event_id(self) -> str: ...

    def to_dict(self) -> dict: ...


@dataclass(frozen=True)
class LearningIterationAdvisory:
    """Non-authoritative ledger guidance attached to an experiment report."""

    influence: LearningInfluence

    def to_dict(self) -> dict:
        return {
            "authority": "advisory_only",
            "decision_effect": "none",
            "influence": self.influence.to_dict(),
        }


@dataclass(frozen=True)
class LaunchReadiness:
    subject_id: str
    launchable: bool
    reasons: tuple[str, ...]
    economics: UnitEconomics | None = None
    experiment: ExperimentResult | None = None
    calculation_version: str = "commerce-evaluation-v1"
    learning_advisory: LearningIterationAdvisory | None = None

    def to_dict(self) -> dict:
        result = {
            "subject_id": self.subject_id,
            "launchable": self.launchable,
            "reasons": list(self.reasons),
            "economics": self.economics.to_dict() if self.economics else None,
            "experiment": self.experiment.to_dict() if self.experiment else None,
            "calculation_version": self.calculation_version,
        }
        if self.learning_advisory is not None:
            result["learning_advisory"] = self.learning_advisory.to_dict()
        return result


def evaluate_product(product: ProductCandidate, offer: SupplierOffer | None, *, observations: Iterable[CampaignObservation] = ()) -> LaunchReadiness:
    economics = calculate_unit_economics(product, offer); reasons = list(economics.reasons) + quality_reasons(product.quality)
    live_observations = [o for o in observations if o.product_id == product.product_id]; experiment = evaluate_experiment(live_observations)[0] if live_observations else None
    if experiment: reasons.extend(experiment.reasons)
    return LaunchReadiness(product.product_id, not reasons, tuple(sorted(set(reasons))), economics, experiment)


def evaluate_campaign(
    campaign: CampaignCandidate,
    observations: Iterable[CampaignObservation],
    *,
    learning_influence: LearningInfluence | None = None,
) -> LaunchReadiness:
    """Evaluate a campaign; typed ledger guidance is report-only.

    The canonical experiment evaluator and existing quality gates retain
    full authority over scoring, reasons, and launchability. A supplied
    influence must be scoped to this campaign's product and action.
    """
    rows = [o for o in observations if o.campaign_id == campaign.campaign_id]
    results = evaluate_experiment(rows)
    experiment = results[0] if results else None
    reasons = quality_reasons(campaign.quality)
    if not rows:
        reasons.append("missing_observations")
    if experiment:
        reasons.extend(experiment.reasons)

    learning_advisory = None
    if learning_influence is not None:
        from .companyos.learning_ledger import LearningGovernorInfluence

        if not isinstance(learning_influence, LearningGovernorInfluence):
            raise TypeError("learning_influence must be a LearningGovernorInfluence")
        expected_candidate_id = campaign.product_id or campaign.campaign_id
        if learning_influence.action_type != "launch_ad_experiment":
            raise ValueError("learning_influence action does not match campaign experiment")
        if learning_influence.candidate_id != expected_candidate_id:
            raise ValueError("learning_influence candidate does not match campaign product")
        if learning_influence.recency_label == "action_type_only_match":
            raise ValueError("campaign advisory cannot use action-wide fallback")
        if not isinstance(learning_influence.workspace_id, str) or not learning_influence.workspace_id.strip():
            raise ValueError("learning_influence must include a workspace provenance")
        if (
            learning_influence.iteration_recommendation_source_event_id
            and learning_influence.iteration_recommendation_source_event_id not in learning_influence.provenance
        ):
            raise ValueError("learning recommendation source must appear in influence provenance")
        learning_advisory = LearningIterationAdvisory(learning_influence)

    return LaunchReadiness(
        campaign.campaign_id,
        not reasons,
        tuple(sorted(set(reasons))),
        experiment=experiment,
        learning_advisory=learning_advisory,
    )
