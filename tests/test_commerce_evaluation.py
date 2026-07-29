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


def test_small_sample_high_roas_is_not_declared_winner():
    """A handful of noisy high-ROAS observations must not be enough evidence
    to call a winner — that's exactly the ad-hoc-confidence gap this test
    guards against."""
    rows = [
        CampaignObservation(str(i), "c1", creative_id="v1", spend=10, revenue=r, conversions=3, quality=LIVE_ATTRIBUTED)
        for i, r in enumerate([16.0, 8.0, 20.0])
    ]
    result = evaluate_experiment(rows)[0]
    assert result.status == "undetermined"
    assert result.significant is False


def test_large_sample_high_roas_is_declared_winner():
    """Enough consistent high-ROAS observations should clear both the
    minimum-detectable-effect and significance bars."""
    rows = [
        CampaignObservation(str(i), "c1", creative_id="v1", spend=10, revenue=16 + (i % 3), conversions=3, quality=LIVE_ATTRIBUTED)
        for i in range(30)
    ]
    result = evaluate_experiment(rows)[0]
    assert result.status == "winner"
    assert result.significant is True
    assert result.p_value is not None and result.p_value <= 0.05


def test_large_sample_low_roas_is_declared_loser():
    rows = [
        CampaignObservation(str(i), "c1", creative_id="v1", spend=10, revenue=4 + (i % 3), conversions=1, quality=LIVE_ATTRIBUTED)
        for i in range(30)
    ]
    result = evaluate_experiment(rows)[0]
    assert result.status == "loser"
    assert result.significant is True


def test_min_conversions_exact_boundary_passes():
    rows = [
        CampaignObservation(str(i), "c1", creative_id="v1", spend=10, revenue=20, conversions=1, quality=LIVE_ATTRIBUTED)
        for i in range(3)
    ]
    result = evaluate_experiment(rows, min_conversions=3)[0]
    assert "insufficient_conversions" not in result.reasons


def test_min_conversions_one_below_boundary_flags_insufficient():
    rows = [
        CampaignObservation(str(i), "c1", creative_id="v1", spend=10, revenue=20, conversions=1, quality=LIVE_ATTRIBUTED)
        for i in range(2)
    ]
    result = evaluate_experiment(rows, min_conversions=3)[0]
    assert "insufficient_conversions" in result.reasons


def test_mixed_quality_observations_surface_all_reasons():
    stale = DataQuality(provenance="live", attribution="attributed", observed_at=datetime.now(timezone.utc) - timedelta(days=3))
    rows = [
        CampaignObservation("a", "c1", creative_id="v1", spend=10, revenue=20, conversions=3, quality=LIVE_ATTRIBUTED),
        CampaignObservation("b", "c1", creative_id="v1", spend=10, revenue=20, conversions=3, quality=stale),
    ]
    result = evaluate_experiment(rows)[0]
    assert "stale_data" in result.reasons
    assert result.status == "undetermined"


def test_stale_supplier_offer_makes_economics_ineligible():
    stale = DataQuality(provenance="live", attribution="attributed", observed_at=datetime.now(timezone.utc) - timedelta(days=3))
    economics = calculate_unit_economics(
        ProductCandidate("p1", "Widget", selling_price=100, quality=LIVE_ATTRIBUTED),
        SupplierOffer("s1", "p1", unit_cost=30, shipping_cost=10, quality=stale),
    )
    assert economics.eligible is False
    assert "stale_data" in economics.reasons


def test_synthetic_supplier_offer_makes_economics_ineligible():
    synthetic = DataQuality(provenance="simulated", attribution="attributed")
    economics = calculate_unit_economics(
        ProductCandidate("p1", "Widget", selling_price=100, quality=LIVE_ATTRIBUTED),
        SupplierOffer("s1", "p1", unit_cost=30, shipping_cost=10, quality=synthetic),
    )
    assert economics.eligible is False
    assert "synthetic_only" in economics.reasons


def test_supplier_offer_exactly_at_max_age_boundary_is_not_stale():
    boundary = DataQuality(
        provenance="live", attribution="attributed",
        observed_at=datetime.now(timezone.utc) - timedelta(hours=47, minutes=59),
    )
    economics = calculate_unit_economics(
        ProductCandidate("p1", "Widget", selling_price=100, quality=LIVE_ATTRIBUTED),
        SupplierOffer("s1", "p1", unit_cost=30, shipping_cost=10, quality=boundary),
    )
    assert "stale_data" not in economics.reasons


def test_supplier_offer_just_past_max_age_boundary_is_stale():
    past_boundary = DataQuality(
        provenance="live", attribution="attributed",
        observed_at=datetime.now(timezone.utc) - timedelta(hours=48, minutes=1),
    )
    economics = calculate_unit_economics(
        ProductCandidate("p1", "Widget", selling_price=100, quality=LIVE_ATTRIBUTED),
        SupplierOffer("s1", "p1", unit_cost=30, shipping_cost=10, quality=past_boundary),
    )
    assert "stale_data" in economics.reasons


def test_zero_spend_positive_revenue_is_excluded_from_roas_sample():
    rows = [
        CampaignObservation("a", "c1", creative_id="v1", spend=0, revenue=50, conversions=1, quality=LIVE_ATTRIBUTED),
        CampaignObservation("b", "c1", creative_id="v1", spend=10, revenue=20, conversions=3, quality=LIVE_ATTRIBUTED),
    ]
    result = evaluate_experiment(rows)[0]
    # Only the spend>0 row contributes to the significance sample (n=1) —
    # not enough for a real test, so the result stays undetermined rather
    # than being skewed by the zero-spend row's undefined ROAS.
    assert result.significant is False
    assert result.mean_roas == 2.0
