from backend.observability.telemetry_sanitization import safe_path_tag, safe_workspace_tag, sanitize_sentry_event, sanitize_telemetry_mapping, telemetry_contains_forbidden_data


def test_sentry_sanitization_removes_body_identity_and_secret_headers():
    event = {
        "request": {"method": "POST", "url": "/api/commerce-mvp/public-run", "data": {"email": "person@example.test"}, "headers": {"authorization": "Bearer " + "a" * 32, "cookie": "session-secret"}},
        "user": {"email": "person@example.test", "phone": "+5215555555555"},
        "tags": {"workspace_id": "demo", "shopify_token": "secret"},
    }
    sanitized = sanitize_sentry_event(event)
    assert "user" not in sanitized
    assert "data" not in sanitized["request"]
    assert "headers" not in sanitized["request"]
    assert "person@example.test" not in str(sanitized)
    assert telemetry_contains_forbidden_data(sanitized) is False


def test_mapping_redacts_pii_and_path_workspace_tags_are_bounded():
    result = sanitize_telemetry_mapping({"customer_email": "person@example.test", "safe": "value"})
    assert result["customer_email"] == "<redacted>"
    assert safe_workspace_tag("demo-workspace") == "demo-workspace"
    assert safe_workspace_tag("name with spaces") == "workspace_redacted"
    assert safe_path_tag("/api/events/timeline?workspace_id=secret") == "/api/events/*"
