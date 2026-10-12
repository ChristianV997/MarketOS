"""Tests for Step 52 — Production Hardening + Agent Hierarchy.

Covers:
  1. Data Integrity Layer — schema validation, UTM, attribution reconciliation
  2. Global Risk Engine   — hard caps, kill-switch, drawdown
  3. Replay Buffer Persistence — save/load JSON
  4. World Model Calibration   — Bayesian update, stats
  5. Agent Hierarchy           — ScalingAgent, GeoAgent, AudienceAgent, RiskAgent
  6. Agent Metrics Registry    — PnL, decision counts, drift
  7. Dashboard endpoints       — /agents, /risk/status, /risk/killswitch/*, /capital_allocation, /prediction_errors
"""
from __future__ import annotations

import os
import tempfile

import pytest
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# 1. Data Integrity Layer
# ---------------------------------------------------------------------------


class TestDataIntegrity:
    def _valid_campaign(self):
        return {
            "campaign_id": "camp_001",
            "spend": 50.0,
            "revenue": 120.0,
            "utm_campaign": "summer_sale",
            "utm_source": "tiktok",
            "utm_medium": "cpc",
        }

    def test_valid_campaign_passes(self):
        from core.data_integrity import validate_campaign
        validate_campaign(self._valid_campaign())  # no exception

    def test_campaign_missing_field_raises(self):
        from core.data_integrity import validate_campaign, ValidationError
        bad = self._valid_campaign()
        del bad["campaign_id"]
        with pytest.raises(ValidationError):
            validate_campaign(bad)

    def test_campaign_missing_utm_raises(self):
        from core.data_integrity import validate_campaign, ValidationError
        bad = self._valid_campaign()
        del bad["utm_campaign"]
        with pytest.raises(ValidationError):
            validate_campaign(bad)

    def test_campaign_negative_spend_raises(self):
        from core.data_integrity import validate_campaign, ValidationError
        bad = self._valid_campaign()
        bad["spend"] = -10.0
        with pytest.raises(ValidationError):
            validate_campaign(bad)

    def test_valid_product_passes(self):
        from core.data_integrity import validate_product
        validate_product({"name": "widget", "score": 0.8})

    def test_product_invalid_score_raises(self):
        from core.data_integrity import validate_product, ValidationError
        with pytest.raises(ValidationError):
            validate_product({"name": "widget", "score": 1.5})

    def test_product_empty_name_raises(self):
        from core.data_integrity import validate_product, ValidationError
        with pytest.raises(ValidationError):
            validate_product({"name": "", "score": 0.5})

    def test_valid_creative_passes(self):
        from core.data_integrity import validate_creative
        validate_creative({"creative_id": "cr_1", "headline": "Buy now", "format": "image"})

    def test_creative_invalid_format_raises(self):
        from core.data_integrity import validate_creative, ValidationError
        with pytest.raises(ValidationError):
            validate_creative({"creative_id": "cr_1", "headline": "Buy", "format": "pdf"})

    def test_ingest_campaign_reconciles_utm(self):
        from core.data_integrity import ingest
        data = {
            "campaign_id": "c1",
            "spend": 10.0,
            "revenue": 20.0,
            "utm_campaign": "x",
            "utm_source": "fb",
            "utm_medium": "cpc",
        }
        result = ingest("campaign", data)
        assert result["utm_content"] == ""
        assert result["utm_term"] == ""

    def test_ingest_unknown_entity_raises(self):
        from core.data_integrity import ingest
        with pytest.raises(ValueError):
            ingest("unknown_entity", {})

    def test_utm_validate_returns_missing_fields(self):
        from core.data_integrity import validate_utm
        missing = validate_utm({"utm_campaign": "x"})
        assert "utm_source" in missing
        assert "utm_medium" in missing

    def test_reconcile_attribution_fills_defaults(self):
        from core.data_integrity import reconcile_attribution
        out = reconcile_attribution({})
        assert out["utm_campaign"] == "unknown_campaign"
        assert out["utm_source"] == "unknown_source"


# ---------------------------------------------------------------------------
# 2. Global Risk Engine
# ---------------------------------------------------------------------------


