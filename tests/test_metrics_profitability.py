"""Tests for backend.metrics — campaign metrics, profitability, forecast."""
import json
import uuid

import pytest

import backend.metrics.campaign_metrics as cm
import backend.metrics.profitability as prof
from backend.core.persistence import save_json_atomic


@pytest.fixture
def isolated_metrics(monkeypatch, tmp_path):
    """Point the metric log and launch snapshot at a private temp dir."""
    metrics_path = tmp_path / "campaign_metrics.jsonl"
    snapshot_path = tmp_path / "dropship.json"
    monkeypatch.setattr(cm, "_METRICS_PATH", metrics_path)
    monkeypatch.setattr(prof, "_DROPSHIP_SNAPSHOT", str(snapshot_path))
    return {"metrics": metrics_path, "snapshot": snapshot_path}


def _write_snapshot(path, launches):
    save_json_atomic(str(path), {"status": "ok", "launches": launches})


def _launch(product, cids, predicted_roas=2.0, confidence=0.8, budget=40.0):
    return {
        "product": product,
        "confidence": confidence,
        "predicted_roas": predicted_roas,
        "budget": budget,
        "campaigns": [{"campaign_id": c, "platform": "tiktok", "status": "live"}
                      for c in cids],
    }


# ── campaign metrics ──────────────────────────────────────────────────────────

def test_record_and_aggregate(isolated_metrics):
    cid = f"c_{uuid.uuid4().hex[:8]}"
    assert cm.record_metric(cid, "tiktok", "Widget", spend_usd=10.0, revenue_usd=25.0)
    assert cm.record_metric(cid, "tiktok", "Widget", spend_usd=10.0, revenue_usd=15.0)

    perf = cm.campaign_performance(lookback_days=1)
    row = next(c for c in perf if c["campaign_id"] == cid)
    assert row["spend"] == 20.0
    assert row["revenue"] == 40.0
    assert row["roas"] == 2.0
    assert row["profit"] == 20.0
    assert row["data_points"] == 2


def test_record_metric_rejects_empty_id(isolated_metrics):
    assert cm.record_metric("", "tiktok", "Widget", spend_usd=10.0) is False


def test_campaign_by_id(isolated_metrics):
    cid = f"c_{uuid.uuid4().hex[:8]}"
    cm.record_metric(cid, "meta", "Gadget", spend_usd=30.0, revenue_usd=60.0,
                     conversions=3)
    detail = cm.campaign_by_id(cid)
    assert detail["total_spend"] == 30.0
    assert detail["roas"] == 2.0
    assert detail["total_conversions"] == 3
    assert cm.campaign_by_id("nonexistent_xyz") is None


def test_platform_filter(isolated_metrics):
    a, b = f"c_{uuid.uuid4().hex[:8]}", f"c_{uuid.uuid4().hex[:8]}"
    cm.record_metric(a, "tiktok", "W", spend_usd=5.0, revenue_usd=5.0)
    cm.record_metric(b, "meta", "W", spend_usd=5.0, revenue_usd=5.0)
    platforms = {c["platform"] for c in cm.campaign_performance(platform="meta")}
    assert platforms == {"meta"}


def test_corrupt_lines_skipped(isolated_metrics):
    cid = f"c_{uuid.uuid4().hex[:8]}"
    cm.record_metric(cid, "tiktok", "W", spend_usd=5.0, revenue_usd=10.0)
    with open(isolated_metrics["metrics"], "a") as f:
        f.write("NOT JSON\n")
    perf = cm.campaign_performance(lookback_days=1)
    assert any(c["campaign_id"] == cid for c in perf)


# ── profitability ─────────────────────────────────────────────────────────────

def test_profitability_attribution(isolated_metrics):
    cid = f"c_{uuid.uuid4().hex[:8]}"
    _write_snapshot(isolated_metrics["snapshot"],
                    [_launch("Hot Widget", [cid], predicted_roas=2.0)])
    cm.record_metric(cid, "tiktok", "Hot Widget", spend_usd=50.0, revenue_usd=150.0)

    report = prof.calculate_profitability(lookback_days=7)
    assert report["num_products"] == 1
    p = report["products"][0]
    assert p["product"] == "Hot Widget"
    assert p["actual_roas"] == 3.0
    assert p["actual_profit"] == 100.0
    assert p["status"] == "profitable"
    # actual 3.0 vs predicted 2.0 → +50% error
    assert p["roas_error_pct"] == 50.0
    assert report["accuracy"]["bias"] == "pessimistic"


