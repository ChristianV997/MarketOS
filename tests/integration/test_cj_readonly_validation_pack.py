from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import run_phase1_cj_readonly_validation_pack as pack


def _clear_cj_env(monkeypatch) -> None:
    for key in ("CJ_EMAIL", "CJ_API_KEY", "MARKETOS_SUPPLIER_AUTH_READONLY", "MARKETOS_SUPPLIER_PROVIDER"):
        monkeypatch.delenv(key, raising=False)


def _observed_validation(secret: str = "") -> dict:
    return {
        "supplier_evidence": {
            "status": "observed", "provider_status": "observed", "source": "authenticated_readonly",
            "warnings": [f"safe warning {secret}"],
            "result": {
                "source_type": "authenticated_readonly_api", "confidence": 0.8,
                "source_url": "https://catalog.example.invalid/product/1?access_token=not-for-output",
                "field_status": {
                    "title": "observed", "price": "observed", "sku": "observed",
                    "inventory_quantity": "observed", "variants": "observed", "shipping_cost": "unavailable",
                },
            },
        },
        "competition_evidence": {"offers": [], "warnings": []},
        "commerce_mvp_run": {"run_id": "fixture-run", "status": "completed"},
        "input_urls": {"supplier_url": "https://catalog.example.invalid/p?api_key=not-for-output"},
    }


def _fake_harness(secret: str = ""):
    def invoke(argv: list[str]) -> int:
        out_dir = Path(argv[argv.index("--out-dir") + 1])
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "validation_report.json").write_text(json.dumps(_observed_validation(secret)), encoding="utf-8")
        (out_dir / "events.jsonl").write_text("", encoding="utf-8")
        return 0
    return invoke


