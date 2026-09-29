from __future__ import annotations

import copy
import json
import subprocess
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from backend.economics.kernel import (
    CurrencyMismatchError,
    EvidenceRef,
    MarketLane,
    Money,
)
from backend.events.repository import InMemoryEventRepository
from backend.events.replay_certification import replay_summary
from backend.workspaces.client_workspace import ClientWorkspace
from backend.workspaces.registry import WorkspaceRegistry
from evaluation.commerce.opportunity_synthesis import build_product_opportunity_synthesis
import evaluation.companyos.service_market_research as service_research
from evaluation.companyos.service_market_research import (
    INPUT_CONTRACT_ID,
    ServiceMarketObservation,
    assess_service_market_candidate,
    load_input_document,
    run_input_document,
)


AS_OF = datetime(2026, 9, 19, 12, tzinfo=timezone.utc)


def _ref(evidence_id: str, *, state: str = "fixture") -> EvidenceRef:
    return EvidenceRef(
        evidence_id,
        source_type="fixture_market_import",
        evidence_state=state,
        captured_at="2026-09-01T00:00:00+00:00",
        valid_until="2026-10-01T00:00:00+00:00",
        snapshot_hash="a" * 64,
    )


def _money(amount: str, evidence_id: str, *, currency: str = "MXN", state: str = "fixture") -> Money:
    ref = _ref(evidence_id, state=state)
    return Money(
        amount,
        currency,
        source="fixture_import",
        evidence_ref=ref,
        provenance="fixture",
        evidence_state=state,
    )


def _workspace_registry(tmp_path: Path) -> tuple[ClientWorkspace, WorkspaceRegistry]:
    workspace = ClientWorkspace(
        workspace_id="service-market-dogfood",
        name="Service market dogfood",
        workspace_type="dry_run",
        created_at=0,
        updated_at=0,
    )
    registry = WorkspaceRegistry(str(tmp_path / "workspace-registry.json"))
    registry.register(workspace)
    return workspace, registry


def _candidate(tmp_path: Path, **overrides):
    workspace, registry = _workspace_registry(tmp_path)
    values = {
        "candidate_id": "operations-automation-advisory",
        "offering_type": "service",
        "service_fee": _money("5000", "fee"),
        "delivery_cost": _money("1000", "labor"),
        "tooling_cost": _money("200", "tooling"),
        "pass_through_cost": _money("100", "pass-through"),
        "refund_revision_reserve": _money("100", "reserve"),
        "delivery_hours": Decimal("20"),
        "delivery_evidence": _ref("delivery-hours"),
        "capacity_hours": Decimal("40"),
        "capacity_evidence": _ref("available-capacity"),
        "observations": (
            ServiceMarketObservation(
                metric="demand",
                subject_id="qualified-requests",
                value=Decimal("10"),
                unit="requests_per_month",
                evidence_ref=_ref("demand"),
            ),
            ServiceMarketObservation(
                metric="competitor_price",
                subject_id="comparable-service-a",
                value=_money("6000", "competitor-price"),
                unit="MXN",
                evidence_ref=_ref("competitor-price"),
            ),
        ),
        "lane": MarketLane(
            lane_id="mx-remote-services",
            origin="MX",
            ship_from="not_applicable_service_origin",
            warehouse="not_applicable_service_fulfillment",
            destination_country="MX",
            currency="MXN",
            evidence_refs=(_ref("market-lane"),),
        ),
        "market_access_evidence": (),
        "evidence_source_mode": "fixture",
        "workspace": workspace,
        "registry": registry,
        "as_of": AS_OF,
    }
    values.update(overrides)
    return values


def _assess(tmp_path: Path, **overrides):
    return assess_service_market_candidate(**_candidate(tmp_path, **overrides))


def test_generic_service_candidate_uses_kernel_and_remains_review_only(tmp_path):
    economics, event, client_export = _assess(tmp_path)

    assert economics is not None
    assert economics.contribution.amount == Decimal("3600")
    assert economics.incremental_contribution is None
    assert economics.orders_required_to_recover_fee is None
    assert economics.evidence_state == "assumed"
    assert event.payload["offering_type"] == "service"
    assert event.payload["market_access_assessment"] == "not_assessed"
    assert event.payload["recommendation"] == "defer_for_evidence"
    assert event.metadata["execution_class"] == "actual_executed"
    assert "fixture" in event.metadata["evidence_classes"]
    assert event.metadata["live_actions_taken"] is False
    assert client_export.payload["status"] == "needs_evidence"


