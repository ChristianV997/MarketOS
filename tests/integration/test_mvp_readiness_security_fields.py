from scripts.mvp_readiness import build_mvp_readiness


def test_mvp_readiness_exposes_hardening_without_secrets(monkeypatch):
    values = {
        "ALLOWED_ORIGINS": "https://mvp.example.test",
        "MARKETOS_MVP_MODE": "1",
        "MARKETOS_PUBLIC_COMMERCE_RUNS": "0",
    }
    report = build_mvp_readiness(values)
    security = report["security"]
    assert security["cors_mvp_safe"] is True
    assert security["request_id_middleware_enabled"] is True
    assert security["rate_limit_enabled"] is True
    assert "SERVICE_ROLE_KEY" not in str(report)
