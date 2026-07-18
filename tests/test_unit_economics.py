"""Tests for Phase 6: true unit economics — category-aware margins, geo
economics, supplier reliability feedback, and CAC-vs-LTV framework.

Covers:
  6a. category_return_rate / calculate_margin category-awareness,
      reliability-sensitive risk-adjusted supplier ranking (shadow-mode).
  6b. calculate_margin_geo (shipping bands, customs duty, COD/card
      economics), geo_margin_adjusted_roas, GeoAgent wiring (shadow-mode).
  6c. SupplierFeedbackStore (EMA reliability decay).
  6d. CohortTracker / effective_cac (Beta-Binomial repeat-rate posterior),
      calculate_ltv_adjusted_margin.
"""
from __future__ import annotations

import importlib

import pytest

from backend.validation.margin_calculator import (
    calculate_margin, calculate_margin_geo, calculate_ltv_adjusted_margin,
    category_return_rate, geo_adjusted_shipping, customs_duty,
    payment_method_economics, geo_margin_adjusted_roas,
    CATEGORY_RETURN_RATES, GEO_SHIPPING_MULTIPLIERS,
    GEO_CUSTOMS_THRESHOLD_USD, COD_REFUSAL_RATE, CARD_REFUSAL_RATE,
)
from backend.economics.supplier_feedback import SupplierFeedbackStore, DEFAULT_PRIOR_RELIABILITY
from backend.economics.ltv import (
    CohortTracker, effective_cac, category_repeat_rate_prior,
    CATEGORY_REPEAT_RATE_PRIOR, PRIOR_STRENGTH, REPEAT_WINDOW_SECONDS,
)


# ─────────────────────────────────────────────────────────────────────────────
# 6a. Category-aware return rates
# ─────────────────────────────────────────────────────────────────────────────


class TestCategoryReturnRates:
    def test_general_matches_legacy_constant(self):
        assert category_return_rate("general") == pytest.approx(0.12)

    def test_unknown_category_falls_back_to_general(self):
        assert category_return_rate("nonexistent") == category_return_rate("general")

    def test_categories_differ(self):
        assert category_return_rate("electronics") != category_return_rate("beauty")

    def test_calculate_margin_default_unchanged(self):
        """No category, no return_rate -> byte-identical to pre-Phase-6."""
        m = calculate_margin(supplier_cost=10.0, retail_price=60.0, shipping_cost=2.0)
        legacy = calculate_margin(supplier_cost=10.0, retail_price=60.0,
                                  shipping_cost=2.0, return_rate=0.12)
        assert m == legacy

    def test_explicit_return_rate_overrides_category(self):
        m = calculate_margin(supplier_cost=10.0, retail_price=60.0,
                             category="electronics", return_rate=0.05)
        assert m["return_loss"] == calculate_margin(
            supplier_cost=10.0, retail_price=60.0, return_rate=0.05)["return_loss"]

    def test_category_changes_return_loss(self):
        general = calculate_margin(supplier_cost=10.0, retail_price=60.0, category="general")
        apparel = calculate_margin(supplier_cost=10.0, retail_price=60.0, category="apparel")
        assert apparel["return_loss"] > general["return_loss"]  # apparel 20% > general 12%


# ─────────────────────────────────────────────────────────────────────────────
# 6a. Supplier risk-adjusted ranking (shadow mode)
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _isolate_event_store(tmp_path, monkeypatch):
    from backend.orchestration.event_store import EventStore
    store = EventStore(path=str(tmp_path / "shadow.jsonl"))
    es_mod = importlib.import_module("backend.orchestration.event_store")
    monkeypatch.setattr(es_mod, "event_store", store)
    yield store