def test_service_market_projects_into_canonical_promotion_gate_without_authorizing_launch(tmp_path):
    _, event, _ = _assess(tmp_path)

    promotion = event.payload["promotion"]

    assert promotion["requested_stage"] == "launch_draft"
    assert promotion["promoted"] is False
    assert promotion["achievable_stage"] == "candidate"
    assert "exact_sku" in promotion["blockers"]
    assert any(item.startswith("evidence_state_insufficient_for_stage:") for item in promotion["blockers"])


def test_typed_assessment_rejects_forged_workspace_before_composition(tmp_path):
    workspace, registry = _workspace_registry(tmp_path)
    forged = ClientWorkspace(
        workspace_id=workspace.workspace_id,
        name="different workspace",
        workspace_type=workspace.workspace_type,
        created_at=workspace.created_at,
        updated_at=workspace.updated_at,
    )

    with pytest.raises(ValueError, match="workspace identity rejected"):
        _assess(tmp_path, workspace=forged, registry=registry)


def test_typed_assessment_rejects_workspace_registered_with_different_identity(tmp_path):
    workspace, registry = _workspace_registry(tmp_path)
    mismatched_registry = WorkspaceRegistry(str(tmp_path / "mismatched-registry.json"))
    mismatched_registry.register(
        ClientWorkspace(
            workspace_id=workspace.workspace_id,
            name="different workspace",
            workspace_type=workspace.workspace_type,
            created_at=workspace.created_at,
            updated_at=workspace.updated_at,
        )
    )

    with pytest.raises(ValueError, match="workspace identity rejected"):
        _assess(tmp_path, workspace=workspace, registry=mismatched_registry)


def test_goods_remain_on_existing_product_synthesis_path(tmp_path):
    fixture_root = Path(__file__).parent / "fixtures" / "opportunity_synthesis"
    reports = [
        json.loads((fixture_root / name).read_text(encoding="utf-8"))
        for name in (
            "marketplace_trend_report.json",
            "supplier_feasibility_report.json",
            "consumer_attention_report.json",
        )
    ]
    product_report = build_product_opportunity_synthesis(*reports).to_dict()

    assert product_report["candidate_count"] > 0
    with pytest.raises(ValueError, match="service-only"):
        _assess(tmp_path, offering_type="goods")


def test_missing_costs_stay_missing_and_block_economics(tmp_path):
    economics, event, client_export = _assess(tmp_path, delivery_cost=None)

    assert economics is None
    assert "missing_delivery_cost_evidence" in event.payload["blockers"]
    assert "delivery_cost" in event.payload["missing_inputs"]
    assert client_export.payload["status"] == "needs_evidence"
    assert client_export.payload["evidence_required"]


def test_explicit_evidenced_zero_cost_is_not_treated_as_missing(tmp_path):
    economics, event, _ = _assess(tmp_path, tooling_cost=_money("0", "tooling-zero"))

    assert economics is not None
    assert economics.tooling_cost.amount == Decimal("0")
    assert economics.contribution.amount == Decimal("3800")
    assert "missing_tooling_cost_evidence" not in event.payload["blockers"]


def test_mixed_economic_currency_fails_closed(tmp_path):
    with pytest.raises(CurrencyMismatchError):
        _assess(tmp_path, tooling_cost=_money("50", "tooling-usd", currency="USD"))


