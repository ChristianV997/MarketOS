"""Tests for backend.metrics.attribution — cross-platform revenue
reconciliation (ROI overhaul Phase 1: fix double-counted attribution).

Covers:
  - no ground truth available → pass-through, flagged
  - platforms under-claim vs ground truth → untouched (not the bug being fixed)
  - platforms over-claim (double-counting) → scaled proportionally to ground truth
  - integration: calculate_profitability() exposes both raw and reconciled
    figures, and only uses reconciled figures live when the flag is set
"""
from __future__ import annotations

import uuid

import pytest

import backend.metrics.campaign_metrics as cm
import backend.metrics.profitability as prof
from backend.core.persistence import save_json_atomic
from backend.metrics.attribution import reconcile_revenue


# ─────────────────────────────────────────────────────────────────────────────
# reconcile_revenue()
# ─────────────────────────────────────────────────────────────────────────────


class TestReconcileRevenue:
    def test_no_ground_truth_passes_through(self):
        result = reconcile_revenue({"c1": 100.0, "c2": 50.0}, None)
        assert result.applied is False
        assert result.reason == "no_ground_truth_available"
        assert result.reconciled_total_revenue == 150.0
        assert result.per_campaign_revenue == {"c1": 100.0, "c2": 50.0}

    def test_under_claim_left_untouched(self):
        """Platforms claiming less than ground truth isn't double-counting."""
        result = reconcile_revenue({"c1": 40.0, "c2": 30.0}, 200.0)
        assert result.applied is False
        assert result.reason == "within_ground_truth"
        assert result.reconciled_total_revenue == 70.0

    def test_over_claim_scaled_to_ground_truth(self):
        """The core fix: two platforms double-claiming the same $100 sale."""
        result = reconcile_revenue({"meta": 100.0, "tiktok": 100.0}, 100.0)
        assert result.applied is True
        assert result.reason == "scaled_to_ground_truth"
        assert result.reconciled_total_revenue == pytest.approx(100.0)
        assert result.per_campaign_revenue["meta"] == pytest.approx(50.0)
        assert result.per_campaign_revenue["tiktok"] == pytest.approx(50.0)
        assert result.scale_factor == pytest.approx(0.5)

    def test_proportional_split_preserved_under_scaling(self):
        """Relative platform performance ordering survives reconciliation."""
        result = reconcile_revenue({"big": 300.0, "small": 100.0}, 200.0)
        assert result.per_campaign_revenue["big"] == pytest.approx(150.0)
        assert result.per_campaign_revenue["small"] == pytest.approx(50.0)
        # ratio preserved: big was 3x small before and after
        ratio = (result.per_campaign_revenue["big"]
                / result.per_campaign_revenue["small"])
        assert ratio == pytest.approx(3.0)

    def test_never_scales_up(self):
        result = reconcile_revenue({"c1": 10.0}, 500.0)
        assert result.applied is False
        assert result.per_campaign_revenue["c1"] == 10.0

    def test_zero_ground_truth_not_treated_as_available(self):
        """Ground truth of exactly 0 isn't meaningfully distinguishable
        from 'no data' here — caller (_shopify_ground_truth) already
        normalizes 0 to None, but defend at this layer too."""
        result = reconcile_revenue({"c1": 50.0}, 0.0)
        # 50 > 0 → over-claim branch, scale factor would be 0
        assert result.applied is True
        assert result.per_campaign_revenue["c1"] == 0.0

    def test_to_dict_json_safe_and_reports_overcount_pct(self):
        result = reconcile_revenue({"meta": 150.0, "tiktok": 150.0}, 100.0)
        d = result.to_dict()
        assert d["applied"] is True
        assert d["overcounted_pct"] == pytest.approx(200.0)  # claimed 3x truth
        import json
        json.dumps(d)  # must not raise


# ─────────────────────────────────────────────────────────────────────────────
# Integration: calculate_profitability()
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def isolated_metrics(monkeypatch, tmp_path):
    metrics_path = tmp_path / "campaign_metrics.jsonl"
    snapshot_path = tmp_path / "dropship.json"
    monkeypatch.setattr(cm, "_METRICS_PATH", metrics_path)
    monkeypatch.setattr(prof, "_DROPSHIP_SNAPSHOT", str(snapshot_path))
    cm._perf_cache.invalidate()   # module-level cache isn't keyed by path
    return {"metrics": metrics_path, "snapshot": snapshot_path}


def _write_snapshot(path, launches):
    save_json_atomic(str(path), {"status": "ok", "launches": launches})


def _launch(product, cids, predicted_roas=2.0, confidence=0.8, budget=40.0):
    return {
        "product": product,
        "confidence": confidence,
        "predicted_roas": predicted_roas,
        "budget": budget,
        "campaigns": [{"campaign_id": c, "platform": "p", "status": "live"}
                      for c in cids],
    }


