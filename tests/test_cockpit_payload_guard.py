from backend.execution_cockpit.payload_guard import validate_cockpit_payload_safe


def test_guard_rejects_unsafe_nested_payload_and_preserves_input():
    payload = {"workspace_id": "default", "payload": {"live": True}}
    result = validate_cockpit_payload_safe("run_workflow", payload)
    assert not result["safe"]
    assert payload["payload"]["live"] is True
    assert any("unsafe_flag" in item for item in result["blocked_reasons"])
    assert not validate_cockpit_payload_safe("unknown", {})["safe"]
    assert validate_cockpit_payload_safe("generate_optimization", {"workspace_id": "default"})["safe"]