class TestSupplierRiskRanking:
    def test_flag_off_returns_legacy_cheapest(self, monkeypatch):
        monkeypatch.delenv("SUPPLIER_RISK_RANKING_LIVE", raising=False)
        monkeypatch.delenv("SUPPLIER_FEEDBACK_LIVE", raising=False)
        from backend.validation import suppliers

        quotes = suppliers.quote_all("Risk Ranking Widget")
        reliable = [q for q in quotes if q.reliability >= suppliers._MIN_RELIABILITY]
        pool = reliable if reliable else quotes
        expected = min(pool, key=lambda q: q.landed_cost)

        best = suppliers.find_best_supplier("Risk Ranking Widget")
        assert best.supplier == expected.supplier
        assert best.landed_cost == expected.landed_cost

    def test_shadow_journal_persists_both_picks(self, monkeypatch, _isolate_event_store):
        monkeypatch.delenv("SUPPLIER_RISK_RANKING_LIVE", raising=False)
        from backend.validation import suppliers

        suppliers.find_best_supplier("Journal Widget", category="apparel")

        events = _isolate_event_store.tail(10)
        shadow = [e for e in events if e.get("event") == "shadow_supplier_ranking"]
        assert len(shadow) > 0
        data = shadow[0]["data"]
        assert "legacy_supplier" in data
        assert "risk_adjusted_supplier" in data
        assert data["live"] is False

    def test_flag_on_may_diverge_from_legacy(self, monkeypatch):
        """Not all products will diverge, but the risk-adjusted ranking
        function itself must be reachable and self-consistent when live."""
        monkeypatch.setenv("SUPPLIER_RISK_RANKING_LIVE", "true")
        from backend.validation import suppliers

        best = suppliers.find_best_supplier("Some Divergent Product Name Here", category="apparel")
        assert best is not None
        assert best.supplier in {c.name for c in suppliers._CLIENTS}


# ─────────────────────────────────────────────────────────────────────────────
# 6b. Geo-aware economics
# ─────────────────────────────────────────────────────────────────────────────


class TestGeoShipping:
    def test_us_baseline_unchanged(self):
        assert geo_adjusted_shipping(5.0, "US") == pytest.approx(5.0)

    def test_international_scales_up(self):
        assert geo_adjusted_shipping(5.0, "AU") > 5.0
        assert geo_adjusted_shipping(5.0, "INTL") > geo_adjusted_shipping(5.0, "US")

    def test_unknown_geo_falls_back_to_intl(self):
        assert geo_adjusted_shipping(5.0, "XX") == geo_adjusted_shipping(5.0, "INTL")


class TestCustomsDuty:
    def test_us_never_incurs_duty(self):
        assert customs_duty(1000.0, 2000.0, "US") == 0.0

    def test_below_threshold_no_duty(self):
        assert customs_duty(50.0, 100.0, "EU") == 0.0

    def test_above_threshold_incurs_duty(self):
        duty = customs_duty(500.0, 1000.0, "EU")
        assert duty == pytest.approx((1000.0 - GEO_CUSTOMS_THRESHOLD_USD) * 0.15)

    def test_duty_uses_max_of_landed_and_retail(self):
        duty = customs_duty(1200.0, 900.0, "EU")
        assert duty > 0


class TestPaymentMethodEconomics:
    def test_card_lower_refusal_than_cod(self):
        card = payment_method_economics(100.0, "card")
        cod = payment_method_economics(100.0, "cod")
        assert card["refusal_rate"] == pytest.approx(CARD_REFUSAL_RATE)
        assert cod["refusal_rate"] == pytest.approx(COD_REFUSAL_RATE)
        assert cod["expected_refusal_loss"] > card["expected_refusal_loss"]

    def test_cod_incurs_handling_fee_card_does_not(self):
        card = payment_method_economics(100.0, "card")
        cod = payment_method_economics(100.0, "cod")
        assert card["handling_fee"] == 0.0
        assert cod["handling_fee"] > 0.0


class TestCalculateMarginGeo:
    def test_us_card_close_to_base_margin(self):
        """US + card should differ from base only by the (small) card
        refusal-rate loss — a real but modeled cost the base calculate_margin
        never accounted for, so this is NOT byte-identical, but should be
        close (within card refusal rate ~2.5% of retail price)."""
        base = calculate_margin(supplier_cost=10.0, retail_price=60.0, shipping_cost=2.0)
        geo = calculate_margin_geo(supplier_cost=10.0, retail_price=60.0, shipping_cost=2.0,
                                    geo="US", payment_method="card")
        assert abs(geo["net_margin"] - base["net_margin"]) < 60.0 * CARD_REFUSAL_RATE + 0.01

    def test_cod_heavy_geo_reduces_margin_materially(self):
        card_us = calculate_margin_geo(supplier_cost=10.0, retail_price=60.0, shipping_cost=2.0,
                                       geo="US", payment_method="card")
        cod_intl = calculate_margin_geo(supplier_cost=10.0, retail_price=60.0, shipping_cost=2.0,
                                        geo="INTL", payment_method="cod")
        assert cod_intl["net_margin"] < card_us["net_margin"]

    def test_high_value_cross_border_incurs_duty(self):
        result = calculate_margin_geo(supplier_cost=500.0, retail_price=1200.0,
                                       shipping_cost=10.0, geo="EU")
        assert result["customs_duty"] > 0

    def test_zero_price_never_raises(self):
        result = calculate_margin_geo(supplier_cost=10.0, retail_price=0.0, geo="EU")
        assert result["margin_status"] == "loss"

    def test_negative_price_never_raises(self):
        result = calculate_margin_geo(supplier_cost=10.0, retail_price=-5.0, geo="INTL")
        assert result["margin_status"] == "loss"


