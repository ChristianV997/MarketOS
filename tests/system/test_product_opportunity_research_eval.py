"""Tests for fixture evaluation and sanitized live-evidence acceptance."""
from __future__ import annotations

import copy
import functools
import json
from pathlib import Path

import pytest

from scripts import evaluate_product_opportunity_research as harness
from scripts.ai.operator_task_packet import SECRET_SHAPED

ROOT = Path(__file__).resolve().parents[2]
PACKET_TEXT = harness.PACKET_PATH.read_text(encoding="utf-8")
LIVE_PACKET_PATH = ROOT / "tests" / "fixtures" / "product_opportunity_eval" / "live_receipts.json"


def _packet() -> dict:
    return json.loads(PACKET_TEXT)


def _live_packet() -> dict:
    return json.loads(LIVE_PACKET_PATH.read_text(encoding="utf-8"))


@functools.lru_cache(maxsize=1)
def _full_report() -> dict:
    # One full run per session: the report is deterministic, so two tests can share it.
    return harness.evaluate_packet(harness.load_packet())


def _strong_report(**overrides) -> dict:
    report = {
        "report_version": "marketplace-trends-v1",
        "evidence_mode": "fixture_demo",
        "candidates": [{"candidate_id": "candidate-a", "query": "Mini Thermal Printer", "evidence": [{"marketplace": "amazon", "price": 29.99, "currency": "USD", "source_confidence": 0.7, "evidence_mode": "fixture"}]}],
    }
    report.update(overrides)
    return report


def test_packet_loads_with_unique_scenarios_and_all_three_pillars():
    packet = harness.load_packet()
    ids = [item["id"] for item in packet["scenarios"]]
    assert len(ids) == len(set(ids)) == 12
    for scenario in packet["scenarios"]:
        for pillar in harness.PILLARS:
            assert pillar in scenario, (scenario["id"], pillar)