def test_stale_evidence_and_conflicting_observations_defer(tmp_path):
    stale_ref = _ref("stale-demand", state="stale")
    stale = ServiceMarketObservation(
        "demand", "qualified-requests", Decimal("10"), "requests_per_month", stale_ref
    )
    base_observations = _candidate(tmp_path / "stale")["observations"]
    economics, stale_event, _ = _assess(
        tmp_path / "stale",
        observations=(base_observations[0], stale, base_observations[1]),
    )
    assert economics is not None
    assert "stale_evidence:stale-demand" in stale_event.payload["blockers"]

    stale_cost = _money("1000", "stale-labor", state="stale")
    stale_cost_economics, stale_cost_event, _ = _assess(
        tmp_path / "stale-cost", delivery_cost=stale_cost
    )
    assert stale_cost_economics is None
    assert "missing_delivery_cost_evidence" in stale_cost_event.payload["blockers"]
    assert "stale_evidence:stale-labor" in stale_cost_event.payload["blockers"]

    first = ServiceMarketObservation(
        "demand", "qualified-requests", Decimal("10"), "requests_per_month", _ref("demand-a")
    )
    conflicting = ServiceMarketObservation(
        "demand", "qualified-requests", Decimal("12"), "requests_per_month", _ref("demand-b")
    )
    conflict_economics, conflict_event, _ = _assess(
        tmp_path / "conflict",
        observations=(first, conflicting, _candidate(tmp_path / "conflict")["observations"][1]),
    )
    assert conflict_economics is not None
    assert "conflicting_observation:demand:qualified-requests" in conflict_event.payload["blockers"]


def test_insufficient_capacity_is_explicit(tmp_path):
    economics, event, _ = _assess(tmp_path, capacity_hours=Decimal("10"))

    assert economics is not None
    assert economics.capacity_utilization == Decimal("2")
    assert "insufficient_delivery_capacity" in event.payload["blockers"]
    assert event.payload["capacity_assessment"] == "insufficient"
    assert event.payload["recommendation"] == "defer_for_evidence"


def test_missing_capacity_does_not_erase_observed_cost_economics(tmp_path):
    economics, event, _ = _assess(
        tmp_path,
        capacity_hours=None,
        capacity_evidence=None,
    )

    assert economics is not None
    assert economics.contribution.amount == Decimal("3600")
    assert economics.capacity_hours is None
    assert economics.capacity_utilization is None
    assert event.payload["capacity_assessment"] == "not_assessed"
    assert "missing_capacity_evidence" in event.payload["blockers"]


def test_unknown_market_access_is_never_presumed_cleared(tmp_path):
    _, event, export = _assess(tmp_path, lane=None, market_access_evidence=())

    assert event.payload["market_access_assessment"] == "not_assessed"
    assert "market_access_applicability" in event.payload["unresolved_checks"]
    assert "market_access_applicability_review" in export.payload["evidence_required"]
    assert export.payload["status"] == "needs_evidence"


def test_replay_and_export_are_byte_deterministic(tmp_path):
    first = _assess(tmp_path / "first")
    second = _assess(tmp_path / "second")
    first_economics, first_event, first_export = first
    second_economics, second_event, second_export = second

    assert first_event.canonical_json().encode() == second_event.canonical_json().encode()
    assert first_event.replay_hash() == second_event.replay_hash()
    assert first_economics.to_dict() == second_economics.to_dict()
    assert first_export.fingerprint == second_export.fingerprint
    assert replay_summary([first_event])["sequence_issues"] == []

    repository = InMemoryEventRepository()
    assert repository.append(first_event).appended is True
    duplicate = repository.append(first_event)
    assert duplicate.appended is False
    assert duplicate.idempotent is True


def test_client_export_is_curated_and_event_does_not_retain_raw_references(tmp_path):
    source_ref = EvidenceRef(
        "safe-source-id",
        source_type="manual_import",
        source_url="C:\\private\\supplier-quotes.csv",
        document_ref="supplier-quote-2026.csv",
        evidence_state="fixture",
        captured_at="2026-09-01T00:00:00+00:00",
        valid_until="2026-10-01T00:00:00+00:00",
    )
    observation = ServiceMarketObservation(
        "demand", "qualified-requests", Decimal("10"), "requests_per_month", source_ref
    )
    _, event, export = _assess(
        tmp_path,
        observations=(observation, _candidate(tmp_path)["observations"][1]),
    )
    encoded = event.canonical_json()

    assert "private\\supplier-quotes" not in encoded
    assert "supplier-quote-2026.csv" not in encoded
    assert set(export.payload) <= {
        "workspace_id", "status", "blockers", "evidence_required", "approvals_required", "next_actions"
    }


