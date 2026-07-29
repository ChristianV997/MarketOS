"""CampaignAsset — full attribution lineage for a launched TikTok campaign."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .base import BaseArtifact


@dataclass
class CampaignAsset(BaseArtifact):
    """Immutable record of a campaign launch with full creative lineage.

    Written at launch time; updated with ROAS outcome when metrics arrive.
    The combination of hook + angle + product + campaign_id is the
    atomic attribution unit for learning.
    """
    artifact_type:    str   = field(default="campaign")
    campaign_id:      str   = field(default="")
    adgroup_id:       str   = field(default="")
    ad_ids:           list[str] = field(default_factory=list)
    product:          str   = field(default="")
    hook:             str   = field(default="")
    angle:            str   = field(default="")
    phase:            str   = field(default="")
    estimated_roas:   float = field(default=0.0)
    actual_roas:      float = field(default=0.0)
    budget:           float = field(default=0.0)
    launched_at:      float = field(default=0.0)
    dry_run:          bool  = field(default=True)
    outcome_recorded: bool  = field(default=False)
    launch_status:    str   = field(default="completed")

    def to_dict(self) -> dict[str, Any]:
        d = super().to_dict()
        d.update({
            "campaign_id":      self.campaign_id,
            "adgroup_id":       self.adgroup_id,
            "ad_ids":           self.ad_ids,
            "product":          self.product,
            "hook":             self.hook,
            "angle":            self.angle,
            "phase":            self.phase,
            "estimated_roas":   self.estimated_roas,
            "actual_roas":      self.actual_roas,
            "budget":           self.budget,
            "launched_at":      self.launched_at,
            "dry_run":          self.dry_run,
            "outcome_recorded": self.outcome_recorded,
            "launch_status":    self.launch_status,
        })
        return d

    def with_outcome(self, roas: float) -> "CampaignAsset":
        """Return a new CampaignAsset updated with the real ROAS outcome."""
        import dataclasses
        updated = dataclasses.replace(
            self,
            actual_roas=roas,
            outcome_recorded=True,
        )
        return updated

    def with_launch_state(
        self,
        *,
        status: str,
        campaign_id: str | None = None,
        adgroup_id: str | None = None,
        ad_ids: list[str] | None = None,
        error: str | None = None,
    ) -> "CampaignAsset":
        """Return an updated launch checkpoint without changing its identity."""
        import dataclasses

        metadata = dict(self.metadata)
        if error:
            metadata["last_error"] = error
        else:
            metadata.pop("last_error", None)
        return dataclasses.replace(
            self,
            campaign_id=self.campaign_id if campaign_id is None else campaign_id,
            adgroup_id=self.adgroup_id if adgroup_id is None else adgroup_id,
            ad_ids=self.ad_ids if ad_ids is None else list(ad_ids),
            launch_status=status,
            metadata=metadata,
        )
