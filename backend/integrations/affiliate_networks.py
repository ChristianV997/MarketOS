"""Phase 8 expansion: Affiliate network integrations for organic channel scaling.

Supports:
- impact.com (multi-network affiliate aggregation)
- Refersion (Shopify affiliate management)
- Commission Junction (direct affiliate recruitment)
- Kenshoo (influencer network)

Tracks affiliate performance, auto-recruits top performers, integrates revenue
into organic ROAS calculations.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum

from backend.patterns.worker import RateLimiter

_log = logging.getLogger(__name__)

# Module-level dry-run convention, matching every other integration in this
# codebase (e.g. backend/integrations/tiktok_ads.py, meta_ads_client.py):
# a single env-derived switch, not a bare constructor-argument default.
# Previously AffiliateNetworkConnector/OrganicChannelExpander each took a
# plain `dry_run: bool = True` constructor default with no env tie-in — a
# caller that forgot to pass `dry_run=True` explicitly (or that flipped
# PHASE8_AFFILIATE_SCALING_LIVE without realizing dry_run was a separate,
# unlinked knob) could end up live by accident.
_DRY_RUN = os.getenv("AFFILIATE_NETWORKS_DRY_RUN", "true").lower() != "false"


def _live() -> bool:
    """True only when real recruitment/fetch calls should actually be made."""
    from backend.research.mode import is_research_only
    return not is_research_only() and not _DRY_RUN


# Recruitment is real-world outreach with a commission-rate commitment —
# rate-limit it the same way other spend/outreach-adjacent workers are
# (e.g. orchestrator/main.py's _dropship_limiter, _organic_post_limiter).
# One shared limiter across all networks/products, not per-key, matching
# the codebase's existing global-gate pattern.
_RECRUITMENT_MIN_INTERVAL_S = float(os.getenv("AFFILIATE_RECRUITMENT_MIN_INTERVAL_S", "3600"))
_recruitment_limiter = RateLimiter(interval_s=_RECRUITMENT_MIN_INTERVAL_S)

# Cap on recruitment attempts per (product_id, network) so a caller retrying
# a failed/rejected recruitment doesn't resubmit indefinitely — mirrors
# backend/commerce/fulfillment.py's _MAX_FULFILLMENT_ATTEMPTS pattern.
_MAX_RECRUITMENT_ATTEMPTS = int(os.getenv("AFFILIATE_MAX_RECRUITMENT_ATTEMPTS", "3"))
_recruitment_attempts: dict[tuple[str, str], int] = {}


class AffiliateNetwork(str, Enum):
    """Supported affiliate networks."""
    IMPACT = "impact"
    REFERSION = "refersion"
    COMMISSION_JUNCTION = "cj"
    KENSHOO = "kenshoo"


@dataclass
class AffiliatePerformance:
    """Affiliate performance metrics."""
    affiliate_id: str
    network: AffiliateNetwork
    product_id: str
    period_start: datetime
    period_end: datetime

    clicks: int = 0
    conversions: int = 0
    revenue: float = 0.0
    commission_paid: float = 0.0

    ctr: float = 0.0  # Click-through rate
    cvr: float = 0.0  # Conversion rate
    revenue_per_click: float = 0.0
    roas: float = 0.0  # Revenue / Commission paid

    def __post_init__(self):
        """Compute derived metrics."""
        if self.clicks > 0:
            self.ctr = self.conversions / self.clicks
            self.revenue_per_click = self.revenue / self.clicks
        if self.commission_paid > 0:
            self.roas = self.revenue / self.commission_paid

    def is_high_performer(self, ctr_threshold: float = 0.05, roas_threshold: float = 2.0) -> bool:
        """Check if affiliate exceeds performance thresholds for auto-recruitment."""
        return self.ctr >= ctr_threshold and self.roas >= roas_threshold


@dataclass
class AffiliateRecruitment:
    """Recruitment request to affiliate network for specific product."""
    product_id: str
    network: AffiliateNetwork
    requested_at: datetime
    affiliate_template: str  # Email template, offer details, etc.
    target_affiliate_count: int = 5
    commission_rate_pct: float = 10.0  # 10% default commission

    status: str = "PENDING"  # PENDING, APPROVED, REJECTED, ACTIVE
    enrolled_count: int = 0
    estimated_organic_revenue_30d: float = 0.0


class AffiliateNetworkConnector:
    """Base connector for affiliate networks."""

    def __init__(
        self,
        network: AffiliateNetwork,
        api_key: str | None = None,
        dry_run: bool | None = None,
    ):
        self.network = network
        self.api_key = api_key
        # None means "not explicitly specified" — defer to the module-level
        # env-derived switch instead of silently defaulting to a bare True.
        self.dry_run = _DRY_RUN if dry_run is None else dry_run

    async def fetch_performance(
        self,
        product_id: str,
        days: int = 30,
    ) -> list[AffiliatePerformance]:
        """Fetch affiliate performance for product over N days."""
        if self.dry_run:
            return self._mock_performance(product_id, days)
        # Real implementation would call network API. No real network client
        # exists yet for any AffiliateNetwork — degrade to an empty result
        # (same "no live client configured" pattern as every other
        # integration in this codebase) rather than raising into the live
        # orchestrator tick.
        _log.warning(
            "affiliate_network_real_api_unavailable network=%s product=%s",
            self.network, product_id,
        )
        return []

    async def recruit_affiliates(
        self,
        recruitment: AffiliateRecruitment,
    ) -> tuple[bool, str]:
        """Submit recruitment request to network.

        Returns (success: bool, message: str)
        """
        from backend.research.mode import is_research_only
        if self.dry_run or is_research_only():
            if is_research_only() and not self.dry_run:
                return False, "research_only"
            _log.info(
                f"[DRY-RUN] {self.network} recruitment: "
                f"product={recruitment.product_id}, "
                f"target={recruitment.target_affiliate_count}, "
                f"commission={recruitment.commission_rate_pct}%"
            )
            return True, "Dry-run recruitment submitted"

        attempt_key = (recruitment.product_id, self.network.value)
        attempts = _recruitment_attempts.get(attempt_key, 0)
        if attempts >= _MAX_RECRUITMENT_ATTEMPTS:
            _log.warning(
                "affiliate_recruitment_attempts_exhausted network=%s product=%s attempts=%d",
                self.network, recruitment.product_id, attempts,
            )
            return False, f"Recruitment attempt cap ({_MAX_RECRUITMENT_ATTEMPTS}) reached"

        if not _recruitment_limiter.ready():
            _log.info(
                "affiliate_recruitment_rate_limited network=%s product=%s",
                self.network, recruitment.product_id,
            )
            return False, "Recruitment rate-limited"

        _recruitment_attempts[attempt_key] = attempts + 1
        _recruitment_limiter.mark()

        # Real implementation would submit to API. No real network client
        # exists yet — degrade gracefully instead of raising into the live
        # orchestrator tick.
        _log.warning(
            "affiliate_network_real_api_unavailable network=%s product=%s",
            self.network, recruitment.product_id,
        )
        return False, f"Real API for {self.network} not yet implemented"

    def _mock_performance(self, product_id: str, days: int = 30) -> list[AffiliatePerformance]:
        """Generate synthetic performance data for MVP."""
        now = datetime.now(timezone.utc)
        period_start = now - timedelta(days=days)

        performances = []
        num_affiliates = 5  # Synthetic: 5 affiliates per product

        for i in range(num_affiliates):
            affiliate_id = f"{self.network}_aff_{i}"
            clicks = 150 + (i * 50)  # Varying performance
            conversions = 8 + (i * 2)

            perf = AffiliatePerformance(
                affiliate_id=affiliate_id,
                network=self.network,
                product_id=product_id,
                period_start=period_start,
                period_end=now,
                clicks=clicks,
                conversions=conversions,
                revenue=conversions * 35.0,  # Avg order value ~$35
                commission_paid=conversions * 35.0 * 0.10,  # 10% commission
            )

            performances.append(perf)

        return performances


class OrganicChannelExpander:
    """Orchestrates affiliate network recruitment and performance tracking."""

    def __init__(self, dry_run: bool | None = None):
        self.dry_run = _DRY_RUN if dry_run is None else dry_run
        self.connectors = {
            network: AffiliateNetworkConnector(network, dry_run=dry_run)
            for network in AffiliateNetwork
        }
        self.recruitment_log: dict[str, list[AffiliateRecruitment]] = {}

    async def evaluate_product_for_affiliate_scaling(
        self,
        product_id: str,
        current_organic_cac: float = 20.0,
        paid_cac: float = 50.0,
    ) -> dict:
        """Evaluate if product qualifies for affiliate scaling.

        Strategy:
        1. Fetch current organic ROAS from UGC channel
        2. Check if affiliate network could improve it (lower CAC, higher volume)
        3. If yes, submit recruitment request
        4. Project 30-day organic revenue with affiliates

        Returns dict with recommendation and projections.
        """
        results = {
            "product_id": product_id,
            "current_organic_cac": current_organic_cac,
            "paid_cac": paid_cac,
            "recommendation": "HOLD",
            "qualified_networks": [],
            "projected_organic_revenue_30d": 0.0,
        }

        # Evaluate each network
        for network in AffiliateNetwork:
            connector = self.connectors[network]

            # Fetch 30-day performance
            perfs = await connector.fetch_performance(product_id, days=30)
            if not perfs:
                continue

            # Find high performers
            high_performers = [p for p in perfs if p.is_high_performer()]
            if not high_performers:
                _log.info(f"No high performers in {network} for {product_id}")
                continue

            # Average stats of high performers
            avg_roas = sum(p.roas for p in high_performers) / len(high_performers)
            avg_revenue = sum(p.revenue for p in high_performers) / len(high_performers)
            affiliate_cac = sum(p.commission_paid for p in high_performers) / len(high_performers) / max(1, sum(p.conversions for p in high_performers))

            # Gate: affiliate CAC must beat current organic CAC
            if affiliate_cac < current_organic_cac * 0.8:  # Must be 20% cheaper
                results["qualified_networks"].append({
                    "network": network.value,
                    "affiliate_count": len(high_performers),
                    "avg_roas": round(avg_roas, 2),
                    "avg_affiliate_cac": round(affiliate_cac, 2),
                    "improvement_vs_current": round((1 - affiliate_cac / current_organic_cac) * 100, 1),
                })

        if results["qualified_networks"]:
            results["recommendation"] = "SCALE"
            # Project: top 3 networks, avg 3 new affiliates per network
            results["projected_organic_revenue_30d"] = 2500.0  # Synthetic projection

        return results

    async def recruit_on_qualified_networks(
        self,
        product_id: str,
        qualified_networks: list[dict],
    ) -> dict:
        """Submit recruitment requests to all qualified networks."""
        recruitment_results = {
            "product_id": product_id,
            "networks_recruited": [],
            "total_target_affiliates": 0,
        }

        for network_info in qualified_networks:
            network_name = network_info["network"]
            try:
                network = AffiliateNetwork(network_name)
            except ValueError:
                _log.warning(f"Unknown network: {network_name}")
                continue

            connector = self.connectors[network]

            # Create recruitment request
            recruitment = AffiliateRecruitment(
                product_id=product_id,
                network=network,
                requested_at=datetime.now(timezone.utc),
                affiliate_template=f"Recruit top-performing affiliates for {product_id}",
                target_affiliate_count=5,
                commission_rate_pct=12.0,  # Slightly higher commission for scaled recruitment
            )

            # Submit
            success, msg = await connector.recruit_affiliates(recruitment)

            if success:
                recruitment.status = "ACTIVE"
                recruitment_results["networks_recruited"].append({
                    "network": network_name,
                    "target_affiliates": recruitment.target_affiliate_count,
                    "commission_rate": recruitment.commission_rate_pct,
                })
                recruitment_results["total_target_affiliates"] += recruitment.target_affiliate_count

                # Log recruitment
                if product_id not in self.recruitment_log:
                    self.recruitment_log[product_id] = []
                self.recruitment_log[product_id].append(recruitment)

        return recruitment_results


async def evaluate_and_scale_organic_channel(
    product_ids: list[str],
    current_organic_cac: float = 20.0,
    paid_cac: float = 50.0,
) -> dict:
    """End-to-end: evaluate products and scale organic via affiliate networks."""
    expander = OrganicChannelExpander(dry_run=True)

    results = {
        "evaluated": [],
        "recruited": [],
        "total_projected_30d_revenue": 0.0,
    }

    for product_id in product_ids:
        # Evaluate
        eval_result = await expander.evaluate_product_for_affiliate_scaling(
            product_id,
            current_organic_cac=current_organic_cac,
            paid_cac=paid_cac,
        )
        results["evaluated"].append(eval_result)

        # Recruit if qualified
        if eval_result["recommendation"] == "SCALE":
            recruit_result = await expander.recruit_on_qualified_networks(
                product_id,
                eval_result["qualified_networks"],
            )
            results["recruited"].append(recruit_result)
            results["total_projected_30d_revenue"] += eval_result["projected_organic_revenue_30d"]

    return results


if __name__ == "__main__":
    import logging

    logging.basicConfig(level=logging.INFO)

    # Demo
    products = ["product_1", "product_2", "product_3"]
    result = asyncio.run(evaluate_and_scale_organic_channel(products))
    print(f"Organic channel expansion: {result}")
