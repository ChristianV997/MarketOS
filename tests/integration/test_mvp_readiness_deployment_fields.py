from backend.runtime.deployment_status import mvp_deployment_status


def test_health_deployment_status_contains_safe_mvp_fields(monkeypatch):
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
    monkeypatch.setenv("MARKETOS_PUBLIC_COMMERCE_RUNS", "0")
    status = mvp_deployment_status()
    assert status["mvp_profile_loaded"] is True
    assert status["public_commerce_runs_enabled"] is False
    assert status["no_credentials_required_for_mvp_smoke"] is True
    assert status["operator_dashboard_expected_route"] == "/operator/events"
    assert "SUPABASE_SERVICE_ROLE_KEY" not in str(status)
