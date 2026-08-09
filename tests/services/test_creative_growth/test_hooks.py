"""Tests for services.creative_growth.hooks."""
from services.creative_growth.hooks import generate_ad_angles, generate_hook_matrix


class TestGenerateAdAngles:
    def test_falls_back_to_generic_angles_when_no_live_pool_or_signals(self, monkeypatch):
        monkeypatch.setattr("core.creative.selection.select_angles", lambda n, fallback: [])
        angles = generate_ad_angles("Widget", signals=None, n=3)
        assert len(angles) == 3
        assert all(isinstance(a, str) for a in angles)

    def test_extracts_fresh_angles_from_real_signals(self, monkeypatch):
        monkeypatch.setattr("core.creative.selection.select_angles", lambda n, fallback: [])
        signals = [{"text": "this is such a satisfying oddly clean video"}]
        angles = generate_ad_angles("Widget", signals=signals, n=5)
        assert "satisfaction" in angles

    def test_combines_live_pool_and_signal_angles_without_duplicates(self, monkeypatch):
        monkeypatch.setattr("core.creative.selection.select_angles", lambda n, fallback: ["curiosity"])
        signals = [{"text": "curiosity strange weird"}]  # would also extract "curiosity"
        angles = generate_ad_angles("Widget", signals=signals, n=5)
        assert angles.count("curiosity") == 1

    def test_never_raises_when_select_angles_fails(self, monkeypatch):
        def _boom(n, fallback):
            raise RuntimeError("boom")
        monkeypatch.setattr("core.creative.selection.select_angles", _boom)
        angles = generate_ad_angles("Widget")
        assert angles  # falls back to defaults


class TestGenerateHookMatrix:
    def test_falls_back_to_generic_hooks_when_no_live_pool(self, monkeypatch):
        monkeypatch.setattr("core.creative.selection.select_hooks", lambda n, fallback: [])
        matrix = generate_hook_matrix("Widget", ["curiosity", "convenience"], n_hooks=2)
        assert len(matrix) == 2 * 2
        assert all({"hook", "angle", "product"} <= row.keys() for row in matrix)

    def test_uses_live_hook_pool_when_available(self, monkeypatch):
        monkeypatch.setattr("core.creative.selection.select_hooks", lambda n, fallback: ["Real hook A", "Real hook B"])
        matrix = generate_hook_matrix("Widget", ["curiosity"], n_hooks=2)
        assert {row["hook"] for row in matrix} == {"Real hook A", "Real hook B"}

    def test_empty_angles_produces_empty_matrix(self, monkeypatch):
        monkeypatch.setattr("core.creative.selection.select_hooks", lambda n, fallback: ["Hook"])
        matrix = generate_hook_matrix("Widget", [])
        assert matrix == []

    def test_never_raises_when_select_hooks_fails(self, monkeypatch):
        def _boom(n, fallback):
            raise RuntimeError("boom")
        monkeypatch.setattr("core.creative.selection.select_hooks", _boom)
        matrix = generate_hook_matrix("Widget", ["curiosity"])
        assert matrix  # falls back to default hooks x given angles
