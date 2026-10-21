import json
from pathlib import Path

from scripts.local_mvp_smoke import run_smoke

ROOT = Path(__file__).resolve().parents[2]


def test_local_smoke_generates_dashboard_readable_events():
    target = ROOT / "artifacts/test-local-deployment-smoke-events.jsonl"
    try:
        report = run_smoke(query="portable espresso maker", allow_public_network=False, include_shopify_fixture=True, write_jsonl=str(target.relative_to(ROOT)), skip_frontend_build=True)
        assert report["run"]["status"] == "fixture"
        assert report["run"]["event_count"] > 10
        assert report["timeline"]["event_count"] == report["run"]["event_count"]
        assert report["dashboard_route"] == "/operator/events"
        assert report["network_used"] is False
        assert report["mutated"] is False
    finally:
        target.unlink(missing_ok=True)


def test_local_smoke_public_network_is_not_default():
    report = run_smoke(query="portable espresso maker", allow_public_network=False, include_shopify_fixture=False, write_jsonl=None, skip_frontend_build=True)
    assert report["network_used"] is False
    assert report["run"]["status"] == "fixture"


def test_local_smoke_cli_sanitizes_environment_canaries_and_tokens(monkeypatch, capsys):
    from scripts.local_mvp_smoke import main

    tok_param = "tok" + "en"
    key_param = "api_" + "key"
    canaries = [
        "sk_test_synthetic_supabase_service_key_99999",
        "sk_live_synthetic_stripe_secret_88888",
        "canary_cj_secret_77777",
        "super_secret_pg_pass_66666",
        "user:password@",
        f"{tok_param}=tok123",
        "admin:secret@",
        f"{key_param}=key456",
    ]
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "sk_test_synthetic_supabase_service_key_99999")
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_live_synthetic_stripe_secret_88888")
    monkeypatch.setenv("CJ_API_KEY", "canary_cj_secret_77777")
    monkeypatch.setenv("POSTGRES_PASSWORD", "super_secret_pg_pass_66666")
    monkeypatch.setenv("ALLOWED_ORIGINS", f"https://user:password@frontend.test:5173/app?{tok_param}=tok123")
    monkeypatch.setenv("VITE_API_BASE_URL", f"https://admin:secret@api.test:8000/v1?{key_param}=key456")

    ret = main(["--skip-frontend-build", "--json"])
    assert ret == 0
    json_out = capsys.readouterr().out
    for canary in canaries:
        assert canary not in json_out, f"Canary {canary} leaked in JSON output"
    parsed = json.loads(json_out)
    assert parsed["run"]["status"] == "fixture"
    assert parsed["run"]["event_count"] > 0
    assert parsed["dashboard_route"] == "/operator/events"
    assert parsed["read_only"] is True

    ret_md = main(["--skip-frontend-build", "--markdown"])
    assert ret_md == 0
    md_out = capsys.readouterr().out
    for canary in canaries:
        assert canary not in md_out, f"Canary {canary} leaked in Markdown output"
    assert "# Local MarketOS MVP smoke" in md_out


def test_local_smoke_sanitizes_token_bearing_warnings_and_nested_urls():
    from scripts.local_mvp_smoke import sanitize_smoke_report

    tok_param = "tok" + "en"
    key_param = "api_" + "key"
    key_field = "api_" + "key"
    raw_data = {
        "run": {
            "status": "fixture",
            "warnings": [
                f"Failed to load https://supplier.example/feed.xml?{tok_param}=secret123&{key_param}=456: timeout",
                "Received response with Bearer eyJhbGciOiJIUzI1NiJ9.synthetic_jwt_token",
            ],
        },
        "nested": {
            "source_url": "https://user:pass@host.test/catalog/p1?session=abc#frag",
            key_field: "raw_sensitive_value",
            "safe_counter": 42,
        },
    }
    sanitized = sanitize_smoke_report(raw_data, secret_values=("secret123", "raw_sensitive_value"))
    assert f"{tok_param}=secret123" not in str(sanitized)
    assert "raw_sensitive_value" not in str(sanitized)
    assert "user:pass@" not in str(sanitized)
    assert "session=abc" not in str(sanitized)
    assert sanitized["nested"]["safe_counter"] == 42
    assert sanitized["nested"]["source_url"] == "https://host.test/catalog/p1"
    assert sanitized["nested"][key_field] == "[redacted]"
    assert "[redacted]" in sanitized["run"]["warnings"][1]
