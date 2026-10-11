"""Comprehensive tests for workflow failure classification and safe operator recovery."""
from __future__ import annotations

import pytest

from backend.workflows.failure_classifier import (
    classify_workflow_failure,
    sanitize_failure_text,
)
from backend.workflows.workflow_models import WorkflowRun, WorkflowStage
from backend.workflows.workflow_summary import build_workflow_summary


def test_failure_classifier_is_structured_and_conservative():
    """Preserve existing test contract."""
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


def test_sanitize_failure_text_direct():
    """Verify sanitize_failure_text directly scrubs secrets, paths, and tracebacks."""
    assert sanitize_failure_text("normal error") == "normal error"
    assert sanitize_failure_text("path C:\\data\\file.txt") == "path <redacted-path>"
    assert sanitize_failure_text("token sk-live-1234567890123456") == "<redacted-secret>"
    assert sanitize_failure_text("canary zz-secret-123") == "canary <redacted-canary>"
    assert sanitize_failure_text(123) == ""  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("raw_text", "expected_category", "expected_severity", "expected_retryable", "expected_recoverable"),
    [
        ("unsafe path traversal rejected: ../outside.csv", "unsafe_path", "critical", False, False),
        ("unconfined path outside allowed directory", "unsafe_path", "critical", False, False),
        ("blocked by safety guard: live provider requested", "blocked_by_safety", "critical", False, False),
        ("live execution and external mutation disallowed in offline mode", "blocked_by_safety", "critical", False, False),
        ("unsupported parser: unknown_custom_csv", "unsupported_parser", "error", False, True),
        ("no evidence available in directory", "no_evidence", "warning", True, True),
        ("service module unavailable: validation runner", "unavailable_service", "error", False, True),
        ("obsidian not configured for note sync", "obsidian_unconfigured", "warning", False, True),
        ("registry unavailable: could not connect to workflow registry", "registry_unavailable", "error", False, True),
        ("artifact render failed: template syntax error", "artifact_render_failed", "error", False, True),
        ("validation failed: opportunity gate check rejected", "validation_failed", "error", False, True),
        ("unknown unexpected crash in calculation", "unexpected_exception", "error", False, False),
    ],
)
def test_all_canonical_failure_categories(
    raw_text: str,
    expected_category: str,
    expected_severity: str,
    expected_retryable: bool,
    expected_recoverable: bool,
):
    info = classify_workflow_failure("test_stage", raw_text)
    assert info["category"] == expected_category
    assert info["severity"] == expected_severity
    assert info["retryable"] is expected_retryable
    assert info["recoverable"] is expected_recoverable
    assert isinstance(info["next_actions"], list)
    assert len(info["next_actions"]) > 0
    assert info["operator_action_required"] is True or expected_category == "obsidian_unconfigured"


def test_false_positive_substring_disambiguation():
    """Verify that common substrings (live, mutation, escape) do not trigger false-positive safety blocks."""
    # 'live' substring inside ordinary English words
    delivery = classify_workflow_failure("delivery_stage", "Delivery estimation failed: connection timeout")
    assert delivery["category"] != "blocked_by_safety"
    assert delivery["severity"] != "critical"

    deliverable = classify_workflow_failure("deliverable_package", "Deliverable package formatting failed")
    assert deliverable["category"] != "blocked_by_safety"

    olive = classify_workflow_failure("market_discovery", "Category olive oil processing error")
    assert olive["category"] != "blocked_by_safety"

    lively = classify_workflow_failure("creative_intelligence", "Lively tone setting failed")
    assert lively["category"] != "blocked_by_safety"

    # 'mutation' substring inside ordinary words
    immutable = classify_workflow_failure("plan", "Immutable configuration object cannot be updated")
    assert immutable["category"] != "blocked_by_safety"

    permutation = classify_workflow_failure("optimization", "Permutation calculation timeout")
    assert permutation["category"] != "blocked_by_safety"

    # 'escape' substring inside JSON / regex errors without an unsafe path
    unescaped = classify_workflow_failure("stage", "Invalid unescaped character in JSON string")
    assert unescaped["category"] != "unsafe_path"


def test_path_and_traceback_scrubbing():
    """Verify that filesystem paths and tracebacks are never reflected in messages or metadata."""
    win_path = "C:\\Users\\SecretOperator\\MarketOS\\data\\private_tokens.csv"
    posix_path = "/var/secrets/companyos/keys/id_ed25519"
    traversal_path = "../../../../etc/shadow"

    err = FileNotFoundError(f"Failed to open {win_path} or {posix_path} or {traversal_path}")
    info = classify_workflow_failure("import_stage", err)

    assert win_path not in info["message"]
    assert posix_path not in info["message"]
    assert traversal_path not in info["message"]
    assert "<redacted-path>" in info["message"]

    traceback_err = (
        "Traceback (most recent call last):\n"
        '  File "C:\\repo\\backend\\runner.py", line 42, in execute\n'
        "    raise RuntimeError('boom')\n"
        "RuntimeError: boom"
    )
    info_tb = classify_workflow_failure("stage", traceback_err)
    assert "Traceback" not in info_tb["message"]
    assert "File \"" not in info_tb["message"]