class TestGlobalRiskEngine:
    def _engine(self, max_daily=1000.0, max_dd=0.30):
        from core.risk.global_risk_engine import GlobalRiskEngine
        return GlobalRiskEngine(max_daily_spend=max_daily, max_drawdown=max_dd)

    def test_all_clear_returns_proposed_budget(self):
        eng = self._engine()
        r = eng.enforce(100.0, 1000.0, 1000.0)
        assert r.allowed is True
        assert r.adjusted_budget == 100.0

    def test_kill_switch_blocks_spend(self):
        eng = self._engine()
        eng.activate_kill_switch("test")
        r = eng.enforce(100.0, 1000.0, 1000.0)
        assert r.allowed is False
        assert r.adjusted_budget == 0.0
        assert "kill_switch" in r.triggered_cap

    def test_deactivate_kill_switch(self):
        eng = self._engine()
        eng.activate_kill_switch()
        eng.deactivate_kill_switch()
        r = eng.enforce(100.0, 1000.0, 1000.0)
        assert r.allowed is True

    def test_drawdown_exceeded_blocks_spend(self):
        eng = self._engine(max_dd=0.30)
        # capital dropped 40% from peak → exceeds 30% max_drawdown
        r = eng.enforce(100.0, current_capital=600.0, peak_capital=1000.0)
        assert r.allowed is False
        assert r.triggered_cap == "drawdown"

    def test_daily_spend_cap_limits_budget(self):
        eng = self._engine(max_daily=500.0)
        eng.record_spend(400.0)
        r = eng.enforce(200.0, 1000.0, 1000.0)
        assert r.allowed is True
        assert r.adjusted_budget == 100.0  # remaining = 500 - 400 = 100

    def test_daily_spend_fully_exhausted(self):
        eng = self._engine(max_daily=100.0)
        eng.record_spend(100.0)
        r = eng.enforce(50.0, 1000.0, 1000.0)
        assert r.allowed is False

    def test_status_dict_structure(self):
        eng = self._engine()
        s = eng.status()
        assert "kill_switch_active" in s
        assert "max_daily_spend" in s
        assert "today_spend" in s

    def test_drawdown_not_exceeded_within_threshold(self):
        eng = self._engine(max_dd=0.30)
        r = eng.enforce(100.0, 800.0, 1000.0)  # 20% drawdown < 30%
        assert r.allowed is True


# ---------------------------------------------------------------------------
# 3. Replay Buffer Persistence
# ---------------------------------------------------------------------------


class TestReplayBufferPersistence:
    def test_save_and_load(self):
        from backend.learning.replay_buffer import ReplayBuffer
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        try:
            buf = ReplayBuffer(capacity=100, persist_path=path)
            buf.add([1.0, 2.0], {"variant": "A"}, 1.5)
            buf.add([3.0, 4.0], {"variant": "B"}, 2.0)
            # Load into a new buffer instance
            buf2 = ReplayBuffer(capacity=100, persist_path=path)
            assert len(buf2) == 2
        finally:
            os.unlink(path)

    def test_load_missing_file_is_silent(self):
        from backend.learning.replay_buffer import ReplayBuffer
        buf = ReplayBuffer(capacity=100, persist_path="/tmp/nonexistent_replay_test.json")
        assert len(buf) == 0

    def test_no_persist_path_works(self):
        from backend.learning.replay_buffer import ReplayBuffer
        buf = ReplayBuffer(capacity=100, persist_path=None)
        buf.add([1.0], {"x": 1}, 0.5)
        assert len(buf) == 1

    def test_add_batch_persists(self):
        from backend.learning.replay_buffer import ReplayBuffer
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        try:
            buf = ReplayBuffer(capacity=50, persist_path=path)
            exps = [{"state": [float(i)], "action": {"v": i}, "reward": float(i)} for i in range(5)]
            buf.add_batch(exps)
            buf2 = ReplayBuffer(capacity=50, persist_path=path)
            assert len(buf2) == 5
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# 4. World Model Calibration
# ---------------------------------------------------------------------------


class TestWorldModelCalibration:
    def test_update_increases_sample_count(self):
        from backend.learning.world_model_calibration import WorldModelCalibrator
        wmc = WorldModelCalibrator()
        wmc.update(1.5, 1.2)
        assert wmc.total_updates == 1

    def test_stats_after_updates(self):
        from backend.learning.world_model_calibration import WorldModelCalibrator
        wmc = WorldModelCalibrator()
        for _ in range(20):
            wmc.update(2.0, 1.8)
        stats = wmc.stats()
        assert "bias" in stats
        assert "uncertainty" in stats
        assert "mae" in stats
        assert "rmse" in stats
        assert stats["n_samples"] == 20

    def test_correct_prediction_shifts_by_bias(self):
        from backend.learning.world_model_calibration import WorldModelCalibrator
        wmc = WorldModelCalibrator()
        for _ in range(50):
            wmc.update(2.0, 1.5)  # consistent over-prediction by +0.5
        corrected = wmc.correct_prediction(2.0)
        # Should be shifted downward (bias > 0 → corrected < 2.0)
        assert corrected < 2.0

    def test_prediction_errors_list(self):
        from backend.learning.world_model_calibration import WorldModelCalibrator
        wmc = WorldModelCalibrator()
        wmc.update(1.5, 1.0)
        errors = wmc.prediction_errors()
        assert len(errors) == 1
        assert errors[0]["predicted"] == 1.5
        assert errors[0]["actual"] == 1.0
        assert errors[0]["error"] == pytest.approx(0.5, abs=0.01)