def test_packet_is_fixture_only_and_secret_free():
    assert SECRET_SHAPED.search(PACKET_TEXT) is None
    modes: set[str] = set()

    def collect(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key == "evidence_mode":
                    modes.add(str(item))
                collect(item)
        elif isinstance(value, list):
            for item in value:
                collect(item)

    packet = _packet()
    collect(packet["scenarios"])
    # The baseline scenario references repository fixtures by path, so their modes are checked too.
    for scenario in packet["scenarios"]:
        for pillar in harness.PILLARS:
            if isinstance(scenario.get(pillar), str):
                collect(json.loads((ROOT / scenario[pillar]).read_text(encoding="utf-8")))
    assert modes and modes <= {"fixture", "fixture_demo"}, modes


def test_fixture_packet_cannot_satisfy_live_evidence_mode():
    report = harness.evaluate_live_packet(_packet())
    assert report["acceptance"]["accepted"] is False
    assert report["acceptance"]["blockers"] == ["live_input_schema_mismatch"]
    assert report["diagnostic_outcome"] is None


def test_valid_live_receipts_are_accepted_without_rewriting_diagnostic_recommendation():
    report = harness.evaluate_live_packet(_live_packet())
    assert report["acceptance"]["accepted"] is True
    assert report["acceptance"]["status"] == "structurally_accepted"
    assert report["acceptance"]["receipt_counts"] == {pillar: 1 for pillar in harness.PILLARS}
    assert report["diagnostic_outcome"]["candidate_ids"] == ["candidate-live"]
    assert report["diagnostic_outcome"]["read_only"] is True
    assert report["acceptance"]["acceptance_basis"] == "sanitized_receipt_contract_only"
    assert report["acceptance"]["validation_level"] == "structural_receipt_contract"
    assert report["acceptance"]["source_verification_status"] == "not_performed"
    assert report["acceptance"]["source_verified"] is False
    assert report["acceptance"]["authenticated_observation"] is False
    assert report["provider_calls"] is False
    assert report["mutated"] is False


def test_live_claims_are_not_source_verification():
    packet = _live_packet()
    receipt = packet["receipts"]["marketplace"][0]
    receipt["source_reference"] = "https://claimed.example/receipt/1"
    receipt["source_verified"] = True
    receipt["authenticated_observation"] = True

    report = harness.evaluate_live_packet(packet)

    acceptance = report["acceptance"]
    assert acceptance["accepted"] is True
    assert acceptance["status"] == "structurally_accepted"
    assert acceptance["validation_level"] == "structural_receipt_contract"
    assert acceptance["source_verification_status"] == "not_performed"
    assert acceptance["source_verified"] is False
    assert acceptance["authenticated_observation"] is False


@pytest.mark.parametrize(
    ("path", "value", "expected"),
    [
        (("receipts", "supplier", 0, "is_live"), False, "non_live_receipt"),
        (("receipts", "supplier", 0, "evidence_class"), "manual", "non_live_receipt"),
        (("receipts", "supplier", 0, "evidence_mode"), "manual_import", "non_live_receipt"),
        (("receipts", "supplier", 0, "freshness"), "stale", "stale_receipt"),
        (("receipts", "supplier", 0, "freshness"), "future_dated", "future_dated_receipt"),
        (("receipts", "supplier", 0, "freshness"), "unavailable", "unavailable_receipt"),
        (("receipts", "supplier", 0, "candidate_id"), "hint-only-candidate", "candidate_binding_mismatch"),
        (("receipts", "supplier", 0, "variant_id"), "other-variant", "variant_binding_mismatch"),
        (("receipts", "supplier", 0, "currency"), None, "currency_missing_or_malformed"),
    ],
)
def test_live_receipt_metadata_failures_are_distinct_and_blocking(path, value, expected):
    packet = _live_packet()
    target = packet
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    report = harness.evaluate_live_packet(packet)
    assert report["acceptance"]["accepted"] is False
    assert expected in report["acceptance"]["blockers"]


def test_live_mode_requires_explicit_currency_but_preserves_explicit_zero():
    explicit_zero = _live_packet()
    offer = explicit_zero["reports"]["supplier"]["candidates"][0]["offers"][0]
    offer.update({"unit_cost": 0, "shipping_cost": 0, "estimated_landed_cost": 0})
    assert harness.evaluate_live_packet(explicit_zero)["acceptance"]["accepted"] is True

    missing = _live_packet()
    del missing["reports"]["supplier"]["candidates"][0]["offers"][0]["unit_cost"]
    report = harness.evaluate_live_packet(missing)
    assert report["acceptance"]["accepted"] is False
    assert "incomplete_viability_evidence" in report["acceptance"]["blockers"]


def test_cross_currency_conflict_cannot_be_waived_by_known_gaps():
    packet = _live_packet()
    packet["reports"]["supplier"]["candidates"][0]["offers"][0]["currency"] = "EUR"
    packet["known_gaps"] = [{"id": "intentional", "checks": ["currency_safety_invariant"]}]
    report = harness.evaluate_live_packet(packet)
    assert report["acceptance"]["accepted"] is False
    assert "currency_conflict" in report["acceptance"]["blockers"]
    assert report["acceptance"]["known_gaps_waived"] is False


@pytest.mark.parametrize(
    ("mutate", "expected"),
    [
        (lambda packet: packet["receipts"]["consumer"][0].update({"freshness": "stale"}), "stale_receipt"),
        (lambda packet: packet["reports"]["marketplace"]["candidates"][0]["evidence"][0].update({"price": 10}), "price_conflict"),
        (lambda packet: packet["reports"]["supplier"]["candidates"][0].update({"query": "different variant"}), "identity_conflict"),
        (lambda packet: packet["reports"]["supplier"]["candidates"][0]["offers"][0].pop("unit_cost"), "incomplete_viability_evidence"),
    ],
)
def test_live_non_waivable_invariants_ignore_known_gaps(mutate, expected):
    packet = _live_packet()
    mutate(packet)
    packet["known_gaps"] = [{"id": "attempted-waiver", "checks": ["currency_safety_invariant"]}]
    report = harness.evaluate_live_packet(packet)
    assert report["acceptance"]["accepted"] is False
    assert expected in report["acceptance"]["blockers"]


def test_fixture_report_mode_cannot_be_hidden_behind_live_receipt_metadata():
    packet = _live_packet()
    packet["reports"]["marketplace"]["evidence_mode"] = "fixture_demo"
    report = harness.evaluate_live_packet(packet)
    assert report["acceptance"]["accepted"] is False
    assert "non_live_marketplace_evidence" in report["acceptance"]["blockers"]


def test_live_input_rejects_secret_shaped_or_raw_payload_data():
    packet = _live_packet()
    packet["receipts"]["marketplace"][0]["raw_payload"] = {"html": "sk_live_synthetic_secret_value"}
    report = harness.evaluate_live_packet(packet)
    assert report["acceptance"]["accepted"] is False
    assert report["acceptance"]["blockers"] == ["raw_or_secret_payload"]


@pytest.mark.parametrize(
    ("pillar", "field"),
    [("marketplace", "evidence"), ("supplier", "offers"), ("consumer", "freshness_statuses")],
)
def test_live_malformed_nested_reports_fail_closed_without_raising(pillar, field):
    packet = _live_packet()
    candidate = packet["reports"][pillar]["candidates"][0]
    candidate[field] = None
    report = harness.evaluate_live_packet(packet)
    assert report["acceptance"]["accepted"] is False
    assert "malformed_report" in report["acceptance"]["blockers"]


def test_live_cli_does_not_fallback_to_demo_fixture(capsys):
    assert harness.main(["--mode", "live_evidence", "--packet", str(LIVE_PACKET_PATH)]) == 0
    assert json.loads(capsys.readouterr().out)["acceptance"]["accepted"] is True
    assert harness.main(["--mode", "live_evidence"]) == 2
    blocked = json.loads(capsys.readouterr().out)
    assert blocked["acceptance"]["accepted"] is False
    assert blocked["diagnostic_outcome"] is None


def test_live_packet_file_size_is_bounded(tmp_path):
    path = tmp_path / "oversized.json"
    path.write_bytes(b"{" + b"x" * harness.LIVE_MAX_PACKET_BYTES)
    report = harness.evaluate_live_file(path)
    assert report["acceptance"]["blockers"] == ["live_input_oversized"]


def test_known_gaps_are_exactly_the_observed_failures_and_none_is_unexpected():
    report = _full_report()
    expected_hard_failures = {
        ("S04_cross_currency_join", "currency_safety_invariant"),
        ("S05_stale_consumer_attention", "stale_evidence_safety_invariant"),
        ("S06_conflicting_price_sources", "price_safety_invariant"),
        ("S07_incomplete_observations", "incomplete_evidence_safety_invariant"),
        ("S09_identity_variant_mismatch", "identity_safety_invariant"),
    }
    unexpected = {
        (scenario["id"], check["name"])
        for scenario in report["scenarios"]
        for check in scenario["checks"]
        if check["status"] == "unexpected_fail"
    }
    assert unexpected == expected_hard_failures
    assert set(report["aggregate"]["unexpected_failures"]) == {
        f"{scenario}:{check}" for scenario, check in expected_hard_failures
    }
    observed = {
        (scenario["id"], check["name"])
        for scenario in report["scenarios"]
        for check in scenario["checks"]
        if check["status"] == "known_gap"
    }
    documented = {(gap["scenario"], name) for gap in report["known_gaps"] for name in gap["checks"]}
    assert observed == documented


@pytest.mark.parametrize(
    ("scenario_id", "check_name"),
    [
        ("S04_cross_currency_join", "currency_safety_invariant"),
        ("S05_stale_consumer_attention", "stale_evidence_safety_invariant"),
        ("S06_conflicting_price_sources", "price_safety_invariant"),
        ("S07_incomplete_observations", "incomplete_evidence_safety_invariant"),
        ("S09_identity_variant_mismatch", "identity_safety_invariant"),
    ],
)
def test_critical_evidence_invariants_cannot_be_documented_away(scenario_id, check_name):
    report = harness.evaluate_packet(harness.load_packet(), only={scenario_id})
    scenario = report["scenarios"][0]
    check = next(item for item in scenario["checks"] if item["name"] == check_name)

    assert check["status"] == "unexpected_fail"
    assert report["checks"]["unexpected_fail"] == 1


def test_report_is_deterministic_across_runs_on_a_bounded_subset():
    subset = {"S01_strong_three_pillar_fixture", "S04_cross_currency_join"}
    first = json.dumps(harness.evaluate_packet(harness.load_packet(), only=subset), sort_keys=True)
    second = json.dumps(harness.evaluate_packet(harness.load_packet(), only=subset), sort_keys=True)
    assert first == second


def test_every_scenario_is_read_only_non_authorizing_and_non_mutating():
    report = _full_report()
    for scenario in report["scenarios"]:
        outcome = scenario["outcome"]
        assert outcome["read_only"] is True, scenario["id"]
        assert outcome["network_calls"] is False, scenario["id"]
        assert outcome["mutated"] is False, scenario["id"]
        assert outcome["next_best_action"] in harness.NON_EXECUTING_ACTIONS, scenario["id"]


def test_measure_detects_cross_currency_identity_and_price_conflicts():
    reports = {
        "marketplace": _strong_report(),
        "supplier": {"candidates": [{"candidate_id": "candidate-a", "query": "mini thermal printer 58mm roll", "offers": [{"supplier": "cj", "unit_cost": 1, "shipping_cost": 1, "estimated_landed_cost": 2, "delivery_max_days": 9, "currency": "EUR", "evidence_mode": "fixture"}], "score": {"economics": {"target_sell_price": 49.99}}}]},
        "consumer": None,
    }
    metrics = harness.measure(reports)
    assert metrics["currency_unreconciled"] == ["candidate-a"]
    assert metrics["identity_conflicts"] == ["candidate-a"]
    assert metrics["price_conflicts"] == ["candidate-a"]
    assert metrics["pillars_supplied"] == 2


def _query_variant_reports(supplier_query="mini thermal printer supplier"):
    queries = {
        "marketplace": "mini thermal printer buy",
        "supplier": supplier_query,
        "consumer": "mini thermal printer review",
    }
    return {
        pillar: {"candidates": [{"candidate_id": "candidate-a", "query": query}]}
        for pillar, query in queries.items()
    }


def test_measure_accepts_explicit_pillar_query_variants_from_a_runner_contract():
    reports = _query_variant_reports()
    context = {
        "candidate-a": {
            "marketplace": "mini thermal printer buy",
            "supplier": "mini thermal printer supplier",
            "consumer": "mini thermal printer review",
        }
    }
    metrics = harness.measure(reports, identity_query_context=context)
    assert metrics["identity_conflicts"] == []


def test_query_variant_context_does_not_waive_an_actual_variant_mismatch():
    reports = _query_variant_reports("mini thermal printer 58mm paper roll")
    context = {
        "candidate-a": {
            "marketplace": "mini thermal printer buy",
            "supplier": "mini thermal printer supplier",
            "consumer": "mini thermal printer review",
        }
    }
    metrics = harness.measure(reports, identity_query_context=context)
    assert metrics["identity_conflicts"] == ["candidate-a"]


def test_packet_applies_runner_query_context_without_waiving_identity_check():
    packet = {
        "schema": harness.SCHEMA,
        "scenarios": [{
            "id": "runner-query-context",
            **_query_variant_reports(),
            "identity_query_context": {
                "candidate-a": {
                    "marketplace": "mini thermal printer buy",
                    "supplier": "mini thermal printer supplier",
                    "consumer": "mini thermal printer review",
                }
            },
            "expectations": {"expected_metrics": {"identity_conflicts": 0}},
        }],
        "known_gaps": [],
    }
    report = harness.evaluate_packet(packet)
    check = next(item for item in report["scenarios"][0]["checks"] if item["name"] == "harness_metrics_match")
    assert check["status"] == "pass"


def test_measure_completeness_and_warnings_without_pillars():
    empty = harness.measure({"marketplace": None, "supplier": None, "consumer": None})
    assert empty["pillars_supplied"] == 0 and empty["completeness"] is None and empty["effective_pillars"] == 0
    metrics = harness.measure({"marketplace": _strong_report(warnings=["provider_failed:amazon"]), "supplier": None, "consumer": None})
    assert metrics["pillar_warnings"] == ["marketplace:provider_failed:amazon"]
    assert metrics["completeness"] == 1.0


@pytest.mark.parametrize(
    ("statuses", "expected"),
    [([], "unrepresented"), (["fresh"], "fresh"), (["fresh", "stale"], "stale"), (["future_dated"], "future_dated"), (["unavailable", "unavailable"], "unavailable")],
)
def test_freshness_classification_is_conservative(statuses, expected):
    assert harness._freshness_class(statuses) == expected


def test_assumption_text_is_not_a_missing_evidence_caution():
    # Regression for a vacuous pass: "supplier_readonly_proof_missing" is an ordinary fixture-mode
    # assumption and must not satisfy an incomplete-evidence caution.
    assert harness._flagged(["supplier_readonly_proof_missing"], "incomplete") is False
    assert harness._flagged(["target_sell_price_missing"], "incomplete", supplier_present=True) is True


def test_resolve_report_accepts_only_repository_fixture_json():
    with pytest.raises(ValueError):
        harness._resolve_report("/etc/passwd")
    with pytest.raises(ValueError):
        harness._resolve_report("tests/fixtures/../../secret.json")
    with pytest.raises(ValueError):
        harness._resolve_report("tests/fixtures/opportunity_synthesis/marketplace_trend_report.txt")
    assert harness._resolve_report(None) is None


def test_load_packet_rejects_wrong_schema_and_duplicate_ids(tmp_path):
    bad_schema = tmp_path / "schema.json"
    bad_schema.write_text(json.dumps({"schema": "other", "scenarios": [{"id": "x"}]}), encoding="utf-8")
    with pytest.raises(ValueError):
        harness.load_packet(bad_schema)
    duplicate = _packet()
    duplicate["scenarios"].append(copy.deepcopy(duplicate["scenarios"][0]))
    path = tmp_path / "duplicate.json"
    path.write_text(json.dumps(duplicate), encoding="utf-8")
    with pytest.raises(ValueError):
        harness.load_packet(path)


def test_cli_writes_a_file_only_when_output_is_given(tmp_path, capsys):
    scenario = "B00_canonical_trio_baseline"
    assert harness.main(["--scenario", scenario]) == 0
    assert json.loads(capsys.readouterr().out)["scenario_count"] == 1
    target = tmp_path / "report.json"
    assert harness.main(["--scenario", scenario, "--output", str(target)]) == 0
    assert json.loads(target.read_text(encoding="utf-8"))["scenario_count"] == 1


@pytest.mark.parametrize("banned", ["subprocess", "socket", "urllib", "http.client", "requests", "getenv", "os.environ", "importlib"])
def test_harness_source_has_no_network_process_or_credential_access(banned):
    source = Path(harness.__file__).read_text(encoding="utf-8")
    assert banned not in source


def test_mutating_synthesis_is_detected_not_masked(monkeypatch):
    real = harness.build_product_opportunity_synthesis

    def mutating(marketplace, supplier, consumer):
        marketplace["candidates"][0]["candidate_id"] = "mutated-by-synthesis"
        return real(marketplace, supplier, consumer)

    monkeypatch.setattr(harness, "build_product_opportunity_synthesis", mutating)
    with pytest.raises(RuntimeError, match="synthesis mutated"):
        harness.evaluate_packet(harness.load_packet(), only={"B00_canonical_trio_baseline"})


def test_unknown_scenario_id_is_rejected():
    with pytest.raises(ValueError, match="unknown scenario ids"):
        harness.evaluate_packet(harness.load_packet(), only={"no_such_scenario"})


def test_unknown_expectation_key_and_gap_check_are_rejected(tmp_path):
    packet = _packet()
    packet["scenarios"][0]["expectations"]["must_not_advnace"] = True
    path = tmp_path / "typo.json"
    path.write_text(json.dumps(packet), encoding="utf-8")
    with pytest.raises(ValueError, match="unknown expectation keys"):
        harness.load_packet(path)
    packet = _packet()
    packet["known_gaps"].append({"id": "GAP-X", "scenario": packet["scenarios"][0]["id"], "checks": ["not_a_check"], "reason": "x"})
    path.write_text(json.dumps(packet), encoding="utf-8")
    with pytest.raises(ValueError, match="unknown checks"):
        harness.load_packet(path)


@pytest.mark.parametrize(
    "identity_query_context",
    [
        {},
        {"candidate-a": {"attention": "query"}},
        {"candidate-a": {"marketplace": ""}},
    ],
)
def test_load_packet_rejects_malformed_runner_query_context(tmp_path, identity_query_context):
    packet = _packet()
    packet["scenarios"][0]["identity_query_context"] = identity_query_context
    path = tmp_path / "bad_identity_context.json"
    path.write_text(json.dumps(packet), encoding="utf-8")
    with pytest.raises(ValueError, match="identity_query_context"):
        harness.load_packet(path)


def test_caution_matching_uses_exact_codes_only():
    assert harness._flagged(["correlated alias 'a' of 'b' shares query"], "identity") is False
    assert harness._flagged(["currency_missing"], "currency") is False
    assert harness._flagged(["currency_mismatch"], "currency") is True
    assert harness._flagged(["supplier_readonly_proof_missing"], "incomplete") is False
    assert harness._flagged(["target_sell_price_missing"], "incomplete", supplier_present=False) is False
    assert harness._flagged(["target_sell_price_missing"], "incomplete", supplier_present=True) is True
    assert harness._flagged(["consumer_evidence_stale"], "freshness") is True
    assert harness._flagged(["stale_cache"], "freshness") is False


def test_partially_unavailable_source_is_not_fresh():
    assert harness._freshness_class(["fresh", "unavailable"]) == "unavailable"
    assert harness._freshness_class(["fresh", "stale"]) == "stale"


def test_pillar_warning_surfacing_is_exact_not_substring():
    assert harness._surfaced("marketplace:provider_failed:amazon", ["provider_failed:amazon_extra"]) is False
    assert harness._surfaced("marketplace:provider_failed:amazon", ["provider_failed:amazon"]) is True
