from __future__ import annotations

from api.routes.phase1_readiness import readiness


def test_phase1_readiness_route_is_get_only_and_safe(monkeypatch):
    monkeypatch.setenv("CJ_EMAIL", "operator@example.invalid"); monkeypatch.setenv("CJ_API_KEY", "very-secret-cj-key")
    report = readiness()
    assert report["read_only"] is True
    assert report["mutated"] is False
    assert report["network_calls"] is False
    # Variable names can be operator guidance; credential values never appear.
    assert "very-secret" not in str(report) and "operator@example.invalid" not in str(report)


def test_phase1_readiness_rejects_paths_outside_artifacts(monkeypatch, tmp_path):
    monkeypatch.setenv("MARKETOS_PHASE1_EVALUATION_REPORT", str(tmp_path / "outside.json"))
    report = readiness()
    assert "evaluation_report" not in report["source_artifacts"]


def test_phase1_readiness_route_is_registered_on_backend_app():
    from backend.api import app
    paths = set()
    for included in app.routes:
        router = getattr(included, "original_router", None)
        if router is not None:
            paths.update(route.path for route in router.routes if hasattr(route, "path"))
        elif hasattr(included, "path"):
            paths.add(included.path)
    assert "/api/phase1/readiness" in paths
