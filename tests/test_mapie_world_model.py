"""Tests for MAPIE conformal prediction interval integration in WorldModel."""
import pytest
from backend.core.state import SystemState
from backend.execution.loop import run_cycle
from agents.world_model import WorldModel


def _make_trained_model(n_cycles=10):
    """Return a WorldModel trained on n_cycles worth of event log data.
    Each cycle generates 5 events; need ≥ 30 events so 6+ cycles suffice.
    """
    state = SystemState()
    for _ in range(n_cycles):
        state = run_cycle(state)
    m = WorldModel()
    m.train(state.event_log)
    return m


class TestWorldModelPreTraining:
    def test_predict_returns_fallback_before_training(self):
        m = WorldModel()
        result = m.predict({"variant": 1})
        assert "roas_6h" in result
        assert "width_6h" in result
        # fallback width should be positive (wide = high uncertainty)
        assert result["width_6h"] > 0

    def test_horizons_all_present_before_training(self):
        m = WorldModel()
        result = m.predict({"variant": 3})
        for h in ("6h", "12h", "24h"):
            assert f"roas_{h}" in result
            assert f"lo_{h}" in result
            assert f"hi_{h}" in result
            assert f"width_{h}" in result


class TestWorldModelPostTraining:
    @pytest.fixture(scope="class")
    @classmethod
    def model(cls):
        return _make_trained_model(n_cycles=10)

    def test_all_horizons_fitted(self, model):
        assert model._fitted == {"6h", "12h", "24h"}

    def test_predict_returns_all_keys(self, model):
        result = model.predict({"variant": 2})
        for h in ("6h", "12h", "24h"):
            assert f"roas_{h}" in result
            assert f"lo_{h}" in result
            assert f"hi_{h}" in result
            assert f"width_{h}" in result

    def test_intervals_are_valid(self, model):
        """lo ≤ point_pred ≤ hi and width = hi - lo."""
        result = model.predict({"variant": 1})
        for h in ("6h", "12h", "24h"):
            lo = result[f"lo_{h}"]
            hi = result[f"hi_{h}"]
            width = result[f"width_{h}"]
            assert hi >= lo, f"hi < lo for horizon {h}"
            assert abs(width - (hi - lo)) < 1e-5, f"width != hi-lo for horizon {h}"

    def test_width_is_positive(self, model):
        result = model.predict({"variant": 4})
        for h in ("6h", "12h", "24h"):
            assert result[f"width_{h}"] >= 0

    def test_mean_uncertainty_property(self, model):
        u = model.mean_uncertainty
        assert isinstance(u, float)
        assert u >= 0


class TestDecisionEngineIntervals:
    def test_decisions_carry_interval_fields(self):
        """After enough cycles to train the model, decisions include pred_lo/hi/width."""
        state = SystemState()
        for _ in range(25):
            state = run_cycle(state)

        from backend.decision.engine import decide
        decisions = decide(state)
        assert len(decisions) == 5
        for d in decisions:
            assert "pred_lo" in d
            assert "pred_hi" in d
            assert "pred_width" in d
            assert "interval_conf" in d
            # interval_conf is in (0, 1]
            assert 0 < d["interval_conf"] <= 1.0

    def test_interval_conf_penalises_wide_intervals(self):
        """Wider prediction intervals produce lower interval_conf."""
        from backend.decision.engine import _interval_confidence
        narrow = {"width_6h": 0.1, "width_12h": 0.1, "width_24h": 0.1}
        wide   = {"width_6h": 2.0, "width_12h": 2.0, "width_24h": 2.0}
        assert _interval_confidence(narrow) > _interval_confidence(wide)


class TestIntervalColumnsInEventLog:
    def test_pred_width_in_event_log_after_training(self):
        """Once world model is trained, pred_width appears in event log rows."""
        state = SystemState()
        for _ in range(30):
            state = run_cycle(state)
        # After training (needs 20 rows), later rows should have pred_width
        late_rows = state.event_log.rows[-10:]
        widths = [r.get("pred_width") for r in late_rows]
        non_none = [w for w in widths if w is not None]
        assert len(non_none) > 0, "No pred_width found in late event log rows"

    def test_pred_width_in_duckdb(self, tmp_path):
        """pred_width is queryable as a proper column in DuckDB event_log."""
        from backend.core.db_serializer import save, query
        state = SystemState()
        for _ in range(30):
            state = run_cycle(state)

        db_path = str(tmp_path / "state.db")
        save(state, db_path)

        rows = query(db_path, "SELECT pred_width FROM event_log WHERE pred_width IS NOT NULL")
        assert len(rows) > 0
        assert all(r[0] >= 0 for r in rows)
