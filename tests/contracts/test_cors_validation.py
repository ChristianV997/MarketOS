from backend.security.cors import explain_cors_readiness, parse_allowed_origins, validate_allowed_origins


def test_origins_are_normalized_and_localhost_is_allowed():
    assert parse_allowed_origins(" https://mvp.example.test/,http://localhost:5173,https://mvp.example.test ") == ["https://mvp.example.test", "http://localhost:5173"]
    report = validate_allowed_origins(["https://mvp.example.test", "http://localhost:5173"], mvp_mode=True)
    assert report["mvp_safe"] is True
    assert report["credentials_enabled"] is False


def test_wildcard_is_blocked_when_mvp_or_public_run_is_enabled():
    report = explain_cors_readiness({"ALLOWED_ORIGINS": "*", "MARKETOS_MVP_MODE": "1"})
    assert report["mvp_safe"] is False
    assert "wildcard_origin_not_allowed_in_mvp_mode" in report["blockers"]


def test_empty_origins_are_a_warning_without_live_gate():
    report = explain_cors_readiness({})
    assert report["configured"] is False
    assert report["mvp_safe"] is True
    assert "allowed_origins_unconfigured" in report["warnings"]