def test_unsafe_identifier_and_naive_timestamp_are_rejected(tmp_path):
    with pytest.raises(ValueError, match="identifier"):
        _assess(tmp_path, candidate_id="../private")
    with pytest.raises(ValueError, match="timezone-aware"):
        _assess(tmp_path, as_of=datetime(2026, 9, 19))


def test_observation_count_is_bounded(tmp_path):
    observations = _candidate(tmp_path)["observations"]
    with pytest.raises(ValueError, match="observation limit"):
        _assess(tmp_path, observations=observations * 51)


def _input_fixture():
    return json.loads(
        (Path(__file__).parent / "fixtures/service_market_research/service-mxn.json").read_text(encoding="utf-8")
    )


def _input_registry(tmp_path):
    workspace, registry = _workspace_registry(tmp_path)
    return workspace, registry


def _run_input(document, *, registry, evidence_source_mode="fixture"):
    return run_input_document(
        document,
        registry=registry,
        evidence_source_mode=evidence_source_mode,
    )


def test_frozen_input_contract_runs_a_deterministic_manual_fixture_report(tmp_path):
    workspace, registry = _input_registry(tmp_path)
    document = _input_fixture()
    assert document["contract_id"] == INPUT_CONTRACT_ID

    first = _run_input(document, registry=registry)
    second = _run_input(document, registry=registry)

    assert first == second
    assert first["schema"] == "MarketOS.ServiceMarketResearchRun.v1"
    assert first["event"]["payload"]["offering_type"] == "service"
    assert first["event"]["payload"]["market_access_assessment"] == "not_assessed"
    assert first["event"]["payload"]["evidence_classes"] == ["fixture"]
    assert first["event"]["payload"]["economics"]["contribution"]["amount"] == "600"
    assert first["trustos_export"]["workspace_id"] == workspace.workspace_id
    assert first["trustos_export"]["payload"]["status"] == "needs_evidence"
    assert first["replay"]["event_count"] == 1
    assert first["replay"]["canonical_event_replay_hash"] == first["event"]["replay_hash"]
    assert first["execution_class"] == "actual_executed"
    assert first["decision_class"] == "simulated_or_planned"
    assert first["derived_output"] == "derived"
    assert first["safety"]["live_validation"] is False


@pytest.mark.parametrize(
    ("offering_type", "expected_status", "expected_applicability"),
    (
        ("service", "incomplete", "applicable"),
        ("goods", "not_applicable", "not_applicable"),
        ("hybrid", "incomplete", "not_assessed"),
        ("unknown", "incomplete", "not_assessed"),
    ),
)
def test_offering_types_are_explicit_without_product_name_rules(
    tmp_path, offering_type, expected_status, expected_applicability
):
    _, registry = _input_registry(tmp_path)
    document = _input_fixture()
    document["offering_type"] = offering_type

    result = _run_input(document, registry=registry)

    assert result["event"]["payload"]["offering_type"] == offering_type
    assert result["event"]["payload"]["assessment_status"] == expected_status
    assert result["event"]["payload"]["service_economics_applicability"] == expected_applicability
    if offering_type != "service":
        assert result["event"]["payload"]["economics"] is None
    if offering_type == "goods":
        assert result["event"]["aggregate_type"] == "offering_market_candidate"
        assert result["event"]["payload"]["recommendation"] == "route_to_existing_goods_authority"


@pytest.mark.parametrize("country", ("MX", "US", "CA"))
def test_supported_jurisdictions_remain_unassessed_without_compliance_proof(tmp_path, country):
    _, registry = _input_registry(tmp_path)
    document = _input_fixture()
    document["market_lane"]["destination_country"] = country

    result = _run_input(document, registry=registry)
    payload = result["event"]["payload"]
    compliance_gate = next(
        item for item in payload["promotion"]["gates"] if item["gate_id"] == "compliance"
    )

    assert payload["market_lane"]["destination_country"] == country
    assert payload["market_access_assessment"] == "not_assessed"
    assert compliance_gate["satisfied"] is False
    assert result["trustos_export"]["payload"]["status"] == "needs_evidence"


