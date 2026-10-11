import json
from pathlib import Path

import pytest

from backend.discovery import local_dataset, market_discovery_runner
from backend.discovery.discovery_registry import get_discovery_registry
from backend.discovery.market_discovery_runner import run_market_discovery


def test_market_discovery_fixture_is_category_first_and_read_only():
    path = Path(__file__).parent / "fixtures" / "market_evidence_seed.json"
    result = run_market_discovery(dataset_paths=[str(path)], run_validation_services=False)
    assert result["status"] == "completed"
    assert result["discovery"]["category_opportunities"]
    assert result["hypotheses"]["hypotheses"]
    assert result["discovery"]["metadata"]["real_market_claims"] is False


def test_empty_discovery_fails_closed():
    get_discovery_registry().clear_for_tests()
    result = run_market_discovery(dataset_paths=[], run_validation_services=False)
    assert result["status"] == "blocked"
    assert "no_local_or_persisted_evidence" in result["warnings"]


def test_validation_uses_governed_dry_run_service():
    get_discovery_registry().clear_for_tests()
    path = Path(__file__).parent / "fixtures" / "market_evidence_seed.json"
    result = run_market_discovery(dataset_paths=[str(path)], max_hypotheses=2, run_validation_services=True)
    assert result["status"] == "completed"
    assert result["validation_reports"]
    assert all(item.get("status") == "completed" for item in result["validation_reports"])


@pytest.mark.parametrize(
    "filename",
    [
        "secret-api-key-SYNTHETIC-CANARY.json",
        "AWS_SECRET_ACCESS_KEY-SYNTHETIC-CANARY.json",
    ],
)
def test_dataset_failure_warning_redacts_caller_filename(filename, tmp_path, monkeypatch):
    input_path = tmp_path / filename
    input_path.write_text("not-json", encoding="utf-8")
    monkeypatch.setattr(local_dataset, "_project_root", lambda: tmp_path)
    result = run_market_discovery(
        dataset_paths=[str(input_path)],
        run_validation_services=False,
        refresh_pipeline=False,
    )
    rendered = json.dumps(result, sort_keys=True)
    warning = next((item for item in result["warnings"] if item.startswith("dataset_failed:")), "")
    leaks = {
        "absolute_path": str(input_path) in rendered,
        "basename": input_path.name in rendered,
        "filename_canary": "SYNTHETIC-CANARY" in rendered,
    }

    assert warning == "dataset_failed:redacted:JSONDecodeError"
    assert not any(leaks.values()), "caller-controlled dataset path leaked"


def test_dataset_failure_warning_omits_exception_message_and_preserves_safe_type(
    tmp_path, monkeypatch
):
    input_path = tmp_path / "safe-name.json"
    marker = "SYNTHETIC_EXCEPTION_MESSAGE_CANARY"

    def fail_with_marker(_path):
        raise ValueError(marker)

    monkeypatch.setattr(market_discovery_runner, "load_local_evidence_dataset", fail_with_marker)
    result = run_market_discovery(
        dataset_paths=[str(input_path)],
        run_validation_services=False,
        refresh_pipeline=False,
    )
    rendered = json.dumps(result, sort_keys=True)
    warning = next((item for item in result["warnings"] if item.startswith("dataset_failed:")), "")
    leaks = {
        "absolute_path": str(input_path) in rendered,
        "basename": input_path.name in rendered,
        "exception_message": marker in rendered,
    }

    assert warning == "dataset_failed:redacted:ValueError"
    assert not any(leaks.values()), "exception details leaked"