class TestGeoMarginAdjustedRoas:
    def test_at_baseline_threshold_is_noop(self):
        from backend.validation.margin_calculator import _PROFITABLE_PCT
        roas = geo_margin_adjusted_roas(2.0, _PROFITABLE_PCT, base_margin_pct=_PROFITABLE_PCT)
        assert roas == pytest.approx(2.0)

    def test_lower_margin_pulls_roas_down(self):
        from backend.validation.margin_calculator import _PROFITABLE_PCT
        roas = geo_margin_adjusted_roas(2.0, _PROFITABLE_PCT / 2, base_margin_pct=_PROFITABLE_PCT)
        assert roas < 2.0

    def test_never_negative(self):
        roas = geo_margin_adjusted_roas(2.0, -50.0)
        assert roas >= 0.0


class TestGeoAgentWiring:
    def test_flag_off_uses_raw_roas(self, monkeypatch):
        monkeypatch.delenv("GEO_ECONOMICS_LIVE", raising=False)
        from agents.hierarchy import GeoAgent
        agent = GeoAgent(expand_roas=2.0, pause_roas=0.9)

        # geo_margin_pct supplied but would pull effective roas below
        # expand threshold — flag off means raw roas (2.5) still triggers expand
        decision = agent.decide({"country": "DE", "roas": 2.5, "geo_margin_pct": 1.0})
        assert decision.action == "expand"

    def test_flag_on_uses_margin_adjusted_roas(self, monkeypatch):
        monkeypatch.setenv("GEO_ECONOMICS_LIVE", "true")
        from agents.hierarchy import GeoAgent
        from backend.validation.margin_calculator import _PROFITABLE_PCT
        agent = GeoAgent(expand_roas=2.0, pause_roas=0.9)

        # geo_margin_pct far below baseline -> margin-adjusted roas collapses
        decision = agent.decide({"country": "DE", "roas": 2.5, "geo_margin_pct": 1.0})
        assert decision.action != "expand"

    def test_no_geo_margin_context_behaves_like_legacy(self, monkeypatch):
        monkeypatch.setenv("GEO_ECONOMICS_LIVE", "true")
        from agents.hierarchy import GeoAgent
        agent = GeoAgent(expand_roas=2.0, pause_roas=0.9)
        decision = agent.decide({"country": "US", "roas": 2.5})
        assert decision.action == "expand"

    def test_shadow_journal_persists(self, _isolate_event_store):
        from agents.hierarchy import GeoAgent
        agent = GeoAgent()
        agent.decide({"country": "FR", "roas": 1.5, "geo_margin_pct": 10.0})

        events = _isolate_event_store.tail(10)
        shadow = [e for e in events if e.get("event") == "shadow_geo_economics"]
        assert len(shadow) > 0
        assert "margin_adjusted_roas" in shadow[0]["data"]


# ─────────────────────────────────────────────────────────────────────────────
# 6c. Supplier reliability feedback loop
# ─────────────────────────────────────────────────────────────────────────────


class TestSupplierFeedbackStore:
    def test_no_observations_returns_static_default(self):
        store = SupplierFeedbackStore()
        assert store.reliability_for("cj_dropshipping", "general", static_default=0.9) == 0.9

    def test_default_prior_when_no_static_default_given(self):
        store = SupplierFeedbackStore()
        assert store.reliability_for("cj_dropshipping") == DEFAULT_PRIOR_RELIABILITY

    def test_success_nudges_reliability_up(self):
        store = SupplierFeedbackStore()
        before = store.reliability_for("zendrop", static_default=0.7)
        store.record_outcome("zendrop", "general", stockout=False, delayed=False, complaint=False)
        after = store.reliability_for("zendrop", static_default=0.7)
        assert after >= before  # EMA toward success=1.0

    def test_stockout_decays_reliability(self):
        store = SupplierFeedbackStore()
        for _ in range(20):
            store.record_outcome("spocket", "general", stockout=False)
        stable = store.reliability_for("spocket")
        for _ in range(10):
            store.record_outcome("spocket", "general", stockout=True)
        after_failures = store.reliability_for("spocket")
        assert after_failures < stable

    def test_category_isolated_from_other_categories(self):
        store = SupplierFeedbackStore()
        store.record_outcome("printful", "apparel", stockout=True)
        assert store.observation_count("printful", "apparel") == 1
        assert store.observation_count("printful", "electronics") == 0

    def test_observation_count_increments(self):
        store = SupplierFeedbackStore()
        store.record_outcome("cj_dropshipping", "general")
        store.record_outcome("cj_dropshipping", "general")
        assert store.observation_count("cj_dropshipping", "general") == 2

    def test_reset_clears_all_state(self):
        store = SupplierFeedbackStore()
        store.record_outcome("cj_dropshipping", "general", stockout=True)
        store.reset()
        assert store.observation_count("cj_dropshipping", "general") == 0
        assert store.reliability_for("cj_dropshipping", static_default=0.42) == 0.42

    def test_journal_persists(self, _isolate_event_store):
        store = SupplierFeedbackStore()
        store.record_outcome("zendrop", "general", stockout=True)

        events = _isolate_event_store.tail(10)
        journaled = [e for e in events if e.get("event") == "supplier_feedback_recorded"]
        assert len(journaled) == 1
        assert journaled[0]["data"]["stockout"] is True


