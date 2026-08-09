from backend.workflows.failure_classifier import classify_workflow_failure


def test_failure_classifier_is_structured_and_conservative():
    no_evidence = classify_workflow_failure("market_discovery", "no evidence available")
    assert no_evidence["category"] == "no_evidence"
    assert no_evidence["retryable"] is True
    safety = classify_workflow_failure("import_evidence", "unsafe path rejected")
    assert safety["category"] == "unsafe_path"
    assert safety["operator_action_required"] is True
    unavailable = classify_workflow_failure("validation_sprint", "service_module_unavailable")
    assert unavailable["category"] == "unavailable_service"
    obsidian = classify_workflow_failure("notes", "obsidian not configured")
    assert obsidian["category"] == "obsidian_unconfigured"
    assert obsidian["severity"] == "warning"
