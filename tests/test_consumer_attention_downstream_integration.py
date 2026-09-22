from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from backend.adapters.research.consumer_attention import import_json, normalize_record
from evaluation.commerce.consumer_attention import build_report
from evaluation.commerce.launch_draft_pack import build_launch_draft_pack
from evaluation.commerce.opportunity_synthesis import build_product_opportunity_synthesis
from evaluation.commerce.product_validation_report import generate
from evaluation.commerce.site_draft_builder import build_site_draft_pack


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "consumer_attention" / "service_market_generic.json"
CLI = ROOT / "scripts" / "run_consumer_attention_intelligence.py"


def service_report() -> dict:
    records = import_json(FIXTURE, platform="manual", source_type="manual_csv_import")
    return build_report(records, evidence_mode="fixture_demo", as_of="2026-09-10T00:00:00Z").to_dict()


def blocked_attention_report() -> dict:
    record = normalize_record(
        {
            "candidate_id": "generic-service",
            "query": "service outcome",
            "source": "manual-observation",
            "source_type": "manual_csv_import",
            "platform": "manual",
            "offering_kind": "service",
            "observed_at": "2026-01-01T00:00:00Z",
            "observation_key": "intent",
            "observation_value": "high",
            "hook": "Make the next step easier",
            "source_confidence": 0.95,
        },
        mode="fixture",
    )
    assert record is not None
    return build_report([record], evidence_mode="fixture_demo", as_of="2026-09-10T00:00:00Z").to_dict()


def test_service_attention_reaches_existing_validation_and_draft_consumers_without_authority_escalation():
    attention = service_report()
    validation = generate(consumer_attention=attention).to_dict()
    assert validation["executive_summary"]["consumer_attention_signals"]["status"] == "supplied"
    assert validation["overall_recommendation"] != "advance_to_launch_draft"
    assert validation["supplier_evidence"]["proof_present"] is False

    synthesis = build_product_opportunity_synthesis(None, None, attention).to_dict()
    assert synthesis["overall_recommendation"] != "advance_to_launch_draft"
    assert synthesis["supplier_feasibility"] == 0
    assert synthesis["unit_economics_summary"] == {}
    assert synthesis["source_reports"]["consumer_attention"] == "supplied"
    assert synthesis["source_reports"]["supplier"] == "missing"

    launch = build_launch_draft_pack(synthesis=synthesis, consumer_attention=attention).to_dict()
    assert launch["launch_draft_status"] == "draft_only_pending_human_approval"
    assert launch["approval_checklist"]["launch_authorized"] is False
    assert all(launch[key]["status"] == "draft" for key in ("shopify_draft_payload", "medusa_draft_payload"))

    site = build_site_draft_pack(
        launch_draft_pack=launch,
        opportunity_synthesis=synthesis,
        consumer_attention=attention,
        site_type="service_business_website",
    ).to_dict()
    assert site["approval_checklist"]["publishing_authorized"] is False
    serialized = json.dumps({"attention": attention, "validation": validation, "synthesis": synthesis, "launch": launch, "site": site}, sort_keys=True)
    assert "api_key" not in serialized.lower()
    assert "live_observed" not in serialized


def test_attention_only_output_cannot_be_mislabeled_as_live_or_supplier_proof():
    attention = service_report()
    serialized = json.dumps(attention, sort_keys=True)
    assert "fixture_demo" in serialized
    assert "live_observed" not in serialized
    synthesis = build_product_opportunity_synthesis(None, None, attention).to_dict()
    assert synthesis["evidence_mode"] == "fixture_demo"
    assert synthesis["overall_recommendation"] != "advance_to_launch_draft"
    assert synthesis["supplier_feasibility"] == 0


def test_blocked_attention_state_stays_blocked_through_downstream_boundaries():
    attention = blocked_attention_report()
    assert attention["freshness_status"] == "stale"
    assert attention["candidates"][0]["score"]["recommendation"] == "reject_low_attention"

    validation = generate(consumer_attention=attention).to_dict()
    assert validation["overall_recommendation"] != "advance_to_launch_draft"
    synthesis = build_product_opportunity_synthesis(None, None, attention).to_dict()
    assert synthesis["supplier_feasibility"] == 0
    assert synthesis["unit_economics_summary"] == {}
    launch = build_launch_draft_pack(synthesis=synthesis, consumer_attention=attention).to_dict()
    assert launch["approval_checklist"]["launch_authorized"] is False
    site = build_site_draft_pack(launch_draft_pack=launch, opportunity_synthesis=synthesis, consumer_attention=attention).to_dict()
    assert site["approval_checklist"]["publishing_authorized"] is False


def test_cli_service_fixture_is_deterministic_and_exposes_freshness_contract(tmp_path):
    command = [
        sys.executable,
        str(CLI),
        "--candidate-seed",
        str(FIXTURE),
        "--as-of",
        "2026-09-10T00:00:00Z",
        "--json",
    ]
    first = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=True)
    second = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=True)
    assert first.stdout == second.stdout
    result = json.loads(first.stdout)
    assert result["freshness_status"] == "fresh"
    assert result["offering_kinds"] == ["hybrid", "service"]
    assert result["read_only"] is True
    assert result["network_calls"] is False
    assert result["mutated"] is False


def test_cli_rejects_unparseable_reference_time():
    result = subprocess.run(
        [sys.executable, str(CLI), "--candidate-seed", str(FIXTURE), "--as-of", "not-a-date", "--json"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    assert "observed_at must be an ISO-8601 timestamp" in result.stderr
