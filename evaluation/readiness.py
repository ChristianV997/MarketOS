"""Read-only product/campaign evaluation and launch-readiness decisions."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Iterable
from .contracts import CampaignCandidate, CampaignObservation, ProductCandidate, SupplierOffer
from .economics import UnitEconomics, calculate_unit_economics
from .experiments import ExperimentResult, evaluate_experiment
from .quality import quality_reasons

@dataclass(frozen=True)
class LaunchReadiness:
    subject_id: str; launchable: bool; reasons: tuple[str, ...]; economics: UnitEconomics | None = None; experiment: ExperimentResult | None = None; calculation_version: str = "commerce-evaluation-v1"
    def to_dict(self) -> dict: return {"subject_id": self.subject_id, "launchable": self.launchable, "reasons": list(self.reasons), "economics": self.economics.to_dict() if self.economics else None, "experiment": self.experiment.to_dict() if self.experiment else None, "calculation_version": self.calculation_version}

def evaluate_product(product: ProductCandidate, offer: SupplierOffer | None, *, observations: Iterable[CampaignObservation] = ()) -> LaunchReadiness:
    economics = calculate_unit_economics(product, offer); reasons = list(economics.reasons) + quality_reasons(product.quality)
    live_observations = [o for o in observations if o.product_id == product.product_id]; experiment = evaluate_experiment(live_observations)[0] if live_observations else None
    if experiment: reasons.extend(experiment.reasons)
    return LaunchReadiness(product.product_id, not reasons, tuple(sorted(set(reasons))), economics, experiment)

def evaluate_campaign(campaign: CampaignCandidate, observations: Iterable[CampaignObservation]) -> LaunchReadiness:
    rows = [o for o in observations if o.campaign_id == campaign.campaign_id]; results = evaluate_experiment(rows); experiment = results[0] if results else None
    reasons = quality_reasons(campaign.quality)
    if not rows: reasons.append("missing_observations")
    if experiment: reasons.extend(experiment.reasons)
    return LaunchReadiness(campaign.campaign_id, not reasons, tuple(sorted(set(reasons))), experiment=experiment)