def test_default_mode_never_calls_harness(monkeypatch, tmp_path, capsys):
    _clear_cj_env(monkeypatch)
    monkeypatch.setattr(pack.live_validation, "main", lambda _argv: (_ for _ in ()).throw(AssertionError("network harness")))
    assert pack.main(["--out-dir", str(tmp_path), "--timestamp", "fixed"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["preflight_status"] == "credential_missing"
    assert report["live_probe_attempted"] is False
    assert report["recommended_next_action"] == "set_credentials"
    assert (tmp_path / "preflight_report.json").is_file()
    assert (tmp_path / "validation_pack_report.json").is_file()


def test_ready_config_without_network_is_blocked_without_harness(monkeypatch, tmp_path, capsys):
    _clear_cj_env(monkeypatch)
    monkeypatch.setenv("CJ_EMAIL", "fixture@example.invalid")
    monkeypatch.setenv("CJ_API_KEY", "fixture-key")
    monkeypatch.setenv("MARKETOS_SUPPLIER_AUTH_READONLY", "1")
    monkeypatch.setattr(pack.live_validation, "main", lambda _argv: (_ for _ in ()).throw(AssertionError("network harness")))
    assert pack.main(["--out-dir", str(tmp_path), "--timestamp", "fixed"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["preflight_status"] == "network_gate_required"
    assert report["live_probe_status"] == "network_gate_required"
    assert report["recommended_next_action"] == "rerun_with_allow_network"


def test_disabled_readonly_flag_is_reported(monkeypatch, tmp_path, capsys):
    _clear_cj_env(monkeypatch)
    monkeypatch.setenv("CJ_EMAIL", "fixture@example.invalid")
    monkeypatch.setenv("CJ_API_KEY", "fixture-key")
    monkeypatch.setenv("MARKETOS_SUPPLIER_AUTH_READONLY", "0")
    assert pack.main(["--allow-network", "--out-dir", str(tmp_path)]) == 0
    assert json.loads(capsys.readouterr().out)["recommended_next_action"] == "enable_readonly_flag"


def test_live_mode_delegates_once_with_one_candidate_and_writes_safe_reports(monkeypatch, tmp_path, capsys):
    _clear_cj_env(monkeypatch)
    secret = "live-secret-do-not-leak"
    monkeypatch.setenv("CJ_EMAIL", "operator@example.invalid")
    monkeypatch.setenv("CJ_API_KEY", secret)
    monkeypatch.setenv("MARKETOS_SUPPLIER_AUTH_READONLY", "1")
    calls: list[list[str]] = []
    fake = _fake_harness(secret)
    monkeypatch.setattr(pack.live_validation, "main", lambda argv: calls.append(argv) or fake(argv))
    assert pack.main(["--allow-network", "--markdown", "--out-dir", str(tmp_path), "--timestamp", "fixed"]) == 0
    output = capsys.readouterr().out
    report = json.loads((tmp_path / "validation_pack_report.json").read_text(encoding="utf-8"))
    assert len(calls) == 1
    assert calls[0][calls[0].index("--max-authenticated-supplier-candidates") + 1] == "1"
    assert report["live_probe_attempted"] is True
    assert report["live_probe_status"] == "observed"
    assert report["supplier_price_observed"] is True
    assert report["supplier_shipping_observed"] is False
    assert report["canonical_event_count"] == 0
    assert (tmp_path / "validation_pack_report.md").is_file()
    for path in tmp_path.glob("*"):
        assert secret not in path.read_text(encoding="utf-8")
    assert "access_token=" not in (tmp_path / "validation_report.json").read_text(encoding="utf-8")
    assert "Phase 1 CJ Read-Only Validation Pack" in output


def test_optional_competitors_are_only_passed_when_operator_supplies_them(monkeypatch, tmp_path):
    _clear_cj_env(monkeypatch)
    monkeypatch.setenv("CJ_EMAIL", "fixture@example.invalid")
    monkeypatch.setenv("CJ_API_KEY", "fixture-key")
    monkeypatch.setenv("MARKETOS_SUPPLIER_AUTH_READONLY", "1")
    calls: list[list[str]] = []
    fake = _fake_harness()
    monkeypatch.setattr(pack.live_validation, "main", lambda argv: calls.append(argv) or fake(argv))
    args = pack._parser().parse_args(["--allow-network", "--competitor-urls", "https://example.invalid/p", "--out-dir", str(tmp_path)])
    pack.run_validation_pack(args)
    assert "--competitor-urls" in calls[0]
    assert calls[0][calls[0].index("--competitor-urls") + 1] == "https://example.invalid/p"


def test_comparison_against_prior_artifact_is_optional_and_deterministic(monkeypatch, tmp_path):
    _clear_cj_env(monkeypatch)
    monkeypatch.setenv("CJ_EMAIL", "fixture@example.invalid")
    monkeypatch.setenv("CJ_API_KEY", "fixture-key")
    monkeypatch.setenv("MARKETOS_SUPPLIER_AUTH_READONLY", "1")
    baseline = tmp_path / "baseline"; baseline.mkdir()
    baseline_value = _observed_validation(); baseline_value["supplier_evidence"]["result"]["field_status"]["price"] = "unavailable"
    (baseline / "validation_report.json").write_text(json.dumps(baseline_value), encoding="utf-8")
    monkeypatch.setattr(pack.live_validation, "main", _fake_harness())
    run = tmp_path / "current"
    report = pack.run_validation_pack(pack._parser().parse_args([
        "--allow-network", "--out-dir", str(run), "--compare-against", str(baseline), "--timestamp", "fixed",
    ]))
    assert report["comparison"] is not None
    assert report["comparison"]["supplier_price_observed"] == 1.0


def test_missing_comparison_artifact_degrades_without_blocking_live_result(monkeypatch, tmp_path):
    _clear_cj_env(monkeypatch)
    monkeypatch.setenv("CJ_EMAIL", "fixture@example.invalid")
    monkeypatch.setenv("CJ_API_KEY", "fixture-key")
    monkeypatch.setenv("MARKETOS_SUPPLIER_AUTH_READONLY", "1")
    monkeypatch.setattr(pack.live_validation, "main", _fake_harness())
    report = pack.run_validation_pack(pack._parser().parse_args([
        "--allow-network", "--out-dir", str(tmp_path), "--compare-against", str(tmp_path / "missing"),
    ]))
    assert report["live_probe_status"] == "observed"
    assert report["comparison"] is not None


@pytest.mark.parametrize(
    ("preflight", "probe", "expected"),
    [
        ("credential_missing", "credential_missing", "set_credentials"),
        ("live_flag_disabled", "live_flag_disabled", "enable_readonly_flag"),
        ("network_gate_required", "network_gate_required", "rerun_with_allow_network"),
        ("provider_failed", "provider_failed", "check_cj_account_permissions"),
        ("ready", "provider_failed", "fix_auth"),
        ("ready", "no_results", "check_cj_account_permissions"),
        ("ready", "observed", "harden_payload_mapping"),
    ],
)
def test_recommended_action_is_deterministic(preflight, probe, expected):
    supplier = {"price_observed": False}
    assert pack._recommended_action(preflight_status=preflight, probe_status=probe, supplier=supplier, evaluation=None) == expected


def test_observed_price_with_medium_quality_is_ready_for_live_results():
    assert pack._recommended_action(
        preflight_status="ready", probe_status="observed", supplier={"price_observed": True},
        evaluation={"overall": {"run_quality": "medium"}},
    ) == "ready_for_phase1_live_results"


def test_sanitizer_preserves_run_ids_but_removes_known_secret_and_url_query():
    secret = "explicit-secret-value"
    sanitized = pack.sanitize_value(
        {"run_id": "cj-readonly-validation-fixed-run-id", "source_url": "https://example.invalid/a?token=abc", "api_key": secret, "note": secret},
        secret_values=(secret,),
    )
    assert sanitized["run_id"] == "cj-readonly-validation-fixed-run-id"
    assert sanitized["source_url"] == "https://example.invalid/a"
    assert sanitized["api_key"] == "[redacted]"
    assert secret not in json.dumps(sanitized)


def test_validation_harness_rejects_out_of_range_authenticated_candidate_bound():
    with pytest.raises(SystemExit):
        pack.live_validation.main(["--max-authenticated-supplier-candidates", "0"])
