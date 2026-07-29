"""Tests for orchestrator.main and its worker dispatchers."""
import pytest
from unittest.mock import patch, MagicMock


def test_run_signal_ingestion_ok():
    from orchestrator.main import _run_signal_ingestion
    with patch("core.signals.signal_engine.get", return_value=[
        {"product": "test", "score": 0.8}
    ]):
        result = _run_signal_ingestion()
    assert result["status"] == "ok"
    assert result["signals"] == 1


def test_commerce_cycle_consumes_ingested_signals():
    from orchestrator import main
    fake_report = MagicMock(
        artifact_id="commerce-cycle-test",
        dry_run=True,
        total_signals=1,
        summary={"ranked": 1, "creatives": 1, "launches": 1, "feedback_records": 1},
    )
    with patch("backend.commerce.run_commerce_cycle", return_value=fake_report) as run:
        with patch("core.signals.signal_engine.get", return_value=[{"product": "test", "score": 0.8}]):
            main._run_signal_ingestion()
        result = main._run_commerce_cycle()
    assert result["status"] == "ok"
    assert result["signals"] == 1
    assert result["dry_run"] is True
    assert run.call_args.kwargs["signals"] == [{"product": "test", "score": 0.8}]


def test_delayed_commerce_metrics_reconcile_only_live_campaigns(monkeypatch):
    from backend.contracts.campaign import CampaignAsset
    from backend.contracts.registry import get_registry
    from orchestrator.main import _reconcile_delayed_commerce_metrics
    import backend.integrations.tiktok_ads as tiktok

    registry = get_registry()
    asset = CampaignAsset(
        artifact_id="commerce-campaign:delayed-test",
        campaign_id="delayed-test",
        product="Delayed Product",
        phase="commerce",
        dry_run=False,
    )
    registry.register(asset)
    monkeypatch.setattr(tiktok, "_DRY_RUN", False)
    monkeypatch.setattr(tiktok, "is_configured", lambda: True)
    monkeypatch.setattr(tiktok, "fetch_roas", lambda ids: {"delayed-test": 2.3})

    class Calibration:
        calls = []

        def record_outcome(self, product, actual_roas):
            self.calls.append((product, actual_roas))

    calibration = Calibration()
    assert _reconcile_delayed_commerce_metrics(calibration) >= 1
    updated = registry.get("commerce-campaign:delayed-test")
    assert updated.outcome_recorded is True
    assert updated.actual_roas == 2.3
    assert ("Delayed Product", 2.3) in calibration.calls


def test_run_signal_ingestion_error():
    from orchestrator.main import _run_signal_ingestion
    with patch("core.signals.signal_engine.get", side_effect=RuntimeError("boom")):
        result = _run_signal_ingestion()
    assert result["status"] == "error"


def test_run_feedback_collection_skips_when_no_module():
    from orchestrator.main import _run_feedback_collection
    result = _run_feedback_collection()
    assert result["status"] in ("ok", "skipped")


def test_run_scaling_skips_when_ajo_not_configured():
    from orchestrator.main import _run_scaling
    with patch("backend.integrations.adobe_ajo.is_configured", return_value=False), \
         patch("core.content.playbook.playbook_memory.all", return_value=[]):
        result = _run_scaling()
    assert result["status"] == "skipped"


def test_live_commerce_loop_suppresses_legacy_playbook_launch(monkeypatch):
    import orchestrator.main as orch
    from core.content.playbook import Playbook, playbook_memory

    playbook_memory.upsert(Playbook(
        product="canonical-owner-test", phase="SCALE", top_hooks=["Hook"],
        top_angles=["Angle"], estimated_roas=2.0, confidence=0.9, evidence_count=1,
    ))
    monkeypatch.setattr(orch, "_COMMERCE_LOOP_LIVE", True)
    with patch("backend.integrations.tiktok_ads.launch_from_playbook") as launch:
        result = orch._run_scaling()
    assert launch.call_count == 0
    assert result["launched"] == 0


def test_collect_metrics_returns_dict():
    from orchestrator.main import _collect_metrics
    result = _collect_metrics()
    assert "avg_roas" in result
    assert "capital" in result
    assert "win_rate" in result


def test_phase_workers_cover_all_phases():
    from orchestrator.main import _PHASE_WORKERS
    from core.system.phase_controller import Phase
    for phase in Phase:
        assert phase in _PHASE_WORKERS
        assert len(_PHASE_WORKERS[phase]) > 0