# ---------------------------------------------------------------------------
# 5. Agent Hierarchy
# ---------------------------------------------------------------------------


class TestScalingAgent:
    def test_scale_above_threshold(self):
        from agents.hierarchy import ScalingAgent
        agent = ScalingAgent(scale_roas=1.8)
        dec = agent.decide({"roas": 2.5, "current_budget": 100.0})
        assert dec.action == "scale"
        assert dec.agent == "scaling"
        assert 0 < dec.confidence <= 1.0

    def test_kill_below_threshold(self):
        from agents.hierarchy import ScalingAgent
        agent = ScalingAgent(kill_roas=0.8)
        dec = agent.decide({"roas": 0.5, "current_budget": 100.0})
        assert dec.action == "kill"

    def test_hold_in_learning_band(self):
        from agents.hierarchy import ScalingAgent
        agent = ScalingAgent(scale_roas=1.8, kill_roas=0.8)
        dec = agent.decide({"roas": 1.2, "current_budget": 100.0})
        assert dec.action == "hold"


class TestGeoAgent:
    def test_expand_high_roas(self):
        from agents.hierarchy import GeoAgent
        agent = GeoAgent(expand_roas=2.0)
        dec = agent.decide({"country": "US", "roas": 2.5})
        assert dec.action == "expand"
        assert dec.metadata["country"] == "US"

    def test_pause_low_roas(self):
        from agents.hierarchy import GeoAgent
        agent = GeoAgent(pause_roas=0.9)
        dec = agent.decide({"country": "CA", "roas": 0.7})
        assert dec.action == "pause"

    def test_test_mid_roas(self):
        from agents.hierarchy import GeoAgent
        agent = GeoAgent(expand_roas=2.0, pause_roas=0.9)
        dec = agent.decide({"country": "DE", "roas": 1.5})
        assert dec.action == "test"


class TestAudienceAgent:
    def test_expand_good_signals(self):
        from agents.hierarchy import AudienceAgent
        agent = AudienceAgent(min_ctr=0.01, min_cvr=0.01)
        dec = agent.decide({"ctr": 0.05, "cvr": 0.03, "audience_size": 50_000})
        assert dec.action == "expand"

    def test_hold_large_audience(self):
        from agents.hierarchy import AudienceAgent
        agent = AudienceAgent(min_ctr=0.01, min_cvr=0.01)
        dec = agent.decide({"ctr": 0.05, "cvr": 0.03, "audience_size": 200_000})
        assert dec.action == "hold"

    def test_retarget_poor_signals(self):
        from agents.hierarchy import AudienceAgent
        agent = AudienceAgent(min_ctr=0.02, min_cvr=0.02)
        dec = agent.decide({"ctr": 0.005, "cvr": 0.001})
        assert dec.action == "retarget"


class TestRiskAgent:
    def test_kill_switch_override(self):
        from agents.hierarchy import RiskAgent
        agent = RiskAgent()
        dec = agent.decide({"kill_switch": True})
        assert dec.action == "kill"
        assert dec.metadata["override"] is True
        assert RiskAgent.is_override(dec)

    def test_drawdown_triggers_kill(self):
        from agents.hierarchy import RiskAgent
        agent = RiskAgent(max_drawdown=0.30)
        dec = agent.decide({
            "current_capital": 600.0,
            "peak_capital": 1000.0,
        })
        assert dec.action == "kill"
        assert RiskAgent.is_override(dec)

    def test_daily_spend_cap_pauses(self):
        from agents.hierarchy import RiskAgent
        agent = RiskAgent(max_daily_spend=1000.0)
        dec = agent.decide({"today_spend": 1100.0})
        assert dec.action == "pause"
        assert RiskAgent.is_override(dec)

    def test_low_roas_kills(self):
        from agents.hierarchy import RiskAgent
        agent = RiskAgent(kill_roas=0.5)
        dec = agent.decide({"roas": 0.3})
        assert dec.action == "kill"

    def test_no_risk_holds(self):
        from agents.hierarchy import RiskAgent
        agent = RiskAgent()
        dec = agent.decide({
            "current_capital": 900.0,
            "peak_capital": 1000.0,
            "today_spend": 100.0,
            "roas": 1.5,
        })
        assert dec.action == "hold"
        assert dec.metadata.get("override") is False


# ---------------------------------------------------------------------------
# 6. Agent Metrics Registry
# ---------------------------------------------------------------------------