class TestSupplierFeedbackWiredIntoRanking:
    def test_feedback_flag_off_ignores_observations(self, monkeypatch):
        monkeypatch.delenv("SUPPLIER_FEEDBACK_LIVE", raising=False)
        from backend.economics.supplier_feedback import supplier_feedback
        from backend.validation import suppliers

        supplier_feedback.reset()
        supplier_feedback.record_outcome("cj_dropshipping", "general", stockout=True)
        supplier_feedback.record_outcome("cj_dropshipping", "general", stockout=True)

        # With the flag off, _effective_reliability must ignore the
        # degraded observed reliability and use the quote's static value.
        quotes = suppliers.quote_all("Feedback Widget")
        cj_quote = next((q for q in quotes if q.supplier == "cj_dropshipping"), None)
        assert cj_quote is not None
        assert suppliers._effective_reliability(cj_quote, "general") == cj_quote.reliability

    def test_feedback_flag_on_uses_observed_reliability(self, monkeypatch):
        monkeypatch.setenv("SUPPLIER_FEEDBACK_LIVE", "true")
        from backend.economics.supplier_feedback import supplier_feedback
        from backend.validation import suppliers

        supplier_feedback.reset()
        for _ in range(10):
            supplier_feedback.record_outcome("cj_dropshipping", "general", stockout=True)

        quotes = suppliers.quote_all("Feedback Widget 2")
        cj_quote = next((q for q in quotes if q.supplier == "cj_dropshipping"), None)
        assert cj_quote is not None
        observed = suppliers._effective_reliability(cj_quote, "general")
        assert observed != cj_quote.reliability
        assert observed < cj_quote.reliability  # degraded by repeated stockouts


# ─────────────────────────────────────────────────────────────────────────────
# 6d. CAC-vs-LTV framework
# ─────────────────────────────────────────────────────────────────────────────


class TestCohortTracker:
    def test_first_order_is_not_a_repeat(self):
        tracker = CohortTracker()
        is_repeat = tracker.record_order("cust_1", "consumables", ts=1000.0)
        assert is_repeat is False

    def test_second_order_within_window_is_a_repeat(self):
        tracker = CohortTracker()
        tracker.record_order("cust_1", "consumables", ts=1000.0)
        is_repeat = tracker.record_order("cust_1", "consumables", ts=1000.0 + 86400 * 10)
        assert is_repeat is True

    def test_second_order_outside_window_is_not_a_repeat(self):
        tracker = CohortTracker()
        tracker.record_order("cust_1", "consumables", ts=0.0)
        is_repeat = tracker.record_order("cust_1", "consumables", ts=REPEAT_WINDOW_SECONDS * 2)
        assert is_repeat is False

    def test_missing_customer_id_never_counts_as_repeat(self):
        tracker = CohortTracker()
        tracker.record_order("", "consumables", ts=1000.0)
        is_repeat = tracker.record_order("", "consumables", ts=1000.0 + 100)
        assert is_repeat is False
        assert tracker.observation_count("consumables") == 2  # both counted as orders

    def test_different_categories_tracked_independently(self):
        tracker = CohortTracker()
        tracker.record_order("cust_1", "consumables", ts=1000.0)
        is_repeat = tracker.record_order("cust_1", "beauty", ts=1000.0 + 100)
        assert is_repeat is False  # different category, not a repeat of consumables

    def test_reset_clears_history(self):
        tracker = CohortTracker()
        tracker.record_order("cust_1", "consumables", ts=1000.0)
        tracker.reset()
        assert tracker.observation_count("consumables") == 0


