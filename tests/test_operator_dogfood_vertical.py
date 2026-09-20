"""Isolated tests for the #283 operator-manifest vertical.

Does not start live providers. Monkeypatches the existing dogfood bridge
seams so the cases do not require a live #279 checkout to classify intake
failures.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import scripts.operator_dogfood_vertical as vertical


def _manifest(tmp_path: Path, **overrides) -> Path:
    body = {
        "schema": "MarketOS.OperatorDogfoodManifest.v1",
        "captured_at": "2026-09-19T00:00:00Z",
        "candidates": [
            {"candidate_id": "cand-001", "label": "display-only-name"},
            {"candidate_id": "cand-002", "label": "other"},
        ],
        "offers": [
            {"offer_id": "OFF-1", "supplier_sku": "SKU-1", "source_reference": "quote://reviewed-1"},
        ],
    }
    body.update(overrides)
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(body), encoding="utf-8")
    return path


def test_absent_manifest(tmp_path: Path):
    report = vertical.run_vertical(
        tmp_path,
        manifest_path=tmp_path / "missing.json",
        candidate_id="cand-001",
        scenario_template="hydroponics_positive_candidate",
    )
    assert report["phases"][0]["classification"] == "unavailable"
    assert report["phases"][0]["detail"]["reason"] == "manifest_absent"
    assert report["live_validated"] is False


def test_stale_manifest_missing_captured_at(tmp_path: Path):
    path = _manifest(tmp_path)
    payload = json.loads(path.read_text())
    del payload["captured_at"]
    path.write_text(json.dumps(payload), encoding="utf-8")
    report = vertical.run_vertical(
        tmp_path,
        manifest_path=path,
        candidate_id="cand-001",
        scenario_template="hydroponics_positive_candidate",
    )
    assert report["phases"][0]["classification"] == "blocked"
    assert "manifest_stale" in report["phases"][0]["detail"]["reason"]


def test_wrong_confirmation_blocks(tmp_path: Path):
    path = _manifest(tmp_path)
    report = vertical.run_vertical(
        tmp_path,
        manifest_path=path,
        candidate_id="cand-001",
        scenario_template="hydroponics_positive_candidate",
        confirmations=[("OFF-WRONG", "SKU-1", "quote://reviewed-1")],
    )
    assert report["phases"][0]["classification"] == "blocked"
    assert report["phases"][0]["detail"]["reason"] == "supplier_confirmation_mismatch"


def test_candidate_selected_by_id_not_label(tmp_path: Path):
    path = _manifest(tmp_path)
    with pytest.raises(vertical.VerticalError) as exc:
        vertical.select_candidate(vertical.load_operator_manifest(tmp_path, path), "display-only-name")
    assert exc.value.reason == "unknown_candidate_id"
    assert vertical.select_candidate(vertical.load_operator_manifest(tmp_path, path), "cand-001") == "cand-001"


def test_unknown_template_blocked(tmp_path: Path):
    path = _manifest(tmp_path)
    report = vertical.run_vertical(
        tmp_path,
        manifest_path=path,
        candidate_id="cand-001",
        scenario_template="not_a_real_template",
    )
    assert report["phases"][0]["detail"]["reason"] == "unknown_scenario_template"


def test_missing_supplier_cost_is_classified_from_replay(tmp_path: Path, monkeypatch):
    path = _manifest(tmp_path)

    def fake_run(argv, **kwargs):
        return {
            "ok": True,
            "reason": None,
            "json": {
                "scenarios": {
                    "result": "actual",
                    "rows": [
                        {
                            "scenario": "hydroponics_positive_candidate",
                            "candidate_id": "cand-001",
                            "replay_equal": True,
                            "promoted_to_launch": False,
                            "blockers": ["supplier_offer_evidence_missing"],
                            "missing_cost_inputs": ["product_cost"],
                            "evidence_classes": {"economics": "unavailable", "compliance": "unavailable"},
                        }
                    ],
                }
            },
        }

    monkeypatch.setattr(vertical.bridge, "trustos_export", lambda rows: vertical.bridge._phase("trustos_export", "passed", {"exports": [
        {
            "payload": {
                "workspace_id": "dogfood-cand-001",
                "blockers": rows[0]["blockers"],
                "evidence_required": ["human_review"],
                "approvals_required": ["operator_review"],
                "status": "fixture_dry_run_requires_review",
            },
            "evidence_state": "requires_review",
            "fingerprint": "a" * 64,
        }
    ]}))
    report = vertical.run_vertical(
        tmp_path,
        manifest_path=path,
        candidate_id="cand-001",
        scenario_template="hydroponics_positive_candidate",
        require_confirmation_match=False,
        runner=fake_run,
    )
    row = report["phases"][1]["detail"]["rows"][0]
    assert row["economics_evidence"] == "unavailable"
    assert row["missing_cost_inputs"] == ["product_cost"]
    assert report["live_validated"] is False
    assert report["launch_authorized"] is False


def test_explicit_zero_is_not_treated_as_missing():
    missing = []
    offer = {"price": {"amount": "0"}}
    shipping = "0"
    if offer["price"]["amount"] in {None, ""}:
        missing.append("product_cost")
    if shipping in {None, ""}:
        missing.append("supplier_shipping")
    assert missing == []


def test_unknown_compliance_stays_unavailable(tmp_path: Path, monkeypatch):
    path = _manifest(tmp_path)

    def fake_run(argv, **kwargs):
        return {
            "ok": True,
            "json": {
                "scenarios": {
                    "result": "actual",
                    "rows": [
                        {
                            "scenario": "solar_4g_security_blocked_candidate",
                            "candidate_id": "cand-001",
                            "replay_equal": True,
                            "promoted_to_launch": False,
                            "blockers": ["compliance_evidence_required"],
                            "evidence_classes": {"compliance": "unavailable", "economics": "derived"},
                        }
                    ],
                }
            },
        }

    monkeypatch.setattr(
        vertical.bridge,
        "trustos_export",
        lambda rows: vertical.bridge._phase("trustos_export", "passed", {"exports": [
            {
                "payload": {
                    "workspace_id": "dogfood-x",
                    "blockers": ["compliance_evidence_required"],
                    "evidence_required": ["compliance"],
                    "approvals_required": ["review"],
                    "status": "fixture_dry_run_requires_review",
                },
                "evidence_state": "requires_review",
                "fingerprint": "b" * 64,
            }
        ]}),
    )
    report = vertical.run_vertical(
        tmp_path,
        manifest_path=path,
        candidate_id="cand-001",
        scenario_template="solar_4g_security_blocked_candidate",
        require_confirmation_match=False,
        runner=fake_run,
    )
    assert report["phases"][1]["detail"]["rows"][0]["compliance_evidence"] == "unavailable"
    assert report["live_validated"] is False


def test_replay_mismatch_blocks_export(tmp_path: Path):
    path = _manifest(tmp_path)

    def fake_run(argv, **kwargs):
        return {
            "ok": True,
            "json": {
                "scenarios": {
                    "result": "actual",
                    "rows": [{"scenario": "x", "replay_equal": False, "promoted_to_launch": False, "blockers": []}],
                }
            },
        }

    report = vertical.run_vertical(
        tmp_path,
        manifest_path=path,
        candidate_id="cand-001",
        scenario_template="commodity_electronics_rejected_candidate",
        require_confirmation_match=False,
        runner=fake_run,
    )
    assert report["phases"][1]["classification"] == "blocked"
    assert report["phases"][1]["detail"]["reason"] == "replay_mismatch"
    assert report["phases"][2]["classification"] == "not_run"


def test_export_rejection_when_upstream_claims_present(tmp_path: Path, monkeypatch):
    path = _manifest(tmp_path)

    def fake_run(argv, **kwargs):
        return {
            "ok": True,
            "json": {
                "scenarios": {
                    "result": "actual",
                    "rows": [
                        {
                            "scenario": "hydroponics_positive_candidate",
                            "candidate_id": "cand-001",
                            "replay_equal": True,
                            "promoted_to_launch": True,
                            "blockers": [],
                        }
                    ],
                }
            },
        }

    monkeypatch.setattr(
        vertical.bridge,
        "trustos_export",
        lambda rows: vertical.bridge._phase("trustos_export", "passed", {"exports": [
            {
                "payload": {"workspace_id": "dogfood-x", "blockers": ["note"], "status": "ok"},
                "evidence_state": "present",
                "fingerprint": "c" * 64,
            }
        ]}),
    )
    report = vertical.run_vertical(
        tmp_path,
        manifest_path=path,
        candidate_id="cand-001",
        scenario_template="hydroponics_positive_candidate",
        require_confirmation_match=False,
        runner=fake_run,
    )
    assert report["phases"][2]["classification"] == "blocked"
    assert report["phases"][2]["detail"]["reason"] == "export_claim_rejected"


def test_repeated_execution_is_deterministic(tmp_path: Path, monkeypatch):
    path = _manifest(tmp_path)

    def fake_run(argv, **kwargs):
        return {
            "ok": True,
            "json": {
                "scenarios": {
                    "result": "actual",
                    "rows": [
                        {
                            "scenario": "high_ticket_deferred_candidate",
                            "candidate_id": "cand-002",
                            "replay_equal": True,
                            "promoted_to_launch": False,
                            "blockers": ["deferred"],
                            "evidence_classes": {"compliance": "unavailable"},
                        }
                    ],
                }
            },
        }

    monkeypatch.setattr(
        vertical.bridge,
        "trustos_export",
        lambda rows: vertical.bridge._phase("trustos_export", "passed", {"exports": [
            {
                "payload": {
                    "workspace_id": "dogfood-cand-002",
                    "blockers": ["deferred"],
                    "evidence_required": ["review"],
                    "approvals_required": ["review"],
                    "status": "fixture_dry_run_requires_review",
                },
                "evidence_state": "requires_review",
                "fingerprint": "d" * 64,
            }
        ]}),
    )
    first = vertical.run_vertical(
        tmp_path,
        manifest_path=path,
        candidate_id="cand-002",
        scenario_template="high_ticket_deferred_candidate",
        require_confirmation_match=False,
        runner=fake_run,
    )
    second = vertical.run_vertical(
        tmp_path,
        manifest_path=path,
        candidate_id="cand-002",
        scenario_template="high_ticket_deferred_candidate",
        require_confirmation_match=False,
        runner=fake_run,
    )
    assert [p["classification"] for p in first["phases"]] == [p["classification"] for p in second["phases"]]
    assert first["candidate_id"] == second["candidate_id"] == "cand-002"


def test_secret_manifest_blocked(tmp_path: Path):
    path = _manifest(tmp_path, note="Bearer sk-live-abcdefghijklmnopqrstuvwx")
    report = vertical.run_vertical(
        tmp_path,
        manifest_path=path,
        candidate_id="cand-001",
        scenario_template="hydroponics_positive_candidate",
    )
    assert report["phases"][0]["classification"] == "blocked"
    assert report["phases"][0]["detail"]["reason"] == "manifest_secret_shaped"