class TestAgentMetricsRegistry:
    def test_record_decision_increments_count(self):
        from backend.agents.agent_metrics import AgentMetricsRegistry
        reg = AgentMetricsRegistry()
        reg.record_decision("scaling", "scale")
        reg.record_decision("scaling", "hold")
        data = reg.get("scaling")
        assert data["total_decisions"] == 2
        assert data["decisions_by_action"]["scale"] == 1

    def test_record_pnl(self):
        from backend.agents.agent_metrics import AgentMetricsRegistry
        reg = AgentMetricsRegistry()
        reg.record_pnl("scaling", revenue=200.0, cost=100.0)
        data = reg.get("scaling")
        assert data["cumulative_pnl"] == pytest.approx(100.0)

    def test_drift_not_detected_insufficient_data(self):
        from backend.agents.agent_metrics import AgentMetricsRegistry
        reg = AgentMetricsRegistry()
        reg.record_prediction_error("scaling", 1.5, 1.0)
        data = reg.get("scaling")
        assert data["drift_detected"] is False  # < 10 samples

    def test_drift_detected_high_error(self):
        from backend.agents.agent_metrics import AgentMetrics
        m = AgentMetrics(agent_name="test")
        for _ in range(20):
            m.record_prediction_error(5.0, 0.0)  # error = 5.0
        assert m.drift_detected(threshold=0.5) is True

    def test_snapshot_returns_all_agents(self):
        from backend.agents.agent_metrics import AgentMetricsRegistry
        reg = AgentMetricsRegistry()
        reg.record_decision("scaling", "scale")
        reg.record_decision("geo", "expand")
        snap = reg.snapshot()
        names = {s["agent"] for s in snap}
        assert "scaling" in names
        assert "geo" in names

    def test_unknown_agent_returns_none(self):
        from backend.agents.agent_metrics import AgentMetricsRegistry
        reg = AgentMetricsRegistry()
        assert reg.get("nonexistent") is None


# ---------------------------------------------------------------------------
# 7. Dashboard Endpoints
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def client():
    from backend.api import app
    from backend.identity.operator_gates import runtime_control_gate
    from backend.identity.workspaces import WorkspaceAccess

    # The kill-switch routes are operator-only. This module checks their behavior for an authorized caller;
    # refusal is covered in tests/identity/test_runtime_control_gates.py.
    operator = WorkspaceAccess("https://issuer.test", "synthetic-operator", "ws_synthetic", "internal", "synthetic", "internal_operator")
    app.dependency_overrides[runtime_control_gate] = lambda: operator
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(runtime_control_gate, None)


class TestAgentsEndpoint:
    def test_returns_dict(self, client):
        resp = client.get("/agents")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, dict)

    def test_has_agents_and_risk_status(self, client):
        data = client.get("/agents").json()
        assert "agents" in data
        assert "risk_status" in data
        assert isinstance(data["agents"], list)

    def test_risk_status_fields(self, client):
        data = client.get("/agents").json()
        rs = data["risk_status"]
        assert "kill_switch_active" in rs
        assert "max_daily_spend" in rs
        assert "today_spend" in rs


class TestRiskEngineEndpoints:
    def test_risk_status_returns_dict(self, client):
        resp = client.get("/risk/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "kill_switch_active" in data

    def test_activate_deactivate_kill_switch(self, client):
        resp = client.post("/risk/killswitch/activate?reason=testing")
        assert resp.status_code == 200
        assert resp.json()["kill_switch_active"] is True

        resp2 = client.post("/risk/killswitch/deactivate")
        assert resp2.status_code == 200
        assert resp2.json()["kill_switch_active"] is False

    def test_kill_switch_reflected_in_status(self, client):
        client.post("/risk/killswitch/activate?reason=test_check")
        status = client.get("/risk/status").json()
        assert status["kill_switch_active"] is True
        client.post("/risk/killswitch/deactivate")


class TestCapitalAllocationEndpoint:
    def test_returns_dict(self, client):
        resp = client.get("/capital_allocation")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, dict)

    def test_has_allocations_and_risk_status(self, client):
        data = client.get("/capital_allocation").json()
        assert "allocations" in data
        assert "total_budget" in data
        assert "risk_status" in data

    def test_allocations_fields(self, client):
        data = client.get("/capital_allocation").json()
        for alloc in data["allocations"]:
            assert "safe_budget" in alloc
            assert "risk_override" in alloc
            assert "risk_reason" in alloc


class TestPredictionErrorsEndpoint:
    def test_returns_dict(self, client):
        resp = client.get("/prediction_errors")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, dict)

    def test_has_errors_and_calibration(self, client):
        data = client.get("/prediction_errors").json()
        assert "errors" in data
        assert "calibration" in data
        assert "total_updates" in data

    def test_calibration_fields(self, client):
        data = client.get("/prediction_errors").json()
        cal = data["calibration"]
        assert "bias" in cal
        assert "uncertainty" in cal

    def test_limit_param(self, client):
        resp = client.get("/prediction_errors?limit=10")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["errors"]) <= 10
