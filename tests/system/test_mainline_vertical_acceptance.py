"""Acceptance contract for the authorities present on refreshed mainline.

These tests intentionally consume the executable acceptance command rather
than recreating a second replay, economics, or export implementation. The
module-scoped report keeps the system test bounded while still checking each
scenario and each security boundary in the emitted report.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.ai import run_mainline_vertical_acceptance as acceptance


EXPECTED_SCENARIOS = {
    "hydroponics_positive_candidate": "hydroponics-kit",
    "smart_pet_support_burden_candidate": "smart-pet-feeder",
    "solar_4g_security_blocked_candidate": "solar-4g-camera",
    "commodity_electronics_rejected_candidate": "commodity-earbuds",
    "high_ticket_deferred_candidate": "walking-pad",
}

EXPECTED_REPLAY_HASH_DIGESTS = {
    "hydroponics_positive_candidate": "9fb24c4c95fea27bda83afe11464073783782c96f44eb495a63eb4b024364c0d",
    "smart_pet_support_burden_candidate": "c4374cd8a9b990555a56f092fa14c15fb37f6d05e18c6459db6fb48ae83ff6d0",
    "solar_4g_security_blocked_candidate": "6ec683136d09e6e1cc49e0c26e616f5a17e98cc3f5d4fb2e5342415532682540",
    "commodity_electronics_rejected_candidate": "87f3b78a7c8d2ef793c2bcbe0b0c9e4499fc06b93a5389bc3505d5db7bd8d14e",
    "high_ticket_deferred_candidate": "7c2de842a76a9498b7f4b9d62d0f01f4f9957244312bac505ad32368e8b744c9",
}


@pytest.fixture(scope="module")
def report() -> dict:
    refs = (
        acceptance._git_value("rev-parse", "HEAD"),
        acceptance._git_value("rev-parse", "origin/main"),
        acceptance._git_value("merge-base", "HEAD", "origin/main"),
    )
    if not acceptance._is_mainline_identity(*refs):
        pytest.skip("mainline acceptance is not applicable outside exact refreshed origin/main")
    result = acceptance.run_acceptance()
    assert result["status"] == "passed", result
    return result


def _scenario_reports(report: dict) -> dict[str, dict]:
    return {
        item["summary"]["scenario"]: item
        for item in report["replay"]["scenarios"]
    }


def test_non_mainline_execution_fails_closed(monkeypatch):
    refs = {
        ("rev-parse", "HEAD"): "head-sha",
        ("rev-parse", "origin/main"): "main-sha",
        ("merge-base", "HEAD", "origin/main"): "merge-base-sha",
    }
    monkeypatch.setattr(acceptance, "_git_value", lambda *args: refs[args])
    monkeypatch.setattr(acceptance, "_status_hash", lambda: "stable-status")
    def unexpected_call(*args, **kwargs):
        raise AssertionError("non-mainline acceptance must not execute upstream authorities")

    monkeypatch.setattr(acceptance, "_run_replay", unexpected_call)
    monkeypatch.setattr(acceptance, "_run_dogfood", unexpected_call)
    monkeypatch.setattr(acceptance, "_run_direct_commerce_scope", unexpected_call)
    monkeypatch.setattr(acceptance, "_run_cost_and_identity_probes", unexpected_call)
    monkeypatch.setattr(acceptance, "_run_safe_export_probe", unexpected_call)
    monkeypatch.setattr(acceptance, "_service_delivery_authority_status", unexpected_call)

    result = acceptance.run_acceptance()

    assert result["checks"]["mainline_identity"] is False
    assert result["status"] == "blocked"
    assert result["replay"] == {"status": "not_run", "reason": "exact_ref_identity_required"}
    for key in (
        "dogfood",
        "direct_commerce_scope",
        "negative_and_identity_probes",
        "trustos_export",
        "service_delivery_upstream",
    ):
        assert result[key]["status"] == "not_run"


def test_acceptance_report_is_mainline_only_and_versioned(report: dict):
    assert report["schema"] == "MarketOS.MainlineVerticalAcceptance.v1"
    assert report["head_sha"] == report["origin_main_sha"] == report["merge_base"]
    assert report["replay"]["commit"] == report["head_sha"]
    assert report["replay"]["base_sha"] == report["head_sha"]
    assert set(report["merged_authorities"]) == {
        "research_to_decision",
        "commercial_replay",
        "operator_dogfood",
        "economics",
        "events",
        "fulfillment",
        "trustos_export",
    }


def test_all_five_mainline_replay_scenarios_are_present_with_product_ids(report: dict):
    scenarios = _scenario_reports(report)
    assert set(scenarios) == set(EXPECTED_SCENARIOS)
    for template, candidate_id in EXPECTED_SCENARIOS.items():
        summary = scenarios[template]["summary"]
        assert summary["candidate_id"] == candidate_id
        assert candidate_id != template
        assert scenarios[template]["checks"]["known_candidate_identity"] is True
        assert scenarios[template]["checks"]["candidate_id_not_template"] is True


@pytest.mark.parametrize("scenario", sorted(EXPECTED_SCENARIOS))
def test_each_scenario_has_separate_commerce_and_fulfillment_event_scopes(report: dict, scenario: str):
    summary = _scenario_reports(report)[scenario]["summary"]
    assert summary["commerce_event_count"] == 17
    assert summary["fulfillment_event_count"] == 20
    assert summary["event_count"] == 37
    assert summary["first_append_count"] == 37
    assert summary["second_append_idempotent_count"] == 37


@pytest.mark.parametrize("scenario", sorted(EXPECTED_SCENARIOS))
def test_each_scenario_preserves_canonical_event_replay_hashes(report: dict, scenario: str):
    item = _scenario_reports(report)[scenario]
    summary = item["summary"]
    hashes = summary["event_replay_hashes"]
    assert len(hashes) == 37
    assert all(len(value) == 64 for value in hashes)
    assert len(summary["replay_hash"]) == 64
    assert len(summary["event_hash_sequence_digest"]) == 64
    assert summary["event_hash_sequence_digest"] == EXPECTED_REPLAY_HASH_DIGESTS[scenario]
    assert summary["replay_hash"] == EXPECTED_REPLAY_HASH_DIGESTS[scenario]
    assert item["checks"]["hash_sequence_complete"] is True
    assert item["checks"]["replay_deterministic"] is True
    assert item["checks"]["event_validation_clean"] is True


def test_direct_commerce_scope_keeps_the_17_event_contract(report: dict):
    direct = report["direct_commerce_scope"]
    assert direct["status"] == "passed"
    assert direct["event_count"] == 17
    assert len(direct["hash_sequence"]) == 17
    assert len(direct["hash_sequence_digest"]) == 64
    assert direct["checks"] == {
        "commerce_aggregate": True,
        "commerce_event_count": True,
        "hash_sequence_complete": True,
        "sequence_clean": True,
    }


def test_replay_repeatability_is_verified_by_the_existing_runner(report: dict):
    for item in report["replay"]["scenarios"]:
        assert item["summary"]["replay_equal"] is True
        assert item["checks"]["append_idempotent"] is True
    assert report["replay"]["status"] == "passed"


def test_missing_cost_is_unavailable_and_not_a_zero_contribution(report: dict):
    probe = report["negative_and_identity_probes"]["missing_cost"]
    assert probe["status"] == "passed"
    assert probe["checks"] == {
        "command_executed": True,
        "economics_unavailable": True,
        "missing_inputs_explicit": True,
        "no_contribution_leak": True,
        "promotion_blocked": True,
    }


def test_explicit_zero_remains_a_supplied_amount(report: dict):
    probe = report["negative_and_identity_probes"]["explicit_zero"]
    assert probe["status"] == "passed"
    assert probe["checks"]["economics_calculated"] is True
    assert probe["checks"]["explicit_zero_preserved"] is True
    assert probe["checks"]["zero_not_missing"] is True


def test_currency_mismatch_fails_closed_without_fx_inference(report: dict):
    probe = report["negative_and_identity_probes"]["currency_mismatch"]
    assert probe == {
        "status": "passed",
        "checks": {"currency_mismatch_rejected": True},
    }


def test_candidate_and_template_provenance_are_separate_contracts(report: dict):
    probe = report["negative_and_identity_probes"]["candidate_template_provenance"]
    assert probe["status"] == "passed"
    assert probe["checks"]["candidate_id_selected"] is True
    assert probe["checks"]["template_selected_explicitly"] is True
    assert probe["checks"]["label_not_routing_authority"] is True
    assert probe["checks"]["live_validated_false"] is True
    assert probe["checks"]["launch_authorized_false"] is True


def test_fixture_and_simulated_evidence_never_becomes_live_proof(report: dict):
    vocabulary = set(report["replay"]["evidence_class_vocabulary"])
    assert {"fixture", "simulated_or_planned", "unavailable", "ci_unavailable"}.issubset(vocabulary)
    for item in report["replay"]["scenarios"]:
        summary = item["summary"]
        evidence = summary["evidence_classes"]
        assert evidence["research_input"] == "fixture"
        assert evidence["commerce_lifecycle"] == "simulated_or_planned"
        assert evidence["fulfillment_lifecycle"] == "simulated_or_planned"
        assert evidence["ci"] == "ci_unavailable"
        assert item["checks"]["fixture_ceiling_preserved"] is True
        assert item["checks"]["promotion_blocked"] is True


def test_compliance_without_authoritative_evidence_is_not_assessed(report: dict):
    for item in report["replay"]["scenarios"]:
        assert item["checks"]["compliance_not_assessed"] is True
        assert item["summary"]["evidence_classes"]["compliance"] == "unavailable"


def test_service_economics_adapter_is_available_but_service_delivery_route_is_not(report: dict):
    service = report["replay"]["service_economics_adapter"]
    assert service["status"] == "passed"
    assert service["checks"] == {
        "adequate_service_data_is_available": True,
        "insufficient_service_data_blocks": True,
        "thin_service_economics_is_none": True,
    }
    upstream = report["service_delivery_upstream"]
    assert upstream["status"] == "unavailable"
    assert upstream["source_prs"] == [271, 275]
    assert "service_delivery_projection.py" in " ".join(upstream["missing_paths"])


def test_trustos_dogfood_export_is_bound_and_requires_review(report: dict):
    dogfood = report["dogfood"]
    assert dogfood["status"] == "passed"
    assert dogfood["export_count"] == 5
    assert all(len(value) == 64 for value in dogfood["export_fingerprints"])
    assert dogfood["checks"]["redaction_validated"] is True
    assert dogfood["checks"]["review_required"] is True
    assert dogfood["checks"]["no_mutation"] is True


def test_direct_trustos_probe_rejects_internal_and_cross_workspace_payloads(report: dict):
    export = report["trustos_export"]
    assert export["status"] == "passed"
    assert export["checks"]["registered_workspace_exported"] is True
    assert export["checks"]["unsafe_internal_prompt_rejected"] is True
    assert export["checks"]["workspace_mismatch_rejected"] is True
    assert export["checks"]["redaction_validated"] is True


def test_all_mutation_controls_are_false_and_worktree_fingerprint_is_stable(report: dict):
    assert report["checks"]["worktree_unchanged"] is True
    assert report["checks"]["service_delivery_status_explicit"] is True
    assert all(value is False for value in report["safety"].values() if isinstance(value, bool))
    assert report["safety"]["ci"] == "ci_unavailable"
    assert report["safety"]["evidence_mode"] == "fixture_and_simulated_or_planned_only"


def test_acceptance_report_does_not_echo_the_local_filesystem_path(report: dict):
    rendered = json.dumps(report, sort_keys=True)
    assert str(Path(__file__).resolve().parents[2]) not in rendered
    assert "credentials" in rendered
    assert "client-workspace-redaction-v1" in rendered


def test_markdown_entrypoint_is_bounded_and_reports_upstream_unavailability(monkeypatch, capsys):
    minimal = {
        "status": "passed",
        "head_sha": "a" * 40,
        "origin_main_sha": "a" * 40,
        "service_delivery_upstream": {"status": "unavailable"},
        "checks": {"replay": True, "dogfood": True},
    }
    monkeypatch.setattr(acceptance, "run_acceptance", lambda: minimal)
    assert acceptance.main(["--markdown"]) == 0
    output = capsys.readouterr().out
    assert "Mainline vertical acceptance: passed" in output
    assert "Service-delivery upstream: `unavailable`" in output