@pytest.mark.parametrize("offering_type", ("service", "goods", "hybrid", "unknown"))
@pytest.mark.parametrize(
    ("captured_at", "valid_until", "expected_blocker"),
    (
        ("2026-09-01T00:00:00+00:00", "2026-09-18T00:00:00+00:00", "stale_evidence:"),
        ("2026-09-20T00:00:00+00:00", "2026-10-01T00:00:00+00:00", "future_dated_evidence:"),
    ),
)
def test_freshness_blocks_consistently_for_every_offering_kind(
    tmp_path, offering_type, captured_at, valid_until, expected_blocker
):
    _, registry = _input_registry(tmp_path)
    document = _input_fixture()
    document["offering_type"] = offering_type
    reference = document["observations"][0]["evidence"]["reference"]
    reference["captured_at"] = captured_at
    reference["valid_until"] = valid_until

    result = _run_input(document, registry=registry)
    payload = result["event"]["payload"]

    assert any(item.startswith(expected_blocker) for item in payload["blockers"])
    assert payload["assessment_status"] == "incomplete"
    assert result["trustos_export"]["payload"]["status"] == "needs_evidence"


@pytest.mark.parametrize("offering_type", ("service", "goods", "hybrid", "unknown"))
def test_malformed_freshness_fails_closed_for_every_offering_kind(tmp_path, offering_type):
    _, registry = _input_registry(tmp_path)
    document = _input_fixture()
    document["offering_type"] = offering_type
    document["observations"][0]["evidence"]["reference"]["captured_at"] = "not-a-timestamp"

    with pytest.raises(ValueError, match="timezone-aware ISO timestamp"):
        _run_input(document, registry=registry)


@pytest.mark.parametrize("offering_type", ("service", "goods", "hybrid", "unknown"))
def test_conflicting_observations_block_every_offering_kind(tmp_path, offering_type):
    _, registry = _input_registry(tmp_path)
    document = _input_fixture()
    document["offering_type"] = offering_type
    duplicate = copy.deepcopy(document["observations"][0])
    duplicate["value"] = "43"
    duplicate["evidence"]["reference"]["evidence_id"] = "ev-demand-conflict"
    duplicate["evidence"]["reference"]["snapshot_hash"] = "9" * 64
    document["observations"].append(duplicate)

    result = _run_input(document, registry=registry)
    payload = result["event"]["payload"]

    assert "conflicting_observation:demand:qualified_requests_monthly" in payload["blockers"]
    assert payload["assessment_status"] == "incomplete"
    assert result["trustos_export"]["payload"]["status"] == "needs_evidence"


def test_evidence_class_comes_from_trusted_source_mode_not_document_claim(tmp_path):
    _, registry = _input_registry(tmp_path)
    document = _input_fixture()
    document["observations"][0]["evidence"]["class"] = "observed"

    result = _run_input(document, registry=registry, evidence_source_mode="manual")
    payload = result["event"]["payload"]
    reference = next(
        item for item in payload["evidence_references"] if item["evidence_id"] == "ev-demand-fixture"
    )

    assert reference["evidence_class"] == "manual"
    assert payload["evidence_classes"] == ["manual"]


def test_default_source_mode_is_unknown_and_cannot_compute_economics(tmp_path):
    _, registry = _input_registry(tmp_path)

    result = run_input_document(_input_fixture(), registry=registry)
    payload = result["event"]["payload"]

    assert payload["economics"] is None
    assert payload["evidence_classes"] == ["unknown"]
    assert any(item.startswith("unknown_evidence_source:") for item in payload["blockers"])
    assert result["trustos_export"]["payload"]["status"] == "needs_evidence"


def test_frozen_input_contract_rejects_missing_and_unknown_fields(tmp_path):
    _, registry = _input_registry(tmp_path)
    missing = _input_fixture()
    del missing["workspace_id"]
    with pytest.raises(ValueError, match="required fields"):
        _run_input(missing, registry=registry)

    unknown = _input_fixture()
    unknown["status"] = "live_validated"
    with pytest.raises(ValueError, match="unexpected fields"):
        _run_input(unknown, registry=registry)


