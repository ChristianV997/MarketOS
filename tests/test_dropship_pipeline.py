"""Tests for backend.dropship — the end-to-end cycle and orchestrator wiring."""
import json
import os

import backend.dropship as dropship
from backend.dropship import run_dropship_cycle


def _fake_opportunities(limit=10, **kw):
    return [
        {"product": "Test Widget", "signal_score": 0.9, "source": "test",
         "platform": "meta", "market_saturation": 0.1, "competitor_count": 3,
         "competition_difficulty": "easy", "opportunity_score": 0.85},
    ]


def test_full_cycle_dry_run(monkeypatch):
    monkeypatch.setattr("backend.discovery.discover_products", _fake_opportunities)
    summary = run_dropship_cycle(max_products=1, budget_daily=40.0)
    assert summary["status"] in ("ok", "skipped")
    assert summary["discovered"] == 1
    assert summary["validated"] == 1
    if summary["status"] == "ok":
        launch = summary["launches"][0]
        assert launch["product"] == "Test Widget"
        # Budget scales with confidence
        assert launch["budget"] == round(40.0 * launch["confidence"], 2)
        assert launch["predicted_roas"] > 0


def test_cycle_persists_snapshot(monkeypatch):
    monkeypatch.setattr("backend.discovery.discover_products", _fake_opportunities)
    run_dropship_cycle(max_products=1)
    # conftest points MARKETOS_STATE_DIR at a temp dir; snapshot must exist there
    path = dropship._SNAPSHOT_PATH
    assert os.path.exists(path)
    with open(path) as f:
        snap = json.load(f)
    assert "status" in snap and "launches" in snap


def test_cycle_no_opportunities(monkeypatch):
    monkeypatch.setattr("backend.discovery.discover_products", lambda **kw: [])
    summary = run_dropship_cycle()
    assert summary["status"] == "skipped"
    assert summary["reason"] == "no_opportunities"


def test_cycle_no_green_products(monkeypatch):
    monkeypatch.setattr("backend.discovery.discover_products", _fake_opportunities)
    red = {"product": "Test Widget", "confidence": 0.1, "recommendation": "red",
           "ready_for_creation": False, "risk_flags": ["no_supplier"],
           "margin": None, "competition": None, "supplier": None,
           "suggested_price": None}
    monkeypatch.setattr("backend.validation.validate_product", lambda name: red)
    summary = run_dropship_cycle()
    assert summary["status"] == "skipped"
    assert summary["reason"] == "no_green_products"
    assert summary["green"] == 0


def test_cycle_stages_calibration_prediction(monkeypatch):
    monkeypatch.setattr("backend.discovery.discover_products", _fake_opportunities)
    from simulation.calibration import calibration_store
    calibration_store.reset()
    summary = run_dropship_cycle(max_products=1)
    if summary["status"] == "ok":
        # A pending prediction exists for the launched product; pairing an
        # outcome must succeed.
        assert calibration_store.record_outcome("Test Widget", actual_roas=1.8)


def test_discovery_failure_is_error(monkeypatch):
    def _boom(**kw):
        raise RuntimeError("adapters down")
    monkeypatch.setattr("backend.discovery.discover_products", _boom)
    summary = run_dropship_cycle()
    assert summary["status"] == "error"
    assert summary["stage"] == "discover"


# ── orchestrator worker wiring ────────────────────────────────────────────────

def test_orchestrator_worker_registers_artifacts(monkeypatch):
    import orchestrator.main as om

    fake_summary = {
        "status": "ok", "discovered": 1, "green": 1, "launched": 1,
        "launches": [{
            "product": "Test Widget", "confidence": 0.8, "predicted_roas": 2.0,
            "campaigns": [
                {"platform": "tiktok", "status": "live",
                 "campaign_id": "dry_test_cid_1", "adgroup_id": "ag1",
                 "ad_ids": ["a1"], "budget": 20.0,
                 "hook": "h", "angle": "problem-solution"},
                {"platform": "meta", "status": "error", "error": "boom"},
            ],
        }],
    }
    monkeypatch.setattr("backend.dropship.run_dropship_cycle", lambda: fake_summary)
    monkeypatch.setattr(om._dropship_limiter, "last_run", 0.0)
    om._campaign_artifacts.pop("dry_test_cid_1", None)

    result = om._run_dropship_pipeline()
    assert result["status"] == "ok"
    assert result["launched"] == 1
    # The live campaign is registered for ROAS attribution; the errored one isn't
    assert "dry_test_cid_1" in om._campaign_artifacts
    art = om._campaign_artifacts["dry_test_cid_1"]
    assert art.product == "Test Widget"
    assert art.phase == "DROPSHIP"


def test_orchestrator_worker_rate_limited(monkeypatch):
    import time
    import orchestrator.main as om
    monkeypatch.setattr(om._dropship_limiter, "last_run", time.time())
    result = om._run_dropship_pipeline()
    assert result == {"status": "skipped", "reason": "rate_limited"}
