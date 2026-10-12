"""Tests for the fixture-only Product Opportunity Synthesis evaluation harness."""
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


def _packet() -> dict:
    return json.loads(PACKET_TEXT)


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


def test_known_gaps_are_exactly_the_observed_failures_and_none_is_unexpected():
    report = _full_report()
    assert report["checks"]["unexpected_fail"] == 0
    assert report["aggregate"]["unexpected_failures"] == []
    observed = {
        (scenario["id"], check["name"])
        for scenario in report["scenarios"]
        for check in scenario["checks"]
        if check["status"] == "known_gap"
    }
    documented = {(gap["scenario"], name) for gap in report["known_gaps"] for name in gap["checks"]}
    assert observed == documented


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