def test_live_validation_claim_and_market_access_claim_stay_unverified(tmp_path):
    _, registry = _input_registry(tmp_path)
    document = _input_fixture()
    document["market_access"]["applicability_claim"] = "live_validated"
    document["economics"]["service_fee"]["evidence"]["class"] = "live_validated"
    document["economics"]["service_fee"]["evidence"]["reference"]["evidence_state_claim"] = "live_validated"

    result = _run_input(document, registry=registry)
    payload = result["event"]["payload"]

    assert payload["market_access_claim"] == service_research._SAFE_PRIVILEGED_CLAIM
    assert payload["market_access_assessment"] == "not_assessed"
    assert payload["economics"] is None
    assert "unverified_privileged_evidence_claim:ev-fee-manual" in payload["blockers"]
    assert "live_validated" not in json.dumps(result)


def test_event_does_not_expose_raw_snapshot_paths_or_provenance(tmp_path):
    document = _input_fixture()
    document["observations"][0]["evidence"]["reference"]["source_url"] = "C:\\private\\customer-notes.json"
    _, registry = _input_registry(tmp_path)

    result = _run_input(document, registry=registry)
    encoded = json.dumps(result, sort_keys=True)

    assert "customer-notes.json" not in encoded
    assert "C:\\private" not in encoded
    assert "locator_sha256" in encoded


def test_typed_boundary_rejects_secret_locators_snapshot_paths_and_raw_provenance(tmp_path):
    unsafe_locator = EvidenceRef(
        "unsafe-locator",
        source_type="manual_import",
        document_ref="sk-" + "live-" + "example-secret-value",
        evidence_state="fixture",
        captured_at="2026-09-01T00:00:00+00:00",
        valid_until="2026-10-01T00:00:00+00:00",
    )
    observation = ServiceMarketObservation(
        "demand", "qualified-requests", Decimal("10"), "requests_per_month", unsafe_locator
    )
    base_observations = _candidate(tmp_path)["observations"]
    with pytest.raises(ValueError, match="secret-shaped"):
        _assess(tmp_path, observations=(observation, base_observations[1]))

    path_hash_ref = EvidenceRef(
        "unsafe-hash",
        source_type="fixture_import",
        evidence_state="fixture",
        captured_at="2026-09-01T00:00:00+00:00",
        valid_until="2026-10-01T00:00:00+00:00",
        snapshot_hash="C:\\private\\snapshot.json",
    )
    path_hash_observation = ServiceMarketObservation(
        "demand", "qualified-requests", Decimal("10"), "requests_per_month", path_hash_ref
    )
    with pytest.raises(ValueError, match="snapshot digest is malformed"):
        _assess(tmp_path, observations=(path_hash_observation, base_observations[1]))

    raw_provenance_money = Money(
        "50",
        "MXN",
        source="fixture_import",
        evidence_ref=_ref("raw-provenance"),
        provenance="C:\\private\\provider-payload.json",
        evidence_state="fixture",
    )
    with pytest.raises(ValueError, match="provenance is not an approved label"):
        _assess(tmp_path, tooling_cost=raw_provenance_money)


def test_serialization_revalidates_mutable_trustos_export(tmp_path, monkeypatch):
    original_export = service_research.export_client_evidence

    def tampered_export(**kwargs):
        result = original_export(**kwargs)
        result.payload["internal_prompt"] = "do not export"
        return result

    monkeypatch.setattr(service_research, "export_client_evidence", tampered_export)
    workspace, registry = _input_registry(tmp_path)

    with pytest.raises(ValueError, match="client evidence export rejected"):
        _run_input(_input_fixture(), registry=registry)


def test_untrusted_privileged_typed_evidence_cannot_compute_economics(tmp_path):
    fee_ref = _ref("ev-verified-claim", state="verified")
    fee = Money(
        "100",
        "MXN",
        source="fixture_import",
        evidence_ref=fee_ref,
        provenance="fixture",
        evidence_state="verified",
    )

    economics, event, _ = _assess(tmp_path, service_fee=fee)

    assert economics is None
    assert any("unverified_privileged_evidence_claim" in item for item in event.payload["blockers"])
    assert '"evidence_state":"verified"' not in event.canonical_json()


