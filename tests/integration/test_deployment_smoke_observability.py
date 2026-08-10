from scripts.deployment_smoke_check import build_report


def test_deployment_smoke_reports_optional_telemetry_without_secret_values():
    values = {"ALLOWED_ORIGINS": "https://mvp.example.test", "MARKETOS_MVP_MODE": "1", "MARKETOS_EVENT_READ_JSONL_PATH": "artifacts/read.jsonl", "MARKETOS_EVENT_WRITE_JSONL_PATH": "artifacts/write.jsonl", "MARKETOS_PUBLIC_SIGNAL_CACHE_DIR": "artifacts/cache", "MARKETOS_PUBLIC_COMMERCE_RUNS": "0", "MARKETOS_SUPABASE_CANONICAL_EVENTS": "0", "VITE_API_BASE_URL": "https://api.example.test", "SENTRY_DSN": "https://secret.example/1"}
    report = build_report(environ=values)
    assert report["telemetry"]["sentry_enabled"] is True
    assert "secret.example" not in str(report)
    assert report["mutated"] is False