def test_dataset_failure_warning_uses_generic_suffix_for_custom_exception(
    tmp_path, monkeypatch
):
    input_path = tmp_path / "safe-name.json"
    marker = "SYNTHETIC_CUSTOM_EXCEPTION_CANARY"
    custom_exception = type("SYNTHETIC_EXCEPTION_CLASS_CANARY", (Exception,), {})

    def fail_with_custom_exception(_path):
        raise custom_exception(marker)

    monkeypatch.setattr(
        market_discovery_runner,
        "load_local_evidence_dataset",
        fail_with_custom_exception,
    )
    result = run_market_discovery(
        dataset_paths=[str(input_path)],
        run_validation_services=False,
        refresh_pipeline=False,
    )
    rendered = json.dumps(result, sort_keys=True)
    warning = next((item for item in result["warnings"] if item.startswith("dataset_failed:")), "")
    leaks = {
        "absolute_path": str(input_path) in rendered,
        "basename": input_path.name in rendered,
        "exception_message": marker in rendered,
        "exception_type": "SYNTHETIC_EXCEPTION_CLASS_CANARY" in rendered,
    }

    assert warning == "dataset_failed:redacted:Exception"
    assert not any(leaks.values()), "custom exception details leaked"


@pytest.mark.parametrize(
    ("source_name", "source_names", "expected_warning"),
    [
        (
            "credential-source-SYNTHETIC-CANARY",
            ["expected-source"],
            "source_filtered:source_not_selected",
        ),
        (
            "secret-source-SYNTHETIC-CANARY",
            None,
            "source_blocked:source_not_allowed",
        ),
    ],
)
def test_source_warnings_redact_caller_controlled_source_name(
    source_name, source_names, expected_warning, tmp_path, monkeypatch
):
    input_path = tmp_path / "source-warning.json"
    input_path.write_text(
        json.dumps(
            {
                "dataset_id": "synthetic-warning-test",
                "source_name": source_name,
                "provenance": {"type": "synthetic_fixture"},
                "records": [],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(local_dataset, "_project_root", lambda: tmp_path)
    result = run_market_discovery(
        dataset_paths=[str(input_path)],
        source_names=source_names,
        run_validation_services=False,
        refresh_pipeline=False,
    )
    rendered = json.dumps(result, sort_keys=True)
    leaks = {
        "absolute_path": str(input_path) in rendered,
        "source_name": source_name in rendered,
    }

    assert result["status"] == "blocked"
    assert expected_warning in result["warnings"]
    assert not any(leaks.values()), "caller-controlled source name leaked"


def test_pipeline_failure_warning_omits_exception_details(monkeypatch):
    from backend.discovery import opportunity_pipeline_builder

    marker = "SYNTHETIC_PIPELINE_EXCEPTION_CANARY"
    custom_exception = type("SYNTHETIC_PIPELINE_EXCEPTION_TYPE", (Exception,), {})

    def fail_pipeline(*_args, **_kwargs):
        raise custom_exception(marker)

    get_discovery_registry().clear_for_tests()
    monkeypatch.setattr(
        opportunity_pipeline_builder,
        "refresh_opportunity_pipeline",
        fail_pipeline,
    )
    result = run_market_discovery(dataset_paths=[], run_validation_services=False)
    rendered = json.dumps(result, sort_keys=True)
    warnings = [
        warning
        for warning in result["warnings"]
        if warning.startswith("opportunity_pipeline_refresh_failed:")
    ]
    leaks = {
        "exception_message": marker in rendered,
        "exception_type": "SYNTHETIC_PIPELINE_EXCEPTION_TYPE" in rendered,
    }

    assert warnings == ["opportunity_pipeline_refresh_failed:Exception"]
    assert not any(leaks.values()), "pipeline exception details leaked"


def test_dataset_failure_warning_preserves_stable_family_and_safe_suffix(
    tmp_path, monkeypatch
):
    input_path = tmp_path / "outside-root.json"
    input_path.write_text("{", encoding="utf-8")

    result = run_market_discovery(
        dataset_paths=[str(input_path)],
        run_validation_services=False,
        refresh_pipeline=False,
    )
    rendered = json.dumps(result, sort_keys=True)
    warning = next((item for item in result["warnings"] if item.startswith("dataset_failed:")), "")
    leaks = {
        "absolute_path": str(input_path) in rendered,
        "basename": input_path.name in rendered,
    }

    assert warning == "dataset_failed:redacted:ValueError"
    assert not any(leaks.values()), "outside-root dataset identity leaked"