def test_profitability_no_spend_is_awaiting(isolated_metrics):
    cid = f"c_{uuid.uuid4().hex[:8]}"
    _write_snapshot(isolated_metrics["snapshot"], [_launch("Silent Widget", [cid])])
    report = prof.calculate_profitability(lookback_days=7)
    assert report["num_products"] == 0
    assert "Silent Widget" in report["awaiting_data"]


def test_profitability_loss_detected(isolated_metrics):
    cid = f"c_{uuid.uuid4().hex[:8]}"
    _write_snapshot(isolated_metrics["snapshot"], [_launch("Dud Widget", [cid])])
    cm.record_metric(cid, "tiktok", "Dud Widget", spend_usd=100.0, revenue_usd=40.0)
    report = prof.calculate_profitability(lookback_days=7)
    p = report["products"][0]
    assert p["status"] == "loss"
    assert p["actual_profit"] == -60.0
    assert report["total_profit"] == -60.0


def test_profitability_empty(isolated_metrics):
    _write_snapshot(isolated_metrics["snapshot"], [])
    report = prof.calculate_profitability(lookback_days=7)
    assert report["status"] == "ok"
    assert report["total_profit"] == 0.0
    assert report["num_products"] == 0


# ── ground truth reconciliation (Shopify + Stripe) ────────────────────────────

def test_ground_truth_neither_source_available_skips_reconciliation(monkeypatch, isolated_metrics):
    """Neither Shopify nor Stripe configured -> reconciled revenue == raw
    (reconcile_revenue's "no_ground_truth_available" early-return path)."""
    monkeypatch.setattr(prof, "_shopify_ground_truth", lambda days: None)
    monkeypatch.setattr(prof, "_stripe_ground_truth", lambda days: None)
    cid = f"c_{uuid.uuid4().hex[:8]}"
    _write_snapshot(isolated_metrics["snapshot"], [_launch("Widget", [cid])])
    cm.record_metric(cid, "tiktok", "Widget", spend_usd=50.0, revenue_usd=150.0)

    report = prof.calculate_profitability(lookback_days=7)
    assert report["total_revenue_reconciled"] == report["total_revenue_raw"] == 150.0


def test_ground_truth_sums_shopify_and_stripe_not_just_one(monkeypatch, isolated_metrics):
    """Regression test: ground truth must be the SUM of both sources, not
    just Shopify. Raw revenue is 150; Shopify alone (80) would trigger
    scaling (raw > 80), but Shopify+Stripe (80+90=170) should not, since
    raw(150) <= 170. If the combination logic silently dropped Stripe,
    this would incorrectly scale revenue_reconciled down to ~80."""
    monkeypatch.setattr(prof, "_shopify_ground_truth", lambda days: 80.0)
    monkeypatch.setattr(prof, "_stripe_ground_truth", lambda days: 90.0)
    cid = f"c_{uuid.uuid4().hex[:8]}"
    _write_snapshot(isolated_metrics["snapshot"], [_launch("Widget", [cid])])
    cm.record_metric(cid, "tiktok", "Widget", spend_usd=50.0, revenue_usd=150.0)

    report = prof.calculate_profitability(lookback_days=7)
    # raw (150) <= combined ground truth (170) -> "within_ground_truth" ->
    # reconciled revenue stays at raw, unscaled.
    assert report["total_revenue_reconciled"] == 150.0


def test_ground_truth_scales_down_when_raw_exceeds_combined_total(monkeypatch, isolated_metrics):
    """Combined ground truth (80+40=120) is below raw revenue (150) ->
    reconciliation scales down proportionally."""
    monkeypatch.setattr(prof, "_shopify_ground_truth", lambda days: 80.0)
    monkeypatch.setattr(prof, "_stripe_ground_truth", lambda days: 40.0)
    cid = f"c_{uuid.uuid4().hex[:8]}"
    _write_snapshot(isolated_metrics["snapshot"], [_launch("Widget", [cid])])
    cm.record_metric(cid, "tiktok", "Widget", spend_usd=50.0, revenue_usd=150.0)

    report = prof.calculate_profitability(lookback_days=7)
    assert report["total_revenue_reconciled"] == 120.0


