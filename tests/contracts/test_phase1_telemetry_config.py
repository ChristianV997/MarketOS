from backend.observability.phase1_telemetry import telemetry_config_from_env, telemetry_readiness


def test_telemetry_is_disabled_and_fail_open_without_credentials():
    config = telemetry_config_from_env({})
    report = telemetry_readiness({})
    assert config.sentry_enabled is False
    assert config.safe_mode is True
    assert report["telemetry_fail_open"] is True
    assert report["sentry_pii_disabled"] is True
    assert report["posthog_server_enabled"] is False


def test_configured_sentry_uses_bounded_sample_rate_without_returning_dsn():
    report = telemetry_readiness({"SENTRY_DSN": "https://secret.example/1", "SENTRY_ENVIRONMENT": "staging", "SENTRY_RELEASE": "build-1", "SENTRY_TRACES_SAMPLE_RATE": "0.05", "VITE_POSTHOG_KEY": "phc_public"})
    assert report["sentry_enabled"] is True
    assert report["sentry_environment"] == "staging"
    assert report["sentry_traces_sample_rate"] == 0.05
    assert "secret.example" not in str(report)