def test_typed_claim_maps_reject_untrusted_strings_and_never_emit_privileged_values(tmp_path):
    secret = "sk-" + "live-" + "example-secret-value"
    with pytest.raises(ValueError, match="evidence-state claim map is malformed") as exc_info:
        _assess(tmp_path, evidence_state_claims={"fee": secret})
    assert secret not in str(exc_info.value)

    economics, event, _ = _assess(
        tmp_path,
        evidence_source_mode="fixture",
        evidence_classes={"fee": "live_validated"},
        evidence_state_claims={"fee": "live_validated"},
    )
    encoded = event.canonical_json()

    assert economics is None
    assert "unverified_privileged_evidence_claim:fee" in event.payload["blockers"]
    assert "live_validated" not in encoded
    assert '"state_claim":"unverified_privileged_claim"' in encoded


@pytest.mark.parametrize(
    "evidence_id",
    ("fee", "labor", "tooling", "pass-through", "reserve", "delivery-hours"),
)
def test_stale_typed_state_claim_cannot_override_fresh_financial_reference(tmp_path, evidence_id):
    economics, event, _ = _assess(
        tmp_path,
        evidence_state_claims={evidence_id: "stale"},
    )

    assert economics is None
    assert f"malformed_evidence_state_mismatch:{evidence_id}" in event.payload["blockers"]
    summary = next(
        item for item in event.payload["evidence_references"]
        if item["evidence_id"] == evidence_id
    )
    assert summary["evidence_state"] == "fixture"
    assert summary["state_claim"] == "stale"


def test_typed_unknown_state_and_manual_source_label_do_not_elevate_evidence(tmp_path):
    unknown_manual = EvidenceRef(
        "unknown-manual-source",
        source_type="manual_import",
        evidence_state="unknown",
        captured_at="2026-09-01T00:00:00+00:00",
        valid_until="2026-10-01T00:00:00+00:00",
    )
    base = _candidate(tmp_path)
    observation = ServiceMarketObservation(
        "demand", "qualified-requests", Decimal("10"), "requests_per_month", unknown_manual
    )
    economics, event, _ = _assess(
        tmp_path,
        evidence_source_mode="unknown",
        observations=(observation, base["observations"][1]),
    )
    summary = next(
        item for item in event.payload["evidence_references"]
        if item["evidence_id"] == "unknown-manual-source"
    )

    assert economics is None
    assert summary["evidence_class"] == "unknown"
    assert summary["evidence_state"] == "unknown"
    assert event.payload["evidence_classes"] == ["unknown"]


