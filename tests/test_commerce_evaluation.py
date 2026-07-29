from datetime import datetime, timedelta, timezone
from evaluation import CampaignCandidate, CampaignObservation, DataQuality, ProductCandidate, SupplierOffer, calculate_unit_economics, evaluate_campaign, evaluate_product
from evaluation.experiments import evaluate_experiment

LIVE_ATTRIBUTED = DataQuality(provenance="live", attribution="attributed")

def test_negative_margin_is_not_launchable_even_with_high_roas():
    result = evaluate_product(ProductCandidate("p1", "Widget", selling_price=20, quality=LIVE_ATTRIBUTED), SupplierOffer("s1", "p1", unit_cost=25, quality=LIVE_ATTRIBUTED))
    assert not result.launchable and "negative_contribution_margin" in result.reasons

def test_unit_economics_calculates_break_even_roas():
    economics = calculate_unit_economics(ProductCandidate("p1", "Widget", selling_price=100), SupplierOffer("s1", "p1", unit_cost=30, shipping_cost=10))
    assert economics.contribution_before_ads > 0 and economics.break_even_roas is not None and economics.max_cac == economics.contribution_before_ads

def test_synthetic_observations_cannot_be_winners():
    quality = DataQuality(provenance="simulated", attribution="attributed")
    rows = [CampaignObservation(str(i), "c1", creative_id="v1", spend=10, revenue=30, conversions=3, quality=quality) for i in range(3)]
    result = evaluate_experiment(rows)[0]
    assert result.status == "undetermined" and "synthetic_only" in result.reasons

def test_unattributed_revenue_is_not_product_launch_evidence():
    product = ProductCandidate("p1", "Widget", selling_price=100, quality=LIVE_ATTRIBUTED); offer = SupplierOffer("s1", "p1", unit_cost=20, quality=LIVE_ATTRIBUTED); quality = DataQuality(provenance="live", attribution="unattributed")
    rows = [CampaignObservation(str(i), "c1", product_id="p1", creative_id="v1", spend=10, revenue=30, conversions=3, quality=quality) for i in range(3)]
    result = evaluate_product(product, offer, observations=rows)
    assert not result.launchable and "unattributed" in result.reasons

def test_duplicate_observations_do_not_inflate_sample_size():
    row = CampaignObservation("same", "c1", creative_id="v1", spend=10, revenue=15, conversions=1, quality=LIVE_ATTRIBUTED); result = evaluate_experiment([row, row, row])[0]
    assert result.observations == 1 and "insufficient_observations" in result.reasons

def test_stale_data_is_reported():
    stale = DataQuality(provenance="live", attribution="attributed", observed_at=datetime.now(timezone.utc) - timedelta(days=3)); result = evaluate_product(ProductCandidate("p1", "Widget", selling_price=100, quality=stale), SupplierOffer("s1", "p1", unit_cost=20))
    assert "stale_data" in result.reasons

def test_campaign_without_observations_is_not_ready():
    result = evaluate_campaign(CampaignCandidate("c1", "p1"), [])
    assert not result.launchable and "missing_observations" in result.reasons
