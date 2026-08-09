"""Tests for scripts/ingest_category_priors.py's pure transform functions —
amazon_category_stats, olist_category_stats, wish_category_stats,
merge_priors never touch the filesystem or network, so they're exercised
entirely on inline fixtures here; the real datasets are never touched in
tests."""
import importlib.util
import sys
from pathlib import Path

_SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "ingest_category_priors.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("ingest_category_priors", _SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules["ingest_category_priors"] = module
    spec.loader.exec_module(module)
    return module


ingest = _load_module()


class TestAmazonCategoryStats:
    def test_price_band_percentiles(self):
        rows = [{"price": p, "average_rating": 4.0} for p in [10, 20, 30, 40, 50]]
        stats = ingest.amazon_category_stats(rows)
        assert stats["price_band"]["p50"] == 30

    def test_return_proxy_from_low_ratings(self):
        rows = ([{"price": 10, "average_rating": 5.0}] * 8
                + [{"price": 10, "average_rating": 1.5}] * 2)
        stats = ingest.amazon_category_stats(rows)
        assert stats["return_proxy"] == 0.2  # 2/10 rated <= 2 stars

    def test_review_volume_counts_all_rows(self):
        rows = [{"price": 10, "average_rating": 4.0}] * 7
        stats = ingest.amazon_category_stats(rows)
        assert stats["review_volume"] == 7

    def test_missing_prices_and_ratings_degrade_to_none(self):
        rows = [{"price": None, "average_rating": None}]
        stats = ingest.amazon_category_stats(rows)
        assert stats["rating_mean"] is None
        assert stats["return_proxy"] is None
        assert stats["price_band"]["p50"] is None

    def test_empty_input(self):
        stats = ingest.amazon_category_stats([])
        assert stats["review_volume"] == 0
        assert stats["rating_mean"] is None


class TestOlistCategoryStats:
    def test_repeat_customer_detected_within_window(self):
        orders = [
            {"customer_unique_id": "c1", "order_purchase_timestamp": 0, "delivery_days": 5},
            {"customer_unique_id": "c1", "order_purchase_timestamp": 10 * 86400, "delivery_days": 4},
            {"customer_unique_id": "c2", "order_purchase_timestamp": 0, "delivery_days": 6},
        ]
        stats = ingest.olist_category_stats(orders)
        assert stats["repeat_rate"] == 0.5  # 1 of 2 distinct customers repeated

    def test_second_order_outside_window_is_not_a_repeat(self):
        orders = [
            {"customer_unique_id": "c1", "order_purchase_timestamp": 0, "delivery_days": 5},
            {"customer_unique_id": "c1", "order_purchase_timestamp": 90 * 86400, "delivery_days": 5},
        ]
        stats = ingest.olist_category_stats(orders)
        assert stats["repeat_rate"] == 0.0

    def test_delivery_days_median(self):
        orders = [{"customer_unique_id": f"c{i}", "order_purchase_timestamp": 0,
                  "delivery_days": d} for i, d in enumerate([3, 5, 7, 9, 11])]
        stats = ingest.olist_category_stats(orders)
        assert stats["delivery_days_p50"] == 7

    def test_empty_input(self):
        stats = ingest.olist_category_stats([])
        assert stats["repeat_rate"] is None
        assert stats["delivery_days_p50"] is None
        assert stats["order_volume"] == 0


class TestWishCategoryStats:
    def test_price_band_and_units_sold_median(self):
        rows = [{"price": p, "units_sold": u, "rating": 4.0, "rating_count": 100}
                for p, u in zip([10, 20, 30, 40, 50], [100, 200, 300, 400, 500])]
        stats = ingest.wish_category_stats(rows)
        assert stats["price_band"]["p50"] == 30
        assert stats["units_sold_median"] == 300

    def test_rating_mean(self):
        rows = [{"price": 10, "units_sold": 50, "rating": r, "rating_count": 10}
                for r in [3.0, 4.0, 5.0]]
        stats = ingest.wish_category_stats(rows)
        assert stats["rating_mean"] == 4.0

    def test_review_volume_counts_all_rows(self):
        rows = [{"price": 10, "units_sold": 50, "rating": 4.0, "rating_count": 10}] * 6
        stats = ingest.wish_category_stats(rows)
        assert stats["review_volume"] == 6

    def test_missing_fields_degrade_to_none(self):
        rows = [{"price": None, "units_sold": None, "rating": None, "rating_count": None}]
        stats = ingest.wish_category_stats(rows)
        assert stats["price_band"]["p50"] is None
        assert stats["units_sold_median"] is None
        assert stats["rating_mean"] is None

    def test_empty_input(self):
        stats = ingest.wish_category_stats([])
        assert stats["review_volume"] == 0
        assert stats["units_sold_median"] is None


class TestMergePriors:
    def test_merges_fields_from_both_sources(self):
        amazon = {"pets": {"return_proxy": 0.08, "rating_mean": 4.3}}
        olist = {"pets": {"repeat_rate": 0.15, "delivery_days_p50": 9}}
        merged = ingest.merge_priors(amazon, olist)
        assert merged["pets"] == {
            "return_proxy": 0.08, "rating_mean": 4.3,
            "repeat_rate": 0.15, "delivery_days_p50": 9,
        }

    def test_category_present_in_only_one_source_gets_partial_entry(self):
        amazon = {"pets": {"return_proxy": 0.08}}
        olist = {}
        merged = ingest.merge_priors(amazon, olist)
        assert merged == {"pets": {"return_proxy": 0.08}}

    def test_no_sources_yields_empty(self):
        assert ingest.merge_priors({}, {}) == {}

    def test_three_way_merge_including_wish(self):
        amazon = {"pets": {"return_proxy": 0.08}}
        olist = {"pets": {"repeat_rate": 0.15}}
        wish = {"wish_summer_products": {"units_sold_median": 500.0}}
        merged = ingest.merge_priors(amazon, olist, wish)
        assert merged["pets"] == {"return_proxy": 0.08, "repeat_rate": 0.15}
        assert merged["wish_summer_products"] == {"units_sold_median": 500.0}

    def test_single_source_still_works(self):
        assert ingest.merge_priors({"pets": {"return_proxy": 0.08}}) == {
            "pets": {"return_proxy": 0.08}
        }
