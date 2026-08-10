from backend.observability.telemetry_sanitization import safe_path_tag, safe_workspace_tag


def test_request_context_tags_are_safe_and_non_sensitive():
    assert safe_path_tag("/api/commerce-mvp/public-run?query=private") == "/api/commerce-mvp/public-run"
    assert safe_workspace_tag("demo") == "demo"
    assert safe_workspace_tag("customer@example.test") == "workspace_redacted"