def test_ground_truth_falls_back_to_single_source(monkeypatch, isolated_metrics):
    """Only Stripe available (Shopify None) -> combined ground truth == Stripe alone."""
    monkeypatch.setattr(prof, "_shopify_ground_truth", lambda days: None)
    monkeypatch.setattr(prof, "_stripe_ground_truth", lambda days: 60.0)
    cid = f"c_{uuid.uuid4().hex[:8]}"
    _write_snapshot(isolated_metrics["snapshot"], [_launch("Widget", [cid])])
    cm.record_metric(cid, "tiktok", "Widget", spend_usd=50.0, revenue_usd=150.0)

    report = prof.calculate_profitability(lookback_days=7)
    # raw (150) > ground truth (60) -> scaled down to 60
    assert report["total_revenue_reconciled"] == 60.0


def test_stripe_ground_truth_none_when_unconfigured(monkeypatch):
    """Regression test: connectors.stripe_connector.get_revenue() always
    returns nonzero mock charges even with no STRIPE_SECRET_KEY (by design,
    for callers that just want a usable figure). _stripe_ground_truth()
    must NOT treat that mock fallback as real ground truth — it should
    short-circuit to None whenever Stripe isn't actually configured, so
    reconciliation isn't silently contaminated by a phantom mock revenue."""
    monkeypatch.delenv("STRIPE_SECRET_KEY", raising=False)

    result = prof._stripe_ground_truth(lookback_days=1)
    assert result is None


def test_stripe_ground_truth_returns_value_when_configured(monkeypatch):
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_fake")
    import connectors.stripe_connector as stripe_mod

    fixture_payload = {
        "data": [{"id": "ch_1", "amount": 5000, "currency": "usd", "status": "succeeded"}]
    }

    monkeypatch.setattr(stripe_mod, "STRIPE_SECRET_KEY", "sk_test_fake")
    monkeypatch.setattr(stripe_mod._stripe.Charge, "list", lambda *a, **kw: fixture_payload)

    result = prof._stripe_ground_truth(lookback_days=1)
    assert result == 50.0


# ── forecast ──────────────────────────────────────────────────────────────────

def test_forecast_no_campaigns(isolated_metrics):
    _write_snapshot(isolated_metrics["snapshot"], [])
    fc = prof.revenue_forecast(horizon_days=7)
    assert fc["status"] == "no_campaigns"
    assert fc["spend_projected"] == 0.0


def test_forecast_bands_ordered(isolated_metrics):
    cid = f"c_{uuid.uuid4().hex[:8]}"
    _write_snapshot(isolated_metrics["snapshot"],
                    [_launch("Fc Widget", [cid], predicted_roas=2.0, budget=50.0)])
    fc = prof.revenue_forecast(horizon_days=7)
    assert fc["status"] == "ok"
    assert fc["spend_projected"] == 350.0                       # 50 × 7
    assert (fc["revenue_pessimistic"] <= fc["revenue_realistic"]
            <= fc["revenue_optimistic"])
    assert fc["revenue_realistic"] == 700.0                     # ROAS 2.0, no correction


def test_forecast_applies_error_correction(isolated_metrics):
    """Observed under-performance drags the realistic band down."""
    cid = f"c_{uuid.uuid4().hex[:8]}"
    _write_snapshot(isolated_metrics["snapshot"],
                    [_launch("Corr Widget", [cid], predicted_roas=2.0, budget=50.0)])
    # Actual ROAS 1.0 vs predicted 2.0 → −50% error → correction ×0.5
    cm.record_metric(cid, "tiktok", "Corr Widget", spend_usd=40.0, revenue_usd=40.0)
    fc = prof.revenue_forecast(horizon_days=7)
    assert fc["error_correction_pct"] == -50.0
    assert fc["revenue_realistic"] == 350.0                     # 350 × (2.0×0.5)


# ── product timeline ──────────────────────────────────────────────────────────

def test_product_timeline(isolated_metrics):
    cid = f"c_{uuid.uuid4().hex[:8]}"
    cm.record_metric(cid, "tiktok", "Tl Widget", spend_usd=10.0, revenue_usd=30.0)
    cm.record_metric(cid, "tiktok", "Tl Widget", spend_usd=10.0, revenue_usd=5.0)
    tl = prof.product_timeline("Tl Widget", lookback_days=7)
    assert len(tl) == 2
    assert tl[0]["timestamp"] <= tl[1]["timestamp"]
    assert tl[0]["roas"] == 3.0
    assert prof.product_timeline("Nobody", lookback_days=7) == []


# ── standalone ingest ─────────────────────────────────────────────────────────

def test_ingest_campaign_metrics(isolated_metrics):
    result = cm.ingest_campaign_metrics()
    assert result["status"] == "ok"
    assert isinstance(result["num_campaigns"], int)
