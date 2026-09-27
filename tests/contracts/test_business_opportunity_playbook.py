"""Structural contract for the methodology-only business opportunity playbook."""

from __future__ import annotations

import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PLAYBOOK = ROOT / "docs" / "ai" / "BUSINESS_OPPORTUNITY_EVALUATION_PLAYBOOK.md"
FIXTURES = ROOT / "tests" / "fixtures" / "opportunity_playbook"

SCENARIOS = {
    "high_demand_poor_margin",
    "weak_demand_strong_supply_gap",
    "foreign_market_no_reachable_buyer",
    "strong_pain_regulatory_block",
    "arbitrage_erased_by_logistics",
    "digital_service_insufficient_distribution",
}
TAXONOMY = {"fact", "inference", "hypothesis", "unknown"}
EVIDENCE_CLASSES = {"fixture", "manual", "manual_import", "observed", "derived", "simulated", "planned", "live", "live_readonly", "unavailable"}
FORBIDDEN_PAYLOAD_MARKERS = ("password=", "api_key=", "authorization:", "<html", "BEGIN PRIVATE KEY", "C:\\Users\\")


def read_playbook() -> str:
    return PLAYBOOK.read_text(encoding="utf-8")


def normalized_playbook() -> str:
    return " ".join(read_playbook().lower().split())


def test_playbook_exists_and_covers_required_methodology() -> None:
    text = read_playbook().lower()
    required = (
        "reachable buyer",
        "recurring pain",
        "current alternatives",
        "supply gap",
        "evidence quality",
        "unit economics",
        "regulatory and platform risk",
        "cheapest decision-changing experiment",
        "fact",
        "inference",
        "hypothesis",
        "unknown",
        "discover",
        "evaluate",
        "compare",
        "validate",
        "review-results",
        "fatal gates",
        "missing",
        "explicit zero",
        "logistics",
        "duty",
        "tax",
        "returns",
        "platform fees",
        "cac",
        "fx",
        "client-safe",
    )
    missing = [term for term in required if term not in text]
    assert not missing, f"missing playbook terms: {missing}"


def test_playbook_declares_non_authority_boundary() -> None:
    text = normalized_playbook()
    required = (
        "not a scorer",
        "not a ranker",
        "not an economics engine",
        "not a promotion gate",
        "not a billing system",
        "not a crm",
        "not a launch authority",
        "does not provide authentication",
        "supplier verification",
    )
    assert all(term in text for term in required)
    assert "backend/economics/kernel.py" in text
    assert "evaluation.trustos.client_workspace_isolation.py" in text


def test_playbook_uses_existing_evidence_ceiling_language() -> None:
    text = normalized_playbook()
    for term in ("fixture", "manual", "observed", "derived", "simulated", "planned", "live"):
        assert term in text
    assert "never becomes live proof" in text
    assert "missing cost" in text
    assert "currency mismatch must fail closed" in text


def test_six_synthetic_scenarios_have_stable_shape() -> None:
    paths = sorted(FIXTURES.glob("*.json"))
    assert {path.stem for path in paths} == SCENARIOS
    for path in paths:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
        assert data["scenario_id"] == path.stem
        assert data["candidate_id"].startswith("fixture-candidate-")
        assert data["workspace_id"] == "fixture-workspace-methodology"
        assert data["offering_kind"] in {"goods", "service", "digital_service", "physical_service", "hybrid", "unknown"}
        assert data["claims"] and data["evidence"] and data["economics"]
        assert data["expected"]["status"] in {"blocked", "needs_evidence", "review_required", "planning_only"}
        for claim in data["claims"]:
            assert claim["taxonomy"] in TAXONOMY
            assert claim["source_ref"].startswith("fixture://")
            assert claim["evidence_class"] in EVIDENCE_CLASSES
        for evidence in data["evidence"]:
            assert evidence["source_ref"].startswith("fixture://")
            assert evidence["evidence_class"] in EVIDENCE_CLASSES
        assert data["blockers"]
        assert data["experiment"]["evidence_class"] == "planned"
        assert json.dumps(data, sort_keys=True, separators=(",", ":")) == json.dumps(data, sort_keys=True, separators=(",", ":"))


def test_fixtures_are_synthetic_and_do_not_contain_sensitive_payloads() -> None:
    for path in FIXTURES.glob("*.json"):
        raw = path.read_text(encoding="utf-8").lower()
        assert all(marker.lower() not in raw for marker in FORBIDDEN_PAYLOAD_MARKERS)
        assert "http://" not in raw and "https://" not in raw
        assert not re.search(r"(?:^|[\\/])(?:\.env|secrets?|credentials?)(?:$|[\\/])", raw)


def test_missing_and_explicit_zero_rules_are_not_collapsed() -> None:
    text = read_playbook().lower()
    assert "missing cost" in text
    assert "explicit quoted zero" in text
    assert "never an observed zero" in text
    for path in FIXTURES.glob("*.json"):
        data = json.loads(path.read_text(encoding="utf-8"))
        economics = data["economics"]
        for name, value in economics.items():
            if name == "currency":
                continue
            assert value != 0
            assert value != "0"


def test_fixture_identifiers_are_not_template_authority_or_runtime_code() -> None:
    for path in FIXTURES.glob("*.json"):
        raw = path.read_text(encoding="utf-8")
        assert "import " not in raw
        assert "build_" not in raw
        assert "rank_" not in raw
        assert "score" not in raw.lower()
        assert "launch_authorized" not in raw
