from scripts.mvp_readiness import build_mvp_readiness


def test_mvp_readiness_reports_optional_observability_without_blocking():
    report = build_mvp_readiness({"ALLOWED_ORIGINS": "https://mvp.example.test", "MARKETOS_MVP_MODE": "1", "MARKETOS_PUBLIC_COMMERCE_RUNS": "0"})
    observability = report["security"]
    assert observability["sentry_enabled"] is False
    assert observability["posthog_frontend_configured"] is False
    assert observability["telemetry_fail_open"] is True
    assert "SENTRY_DSN" not in str(report)
