from backend.security.safe_logging import contains_forbidden_secret, redact_mapping, safe_log_event


def test_secret_keys_and_long_token_values_are_redacted():
    raw = {"authorization": "Bearer " + "a" * 32, "nested": {"shopify_token": "b" * 32}, "safe": "operator-summary"}
    redacted = redact_mapping(raw)
    assert redacted["authorization"] == "<redacted>"
    assert redacted["nested"]["shopify_token"] == "<redacted>"
    assert "a" * 32 not in str(redacted)
    assert contains_forbidden_secret(raw) is True


def test_request_log_accepts_summary_fields_without_body_data(caplog):
    event = safe_log_event("request_end", request_id="req-1", method="POST", path="/api/commerce-mvp/public-run", status_code=200, duration_ms=2.1, body="do-not-log")
    assert event["body"] == "<redacted>"
    assert "do-not-log" not in caplog.text
