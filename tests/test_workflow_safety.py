from backend.workflows.workflow_safety import validate_workflow_payload_safe


def test_workflow_safety_rejects_nested_live_mutation_and_url_flags_without_mutating_input():
    payload = {"inputs": {"live": True, "nested": [{"place_order": True}]}, "url": "https://example.com"}
    original = {"inputs": {"live": True, "nested": [{"place_order": True}]}, "url": "https://example.com"}
    result = validate_workflow_payload_safe(payload)
    assert result["safe"] is False
    assert result["blocked_reasons"]
    assert payload == original


def test_workflow_safety_accepts_bounded_local_import_payload():
    result = validate_workflow_payload_safe({"import_paths": ["tests/fixtures/evidence_imports/google_trends_sample.csv"], "dry_run": True})
    assert result["safe"] is True
