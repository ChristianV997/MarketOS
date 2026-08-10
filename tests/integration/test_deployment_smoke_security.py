from scripts.deployment_smoke_check import build_report


def test_deployment_smoke_reports_security_invariants():
    values = {
        "ALLOWED_ORIGINS": "https://mvp.example.test",
        "MARKETOS_MVP_MODE": "1",
        "MARKETOS_EVENT_READ_JSONL_PATH": "artifacts/read.jsonl",
        "MARKETOS_EVENT_WRITE_JSONL_PATH": "artifacts/write.jsonl",
        "MARKETOS_PUBLIC_SIGNAL_CACHE_DIR": "artifacts/cache",
        "MARKETOS_PUBLIC_COMMERCE_RUNS": "0",
        "MARKETOS_SUPABASE_CANONICAL_EVENTS": "0",
        "VITE_API_BASE_URL": "https://api.example.test",
    }
    report = build_report(environ=values)
    assert report["security"]["cors_mvp_safe"] is True
    assert report["security"]["request_id_middleware_enabled"] is True
    assert report["security"]["distributed_rate_limiting"] is False
    assert report["mutated"] is False