def test_secret_and_canary_scrubbing():
    """Verify that API keys, tokens, PII, and canaries are scrubbed from messages and metadata."""
    canary = "zz-canary-secret-token-1844"
    synthetic_key = "-".join(["sk", "live", "abcdef1234567890abcdef"])
    gh_token = "_".join(["ghp", "abcdefghijklmnopqrstuvwxyz123456"])
    email = "secret_operator@marketos.corp"

    exc = Exception(f"Failed authenticating {synthetic_key} for {email} with {gh_token} and {canary}")
    info = classify_workflow_failure("auth_stage", exc)

    assert canary not in info["message"]
    assert synthetic_key not in info["message"]
    assert gh_token not in info["message"]
    assert email not in info["message"]


def test_malicious_and_unbounded_context_is_safely_bounded():
    """Arbitrary, malicious, or sensitive context passed by caller must not be reflected in metadata."""
    key_name = "_".join(["api", "key"])
    pass_name = "_".join(["secret", "password"])
    token_name = "_".join(["private", "token"])
    malicious_context = {
        key_name: "-".join(["sk", "live", "secret", "value"]),
        token_name: "-".join(["token", "12345"]),
        pass_name: "superpassword",
        "canary": "zz-canary-999",
        "arbitrary_payload": {"nested": "data"},
        "path": "C:\\Windows\\System32\\cmd.exe",
        "workspace_id": "ws_valid_123",
        "checkpoint_id": "cp_valid_456",
        "step_order": 5,
    }

    info = classify_workflow_failure("stage", "error message", context=malicious_context)
    meta = info["metadata"]

    assert "api_key" not in meta
    assert "private_token" not in meta
    assert "secret_password" not in meta
    assert "canary" not in meta
    assert "arbitrary_payload" not in meta
    assert "path" not in meta

    assert meta["workspace_id"] == "ws_valid_123"
    assert meta["checkpoint_id"] == "cp_valid_456"
    assert meta["step_order"] == 5
    assert meta["stage_name"] == "stage"
    assert meta["error_type"] == "str"


def test_safety_invariants_strictly_non_retryable_and_non_recoverable():
    """Safety blocks must always remain non-retryable and non-recoverable with critical severity."""
    for text in (
        "unsafe path rejected: /etc/passwd",
        "blocked by safety: live external actions are disabled",
        "live provider access blocked",
    ):
        info = classify_workflow_failure("import_stage", text, context={"retryable": True, "recoverable": True})
        assert info["retryable"] is False
        assert info["recoverable"] is False
        assert info["severity"] == "critical"
        assert info["operator_action_required"] is True
        for action in info["next_actions"]:
            assert any(k in action.lower() for k in ("offline", "allowed directories", "disabled", "inspect", "unconfined", "traversal"))


def test_custom_exception_handling():
    """Custom exception classes are classified safely and their class name is recorded in metadata."""
    class CustomStorageError(Exception):
        pass

    exc = CustomStorageError("Registry storage corrupted")
    info = classify_workflow_failure("storage_stage", exc)
    assert info["metadata"]["error_type"] == "CustomStorageError"
    assert info["category"] == "registry_unavailable"


def test_downstream_summary_projection_incorporates_recovery_guidance():
    """Stage-level failure recovery actions must be cleanly projected into the workflow summary."""
    canary_path = "C:\\private\\canary\\dataset.csv"
    err = FileNotFoundError(f"Unsafe path {canary_path} rejected")
    info = classify_workflow_failure("import_evidence", err)

    stage = WorkflowStage("stage_1", "import_evidence", 1, status="failed")
    stage.errors.append(info["message"])
    stage.metadata["failure_classification"] = info

    run = WorkflowRun(
        "run_1",
        "default",
        "import_discovery_cycle",
        "Import Discovery Test",
        "Test summary projection",
        stages=[stage],
    )
    run.errors = list(stage.errors)

    summary = build_workflow_summary(run)
    assert "import_evidence" in summary["failed_stages"]
    # Verify failure classification next actions are surfaced into summary next actions
    assert any("allowed directories" in a.lower() for a in summary["next_actions"])
    # Verify no leaked raw path in operator actions required
    assert canary_path not in str(summary["operator_actions_required"])