def test_input_file_loader_rejects_oversize_duplicate_and_deep_json(tmp_path, capsys):
    oversized = tmp_path / "oversized.json"
    oversized.write_text(" " * 70_000, encoding="utf-8")
    with pytest.raises(ValueError, match="input size limit"):
        load_input_document(oversized)

    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text('{"contract_id":"x","contract_id":"y"}', encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate JSON field"):
        load_input_document(duplicate)

    nested_duplicate = tmp_path / "nested-duplicate.json"
    nested_duplicate.write_text('{"outer":{"x":1,"x":2}}', encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate JSON field"):
        load_input_document(nested_duplicate)

    deeply_nested = tmp_path / "deeply-nested.json"
    nested = "[" * 30_000 + "0" + "]" * 30_000
    assert len(nested.encode("utf-8")) < service_research.MAX_INPUT_BYTES
    deeply_nested.write_text(nested, encoding="utf-8")
    with pytest.raises(ValueError, match="input JSON is malformed"):
        load_input_document(deeply_nested)

    exit_code = service_research.main([
        "--input", str(deeply_nested),
        "--workspace-registry", str(tmp_path / "unused-registry.json"),
    ])
    captured = capsys.readouterr()
    assert exit_code == 2
    assert "Traceback" not in captured.err
    assert "RecursionError" not in captured.err


def test_deep_python_input_is_converted_to_a_bounded_contract_error(tmp_path):
    _, registry = _input_registry(tmp_path)
    nested = 0
    for _ in range(30_000):
        nested = [nested]

    with pytest.raises(ValueError, match="not bounded JSON"):
        run_input_document(nested, registry=registry, evidence_source_mode="fixture")


@pytest.mark.parametrize(
    ("path", "blocker", "expect_economics"),
    (
        (("economics", "service_fee"), "missing_service_fee_evidence", False),
        (("economics", "labor_cost"), "missing_delivery_cost_evidence", False),
        (("economics", "pass_through_cost"), "missing_pass_through_cost_evidence", False),
        (("economics", "refund_revision_reserve"), "missing_refund_revision_reserve_evidence", False),
        (("economics", "tooling_cost"), "missing_tooling_cost_evidence", False),
    ),
)
def test_missing_required_cost_evidence_never_becomes_zero_economics(tmp_path, path, blocker, expect_economics):
    _, registry = _input_registry(tmp_path)
    document = _input_fixture()
    document[path[0]][path[1]] = None

    result = _run_input(document, registry=registry)
    payload = result["event"]["payload"]

    assert (payload["economics"] is not None) is expect_economics
    assert blocker in payload["blockers"]
    assert path[1] in payload["missing_inputs"] or path[1] == "labor_cost"


def test_missing_capacity_or_jurisdiction_evidence_stays_not_assessed(tmp_path):
    _, registry = _input_registry(tmp_path)
    document = _input_fixture()
    document["economics"]["capacity_hours"] = None
    document["economics"]["capacity_evidence"] = None
    document["market_lane"]["evidence"] = []

    result = _run_input(document, registry=registry)
    payload = result["event"]["payload"]

    assert payload["capacity_assessment"] == "not_assessed"
    assert payload["economics"] is not None
    assert payload["market_access_assessment"] == "not_assessed"
    assert "missing_capacity_evidence" in payload["blockers"]
    assert "missing_market_lane_evidence" in payload["blockers"]
    assert payload["assessment_status"] == "incomplete"


def test_untrusted_state_and_locator_claims_cannot_upgrade_evidence(tmp_path):
    _, registry = _input_registry(tmp_path)
    document = _input_fixture()
    fee_evidence = document["economics"]["service_fee"]["evidence"]
    fee_evidence["class"] = "live_validated"
    fee_evidence["reference"]["evidence_state_claim"] = "live_validated"

    payload = _run_input(document, registry=registry)["event"]["payload"]

    fee_summary = next(item for item in payload["evidence_references"] if item["evidence_id"] == "ev-fee-manual")
    assert fee_summary["evidence_class"] == "fixture"
    assert fee_summary["evidence_state"] == "unknown"
    assert fee_summary["state_claim"] == service_research._SAFE_PRIVILEGED_CLAIM
    assert payload["economics"] is None
    assert "unverified_privileged_evidence_claim:ev-fee-manual" in payload["blockers"]
    assert "live_validated" not in json.dumps(payload)

    secret = _input_fixture()
    secret["observations"][0]["evidence"]["reference"]["document_ref"] = "sk-" + "live-" + "example-secret-value"
    with pytest.raises(ValueError, match="secret-shaped"):
        _run_input(secret, registry=registry)


def test_not_applicable_claim_is_preserved_but_never_attests_market_access(tmp_path):
    _, registry = _input_registry(tmp_path)
    document = _input_fixture()
    document["market_access"]["applicability_claim"] = "not_applicable"

    result = _run_input(document, registry=registry)
    payload = result["event"]["payload"]

    assert payload["market_access_claim"] == "not_applicable"
    assert payload["market_access_assessment"] == "not_assessed"
    assert "market_access_claim_requires_review:not_applicable" in payload["blockers"]
    assert result["trustos_export"]["payload"]["status"] == "needs_evidence"


def test_cli_emits_deterministic_report_without_writing_outputs(tmp_path):
    workspace, registry = _input_registry(tmp_path)
    input_path = Path(__file__).parent / "fixtures/service_market_research/service-mxn.json"
    before = (tmp_path / "workspace-registry.json").read_bytes()
    command = [
        sys.executable,
        "-m",
        "evaluation.companyos.service_market_research",
        "--input",
        str(input_path),
        "--workspace-registry",
        str(tmp_path / "workspace-registry.json"),
    ]
    first = subprocess.run(command, check=True, capture_output=True, text=True)
    second = subprocess.run(command, check=True, capture_output=True, text=True)

    assert first.stdout == second.stdout
    report = json.loads(first.stdout)
    assert report["event"]["workspace_id"] == workspace.workspace_id
    assert report["evidence_classes"] == ["manual"]
    assert report["safety"]["database_writes"] is False
    assert (tmp_path / "workspace-registry.json").read_bytes() == before