class TestRepeatRatePosterior:
    def test_prior_dominates_with_no_observations(self):
        tracker = CohortTracker()
        rate = tracker.repeat_rate("consumables")
        assert rate == pytest.approx(category_repeat_rate_prior("consumables"))

    def test_unknown_category_uses_general_prior(self):
        tracker = CohortTracker()
        assert tracker.repeat_rate("nonexistent") == pytest.approx(
            category_repeat_rate_prior("general"))

    def test_posterior_shifts_toward_observed_data(self):
        tracker = CohortTracker()
        # Simulate a category with a MUCH higher observed repeat rate than
        # its prior — feed enough observations to move the posterior.
        ts = 0.0
        for i in range(100):
            tracker.record_order(f"cust_{i}", "jewelry", ts=ts)
            tracker.record_order(f"cust_{i}", "jewelry", ts=ts + 100)  # near-instant repeat
            ts += 1000

        prior = category_repeat_rate_prior("jewelry")
        posterior = tracker.repeat_rate("jewelry")
        assert posterior > prior  # observed 100% repeat pulls posterior up

    def test_few_observations_barely_move_posterior(self):
        tracker = CohortTracker()
        tracker.record_order("cust_1", "jewelry", ts=0.0)
        tracker.record_order("cust_1", "jewelry", ts=100.0)  # 1 repeat, 2 total obs
        prior = category_repeat_rate_prior("jewelry")
        posterior = tracker.repeat_rate("jewelry")
        # PRIOR_STRENGTH=20 vs 2 observations -> posterior close to prior
        assert abs(posterior - prior) < 0.05


class TestEffectiveCac:
    def test_zero_repeat_rate_leaves_cac_unchanged(self):
        tracker = CohortTracker()
        # Force a scenario approximating zero repeat rate: not perfectly
        # achievable with a nonzero prior, but jewelry has the lowest prior.
        cac = effective_cac(100.0, category="jewelry", tracker=tracker)
        assert cac < 100.0  # prior alone still nudges it slightly
        assert cac > 90.0   # but not by much given jewelry's low prior

    def test_higher_repeat_rate_lowers_effective_cac_more(self):
        tracker = CohortTracker()
        cac_consumables = effective_cac(100.0, category="consumables", tracker=tracker)
        cac_jewelry = effective_cac(100.0, category="jewelry", tracker=tracker)
        assert cac_consumables < cac_jewelry

    def test_never_exceeds_first_order_cac(self):
        tracker = CohortTracker()
        cac = effective_cac(100.0, category="consumables", tracker=tracker)
        assert cac <= 100.0

    def test_uses_module_singleton_by_default(self):
        from backend.economics.ltv import cohort_tracker
        cohort_tracker.reset()
        cac = effective_cac(100.0, category="general")
        assert cac > 0


class TestCalculateLtvAdjustedMargin:
    def test_consumables_outrank_oneoffs_at_identical_first_order_margin(self):
        from backend.economics.ltv import cohort_tracker
        cohort_tracker.reset()

        consumable = calculate_ltv_adjusted_margin(
            supplier_cost=10.0, retail_price=60.0, shipping_cost=2.0,
            category="consumables")
        oneoff = calculate_ltv_adjusted_margin(
            supplier_cost=10.0, retail_price=60.0, shipping_cost=2.0,
            category="jewelry")

        # Identical first-order economics (cost/price/shipping), but
        # consumables' higher repeat-rate prior should yield materially
        # better LTV-adjusted net margin.
        assert consumable["net_margin"] > oneoff["net_margin"]
        assert consumable["effective_cac"] < oneoff["effective_cac"]

    def test_zero_price_never_raises(self):
        result = calculate_ltv_adjusted_margin(supplier_cost=10.0, retail_price=0.0)
        assert result["margin_status"] == "loss"

    def test_effective_cac_never_exceeds_base_cac(self):
        base = calculate_margin(supplier_cost=10.0, retail_price=60.0, category="general")
        ltv = calculate_ltv_adjusted_margin(supplier_cost=10.0, retail_price=60.0, category="general")
        assert ltv["effective_cac"] <= base["cac"]

    def test_ltv_adjusted_margin_at_least_as_good_as_base(self):
        base = calculate_margin(supplier_cost=10.0, retail_price=60.0, category="consumables")
        ltv = calculate_ltv_adjusted_margin(supplier_cost=10.0, retail_price=60.0, category="consumables")
        assert ltv["net_margin"] >= base["net_margin"]