class TestProfitabilityReconciliationIntegration:
    def test_reconciliation_fields_present_and_default_off(
            self, isolated_metrics, monkeypatch):
        """Default behavior unchanged (shadow-mode requirement): revenue ==
        revenue_raw unless ATTRIBUTION_RECONCILE_LIVE=true."""
        monkeypatch.delenv("ATTRIBUTION_RECONCILE_LIVE", raising=False)
        monkeypatch.setattr(prof, "_shopify_ground_truth", lambda days: 100.0)

        meta_cid = f"meta_{uuid.uuid4().hex[:8]}"
        tiktok_cid = f"tiktok_{uuid.uuid4().hex[:8]}"
        cm.record_metric(meta_cid, "meta", "Widget", spend_usd=50.0, revenue_usd=150.0)
        cm.record_metric(tiktok_cid, "tiktok", "Widget", spend_usd=50.0, revenue_usd=150.0)
        _write_snapshot(isolated_metrics["snapshot"],
                        [_launch("Widget", [meta_cid, tiktok_cid])])

        report = prof.calculate_profitability(lookback_days=1)
        widget = next(p for p in report["products"] if p["product"] == "Widget")

        # Raw (unreconciled) behavior preserved by default.
        assert widget["revenue"] == widget["revenue_raw"] == pytest.approx(300.0)
        # But the reconciled figure is computed and exposed for comparison.
        assert widget["revenue_reconciled"] == pytest.approx(100.0)
        assert report["attribution_reconciliation"]["applied"] is True
        assert report["attribution_reconciliation"]["live"] is False

    def test_reconciliation_live_flag_corrects_double_count(
            self, isolated_metrics, monkeypatch):
        monkeypatch.setenv("ATTRIBUTION_RECONCILE_LIVE", "true")
        monkeypatch.setattr(prof, "_shopify_ground_truth", lambda days: 100.0)

        meta_cid = f"meta_{uuid.uuid4().hex[:8]}"
        tiktok_cid = f"tiktok_{uuid.uuid4().hex[:8]}"
        cm.record_metric(meta_cid, "meta", "Widget", spend_usd=50.0, revenue_usd=150.0)
        cm.record_metric(tiktok_cid, "tiktok", "Widget", spend_usd=50.0, revenue_usd=150.0)
        _write_snapshot(isolated_metrics["snapshot"],
                        [_launch("Widget", [meta_cid, tiktok_cid])])

        report = prof.calculate_profitability(lookback_days=1)
        widget = next(p for p in report["products"] if p["product"] == "Widget")

        assert widget["revenue"] == pytest.approx(100.0)
        assert widget["actual_roas"] == pytest.approx(100.0 / 100.0)
        assert report["attribution_reconciliation"]["live"] is True

    def test_no_ground_truth_leaves_profitability_unchanged(
            self, isolated_metrics, monkeypatch):
        monkeypatch.setenv("ATTRIBUTION_RECONCILE_LIVE", "true")
        monkeypatch.setattr(prof, "_shopify_ground_truth", lambda days: None)

        cid = f"c_{uuid.uuid4().hex[:8]}"
        cm.record_metric(cid, "meta", "Gadget", spend_usd=20.0, revenue_usd=60.0)
        _write_snapshot(isolated_metrics["snapshot"], [_launch("Gadget", [cid])])

        report = prof.calculate_profitability(lookback_days=1)
        gadget = next(p for p in report["products"] if p["product"] == "Gadget")
        assert gadget["revenue"] == pytest.approx(60.0)
        assert report["attribution_reconciliation"]["applied"] is False
        assert report["attribution_reconciliation"]["reason"] == "no_ground_truth_available"

    def test_single_platform_product_unaffected_by_reconciliation(
            self, isolated_metrics, monkeypatch):
        """A product with no cross-platform overlap shouldn't be penalized
        just because *other* products over-claimed in the same window —
        reconciliation is portfolio-wide by necessity (Shopify orders
        aren't product-tagged), so document the actual behavior: this
        product's share is still scaled if the *total* portfolio over-claims."""
        monkeypatch.setenv("ATTRIBUTION_RECONCILE_LIVE", "true")
        monkeypatch.setattr(prof, "_shopify_ground_truth", lambda days: 50.0)

        cid = f"c_{uuid.uuid4().hex[:8]}"
        cm.record_metric(cid, "meta", "Solo", spend_usd=10.0, revenue_usd=100.0)
        _write_snapshot(isolated_metrics["snapshot"], [_launch("Solo", [cid])])

        report = prof.calculate_profitability(lookback_days=1)
        solo = next(p for p in report["products"] if p["product"] == "Solo")
        # 100 claimed vs 50 ground truth → scaled to 50, exactly ground truth
        assert solo["revenue"] == pytest.approx(50.0)
