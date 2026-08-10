from scripts.telemetry_readiness import build_report, markdown_report


def test_telemetry_readiness_is_deterministic_and_redacted():
    report = build_report({"SENTRY_DSN": "https://secret.example/1", "VITE_POSTHOG_KEY": "phc_public"}, test_sanitization=True)
    assert report["sentry_enabled"] is True
    assert report["posthog_frontend_configured"] is True
    assert report["sanitization_test"]["forbidden_data_remaining"] is False
    assert "secret.example" not in markdown_report(report)
