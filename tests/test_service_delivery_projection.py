from __future__ import annotations

import json
from dataclasses import replace
from decimal import Decimal

import pytest

from backend.deliverables.registry import DeliverableRegistry
from backend.economics import EvidenceRef, Money
from backend.workspaces.client_workspace import ClientWorkspace
from evaluation.companyos.service_delivery import (
    REQUIRED_CLIENT_DATA_FIELDS,
    assess_client_data_quality,
    build_client_service_deliverable,
    create_engagement,
    default_service_delivery_packages,
    evaluate_engagement_economics,
    transition_engagement,
)
from evaluation.companyos.service_delivery_artifact import build_service_delivery_artifact
from evaluation.companyos.service_delivery_projection import (
    MAX_PROJECTION_BYTES,
    PROJECTION_REPORT_VERSION,
    build_service_engagement_projection,
    build_service_engagement_row,
)


def packages_by_id():
    return {p.package_id: p for p in default_service_delivery_packages()}


def client_workspace(name="Acme Corp"):
    return ClientWorkspace(name=name, workspace_type="client_service")


def adequate_intake():
    return {name: {"available": True} for name in REQUIRED_CLIENT_DATA_FIELDS}


def _full_row(package_id, *, states=("screening", "eligible", "scoped", "evidence_collection"), data_inadequate=False, client_id="client-1", registry_path="/tmp/never-written-service-delivery-projection-test.json"):
    pkg = packages_by_id()[package_id]
    engagement = create_engagement(client_id=client_id, workspace=client_workspace(), package=pkg, scope="engagement")
    for state in states:
        engagement = transition_engagement(engagement, state)
    dq = assess_client_data_quality({"revenue": {"available": True}} if data_inadequate else adequate_intake())
    refs = (EvidenceRef("ev-1", source_type="order_export", evidence_state="live_readonly", captured_at="2026-09-01"),)
    if engagement.lifecycle_state == "evidence_collection":
        engagement = transition_engagement(engagement, "analysis", evidence_set=refs)
    economics = None
    if not dq.data_inadequate:
        economics = evaluate_engagement_economics(pkg, fee=pkg.price_min_money, ad_spend=Money("2000", pkg.currency), roas_before=Decimal("1.4"), roas_after=Decimal("2.1"), cac_before=Money("22", pkg.currency), cac_after=Money("16", pkg.currency), evidence_refs=refs)
    registry = DeliverableRegistry(path=registry_path)
    deliverable = build_client_service_deliverable(engagement, pkg, economics, dq, recommendation="proceed", registry=registry)
    artifact = build_service_delivery_artifact(engagement, pkg, economics, dq, deliverable, evidence_refs=refs)
    row = build_service_engagement_row(engagement, pkg, dq, economics, artifact)
    return engagement, pkg, dq, economics, row


# ---------------------------------------------------------------------------
# Four priority packages
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("package_id", ("product-validation-sprint", "unit-economics-cac-roas-diagnostic", "launch-draft-pack", "managed-acquisition-cro"))
def test_each_priority_package_produces_a_valid_projection_row(package_id):
    _, pkg, _, _, row = _full_row(package_id, registry_path=f"/tmp/never-written-service-delivery-projection-test-{package_id}.json")
    projection = build_service_engagement_projection([row])
    assert projection["report_version"] == PROJECTION_REPORT_VERSION
    assert projection["engagements"][0]["service_id"] == pkg.package_id
    assert projection["engagements"][0]["package_id"] == pkg.package_id
    assert projection["workspace_id"] == row["workspace_id"]


# ---------------------------------------------------------------------------
# Lifecycle coverage: data_inadequate and cancelled preserved
# ---------------------------------------------------------------------------

def test_data_inadequate_lifecycle_is_preserved_and_blocks_optimistic_output():
    engagement, pkg, dq, economics, row = _full_row("product-validation-sprint", data_inadequate=True, registry_path="/tmp/never-written-service-delivery-projection-test-2.json")
    assert dq.data_inadequate is True
    assert row["eligibility"]["data_inadequate"] is True
    assert row["economics"]["contribution"] is None
    assert row["financial_readiness"]["ready"] is False
    assert row["next_best_action"]["owner"] == "client"


def test_cancelled_lifecycle_state_is_preserved_end_to_end():
    pkg = packages_by_id()["product-validation-sprint"]
    engagement = create_engagement(client_id="client-9", workspace=client_workspace(), package=pkg, scope="x")
    engagement = transition_engagement(engagement, "intake") if engagement.lifecycle_state != "intake" else engagement
    engagement = transition_engagement(engagement, "cancelled") if "cancelled" in _allowed(engagement) else transition_engagement(transition_engagement(engagement, "screening"), "paused")
    dq = assess_client_data_quality(adequate_intake())
    registry = DeliverableRegistry(path="/tmp/never-written-service-delivery-projection-test-3.json")
    deliverable = build_client_service_deliverable(engagement, pkg, None, dq, registry=registry)
    artifact = build_service_delivery_artifact(engagement, pkg, None, dq, deliverable)
    row = build_service_engagement_row(engagement, pkg, dq, None, artifact)
    assert row["lifecycle_state"] in {"cancelled", "paused"}
    assert row["next_best_action"]["owner"] == "blocked"


def _allowed(engagement):
    from evaluation.companyos.service_delivery import _ENGAGEMENT_TRANSITIONS
    return _ENGAGEMENT_TRANSITIONS.get(engagement.lifecycle_state, ())


# ---------------------------------------------------------------------------
# Currency and provenance metadata preserved
# ---------------------------------------------------------------------------

def test_currency_is_preserved_through_the_projection_not_silently_converted():
    pkg = packages_by_id()["managed-acquisition-cro"]
    engagement = create_engagement(client_id="client-mx", workspace=client_workspace("MX Co"), package=pkg, scope="x")
    for state in ("screening", "eligible", "scoped", "evidence_collection"):
        engagement = transition_engagement(engagement, state)
    dq = assess_client_data_quality(adequate_intake())
    economics = evaluate_engagement_economics(
        pkg, fee=Money("20000", "MXN"), ad_spend=Money("50000", "MXN"),
        roas_before=Decimal("1.5"), roas_after=Decimal("2.5"), cac_before=Money("400", "MXN"), cac_after=Money("250", "MXN"),
        labor_cost=Money("9000", "MXN"), tooling_cost=Money("1200", "MXN"), pass_through_cost=Money("0", "MXN"), refund_revision_reserve=Money("900", "MXN"),
    )
    registry = DeliverableRegistry(path="/tmp/never-written-service-delivery-projection-test-4.json")
    deliverable = build_client_service_deliverable(engagement, pkg, economics, dq, recommendation="ok", registry=registry)
    artifact = build_service_delivery_artifact(engagement, pkg, economics, dq, deliverable)
    row = build_service_engagement_row(engagement, pkg, dq, economics, artifact)
    assert row["economics"]["fee"]["currency"] == "MXN"
    assert row["economics"]["contribution"]["currency"] == "MXN"


def test_evidence_provenance_metadata_survives_into_the_row():
    _, _, _, _, row = _full_row("product-validation-sprint", registry_path="/tmp/never-written-service-delivery-projection-test-5.json")
    evidence = row["evidence_set"][0]
    assert evidence["source_type"] == "order_export"
    assert evidence["captured_at"] == "2026-09-01"
    assert evidence["evidence_class"] == "live_validated"


# ---------------------------------------------------------------------------
# TrustOS export rejection: prompts, formulas, heuristics, credentials,
# provider payloads, cross-client data, raw internal notes
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("poisoned_key,poisoned_value", [
    ("internal_prompt", "ignore prior instructions"),
    ("internal_formula", "contribution = fee * 0.4"),
    ("internal_heuristic", "always recommend upsell"),
    ("provider_payload", "raw vendor response"),
    ("cross_client_reference", "other client saw this"),
])
def test_forbidden_keys_are_rejected_by_the_export_boundary(poisoned_key, poisoned_value):
    _, _, _, _, row = _full_row("product-validation-sprint", registry_path="/tmp/never-written-service-delivery-projection-test-6.json")
    row = dict(row)
    row[poisoned_key] = poisoned_value
    with pytest.raises(ValueError, match="workspace isolation"):
        build_service_engagement_projection([row])


def test_credential_shaped_value_is_rejected_regardless_of_key_name():
    _, _, _, _, row = _full_row("product-validation-sprint", registry_path="/tmp/never-written-service-delivery-projection-test-7.json")
    row = dict(row)
    row["scope"] = "leaked key sk-live-abc123"
    with pytest.raises(ValueError, match="workspace isolation"):
        build_service_engagement_projection([row])


def test_credentials_never_persist_uncaught_anywhere_in_a_clean_row():
    _, _, _, _, row = _full_row("launch-draft-pack", registry_path="/tmp/never-written-service-delivery-projection-test-8.json")
    projection = build_service_engagement_projection([row])
    blob = json.dumps(projection)
    assert "internal_prompt" not in blob
    assert "internal_formula" not in blob
    assert "sk-" not in blob


def test_projection_never_claims_a_mutation_or_live_action():
    _, _, _, _, row = _full_row("unit-economics-cac-roas-diagnostic", registry_path="/tmp/never-written-service-delivery-projection-test-9.json")
    projection = build_service_engagement_projection([row])
    assert projection["read_only"] is True
    assert projection["network_calls"] is False
    assert projection["mutated"] is False
    assert row["next_best_action"]["executes_live_action"] is False


# ---------------------------------------------------------------------------
# Deterministic replay
# ---------------------------------------------------------------------------

def test_projection_is_byte_identical_across_independent_builds():
    _, pkg1, dq1, econ1, row1 = _full_row("product-validation-sprint", client_id="client-r", registry_path="/tmp/never-written-service-delivery-projection-test-10.json")
    _, pkg2, dq2, econ2, row2 = _full_row("product-validation-sprint", client_id="client-r", registry_path="/tmp/never-written-service-delivery-projection-test-11.json")
    projection1 = build_service_engagement_projection([row1], generated_at="fixed-t")
    projection2 = build_service_engagement_projection([row2], generated_at="fixed-t")
    assert json.dumps(projection1, sort_keys=True) == json.dumps(projection2, sort_keys=True)


def test_replaying_the_same_row_twice_does_not_duplicate_engagements():
    _, _, _, _, row = _full_row("product-validation-sprint", registry_path="/tmp/never-written-service-delivery-projection-test-12.json")
    with pytest.raises(ValueError, match="duplicate engagement"):
        build_service_engagement_projection([row, row])


def test_projection_rejects_rows_from_multiple_workspaces():
    _, _, _, _, row_a = _full_row("product-validation-sprint", client_id="client-a", registry_path="/tmp/never-written-service-delivery-projection-test-mixed-a.json")
    _, _, _, _, row_b = _full_row("product-validation-sprint", client_id="client-b", registry_path="/tmp/never-written-service-delivery-projection-test-mixed-b.json")
    row_b = {**row_b, "workspace_id": "workspace-other"}
    with pytest.raises(ValueError, match="cannot combine workspaces"):
        build_service_engagement_projection([row_a, row_b])


# ---------------------------------------------------------------------------
# Malformed input
# ---------------------------------------------------------------------------

def test_malformed_row_missing_engagement_id_is_rejected_at_the_producer_boundary():
    with pytest.raises(ValueError, match="complete identity"):
        build_service_engagement_projection([{"workspace_id": "workspace-malformed", "not_an_engagement": True}])


def test_projection_rejects_rows_without_workspace_identity():
    with pytest.raises(ValueError, match="require a workspace identity"):
        build_service_engagement_projection([{"engagement_id": "eng-1"}])


def test_projection_rejects_oversized_serialized_output():
    row = {
        "workspace_id": "workspace-large",
        "engagement_id": "eng-large",
        "client_id": "client-large",
        "package_id": "product-validation-sprint",
        "read_only": True,
        "network_calls": False,
        "mutated": False,
        "scope": "x" * MAX_PROJECTION_BYTES,
    }
    with pytest.raises(ValueError, match="serialized size"):
        build_service_engagement_projection([row])


def test_projection_rejects_nested_identity_mismatch():
    _, _, _, _, row = _full_row("product-validation-sprint", registry_path="/tmp/never-written-service-delivery-projection-test-identity.json")
    mismatched = {**row, "intake": {**row["intake"], "workspace_id": "workspace-other"}}
    with pytest.raises(ValueError, match="mismatched nested identity"):
        build_service_engagement_projection([mismatched])


def test_projection_rejects_unsafe_row_flags():
    _, _, _, _, row = _full_row("product-validation-sprint", registry_path="/tmp/never-written-service-delivery-projection-test-safety.json")
    with pytest.raises(ValueError, match="read-only safety"):
        build_service_engagement_projection([{**row, "network_calls": True}])


def test_projection_rejects_mixed_display_economics_currencies():
    _, _, _, _, row = _full_row("product-validation-sprint", registry_path="/tmp/never-written-service-delivery-projection-test-currency.json")
    economics = {**row["economics"], "contribution": {**row["economics"]["contribution"], "currency": "CAD"}}
    with pytest.raises(ValueError, match="currency mismatch"):
        build_service_engagement_projection([{**row, "economics": economics}])


def test_row_rejects_mismatched_artifact_identity():
    engagement, pkg, dq, economics, row = _full_row("product-validation-sprint", registry_path="/tmp/never-written-service-delivery-projection-test-artifact-identity.json")
    del row
    refs = engagement.evidence_set
    registry = DeliverableRegistry(path="/tmp/never-written-service-delivery-projection-test-artifact-identity-registry.json")
    deliverable = build_client_service_deliverable(engagement, pkg, economics, dq, recommendation="ok", registry=registry)
    artifact = build_service_delivery_artifact(engagement, pkg, economics, dq, deliverable, evidence_refs=refs)
    forged = replace(artifact, workspace_id="workspace-other")
    with pytest.raises(ValueError, match="artifact and engagement identity"):
        build_service_engagement_row(engagement, pkg, dq, economics, forged)


def test_row_rejects_malformed_artifact_identity_or_export_status():
    engagement, pkg, dq, economics, _ = _full_row("product-validation-sprint", registry_path="/tmp/never-written-service-delivery-projection-test-malformed-artifact.json")
    refs = engagement.evidence_set
    registry = DeliverableRegistry(path="/tmp/never-written-service-delivery-projection-test-malformed-artifact-registry.json")
    deliverable = build_client_service_deliverable(engagement, pkg, economics, dq, recommendation="ok", registry=registry)
    artifact = build_service_delivery_artifact(engagement, pkg, economics, dq, deliverable, evidence_refs=refs)

    with pytest.raises(ValueError, match="artifact identity"):
        build_service_engagement_row(engagement, pkg, dq, economics, replace(artifact, artifact_id="artifact-forged"))
    with pytest.raises(ValueError, match="safe for export"):
        build_service_engagement_row(engagement, pkg, dq, economics, replace(artifact, safe_export_status="unsafe"))


def test_empty_projection_is_still_a_valid_safe_envelope():
    projection = build_service_engagement_projection([], availability="unavailable", diagnostics=("no_engagements_available",))
    assert projection["engagements"] == []
    assert projection["diagnostics"] == ["no_engagements_available"]
    assert projection["availability"] == "unavailable"


# ---------------------------------------------------------------------------
# Backward compatibility
# ---------------------------------------------------------------------------

def test_existing_service_delivery_and_artifact_modules_are_unaffected():
    from evaluation.companyos.service_delivery import default_service_delivery_packages as packages_fn
    assert len(packages_fn()) == 4


def test_row_data_quality_state_reflects_the_supplied_assessment_not_a_stale_engagement_default():
    # engagement.data_quality_state only updates when a caller threads it
    # through transition_engagement(..., data_quality_state=...); this row
    # builder must not trust that possibly-stale copy over the
    # ClientDataQualityAssessment it was actually given.
    pkg = packages_by_id()["product-validation-sprint"]
    engagement = create_engagement(client_id="client-dq", workspace=client_workspace(), package=pkg, scope="x")
    for state in ("screening", "eligible", "scoped", "evidence_collection"):
        engagement = transition_engagement(engagement, state)
    assert engagement.data_quality_state == "unavailable"  # never threaded through a transition
    dq = assess_client_data_quality(adequate_intake())
    assert dq.status == "adequate"
    registry = DeliverableRegistry(path="/tmp/never-written-service-delivery-projection-test-13.json")
    economics = evaluate_engagement_economics(pkg, fee=pkg.price_min_money, ad_spend=Money("2000", pkg.currency), roas_before=Decimal("1"), roas_after=Decimal("2"), cac_before=Money("22", pkg.currency), cac_after=Money("16", pkg.currency))
    deliverable = build_client_service_deliverable(engagement, pkg, economics, dq, recommendation="ok", registry=registry)
    artifact = build_service_delivery_artifact(engagement, pkg, economics, dq, deliverable)
    row = build_service_engagement_row(engagement, pkg, dq, economics, artifact)
    assert row["data_quality_state"] == "adequate"


def test_cad_currency_is_preserved_through_the_projection():
    pkg = packages_by_id()["launch-draft-pack"]
    engagement = create_engagement(client_id="client-cad", workspace=client_workspace("CAD Co"), package=pkg, scope="cad scope")
    for state in ("screening", "eligible", "scoped", "evidence_collection"):
        engagement = transition_engagement(engagement, state)
    dq = assess_client_data_quality(adequate_intake())
    economics = evaluate_engagement_economics(
        pkg, fee=Money("15000", "CAD"), ad_spend=Money("35000", "CAD"),
        roas_before=Decimal("1.5"), roas_after=Decimal("2.2"), cac_before=Money("300", "CAD"), cac_after=Money("200", "CAD"),
        labor_cost=Money("6000", "CAD"), tooling_cost=Money("800", "CAD"), pass_through_cost=Money("0", "CAD"), refund_revision_reserve=Money("600", "CAD"),
    )
    registry = DeliverableRegistry(path="/tmp/never-written-cad-test.json")
    deliverable = build_client_service_deliverable(engagement, pkg, economics, dq, recommendation="ok", registry=registry)
    artifact = build_service_delivery_artifact(engagement, pkg, economics, dq, deliverable)
    row = build_service_engagement_row(engagement, pkg, dq, economics, artifact)
    assert row["economics"]["fee"]["currency"] == "CAD"
    assert row["economics"]["contribution"]["currency"] == "CAD"


def test_stale_intake_fields_mark_the_row_stale_without_inventing_amounts():
    pkg = packages_by_id()["product-validation-sprint"]
    engagement = create_engagement(client_id="client-stale", workspace=client_workspace(), package=pkg, scope="stale intake")
    engagement = transition_engagement(engagement, "screening")
    intake = adequate_intake()
    intake["orders"] = {"available": True, "as_of_days_ago": 400}
    dq = assess_client_data_quality(intake, max_age_days=90)
    registry = DeliverableRegistry(path="/tmp/never-written-stale-projection-test.json")
    deliverable = build_client_service_deliverable(engagement, pkg, None, dq, registry=registry)
    artifact = build_service_delivery_artifact(engagement, pkg, None, dq, deliverable)
    row = build_service_engagement_row(engagement, pkg, dq, None, artifact)
    assert row["stale"] is True
    assert row["economics"]["contribution"] is None
    projection = build_service_engagement_projection([row], availability="partial")
    assert projection["availability"] == "partial"
    assert projection["engagements"][0]["economics"]["frontend_calculates"] is False


def test_mixed_currency_raises_mismatch_error_in_kernel():
    from backend.economics import CurrencyMismatchError
    pkg = packages_by_id()["product-validation-sprint"]
    with pytest.raises(CurrencyMismatchError):
        evaluate_engagement_economics(
            pkg,
            fee=Money("5000", "CAD"),
            ad_spend=Money("2000", "USD"),
            roas_before=Decimal("1.5"),
            roas_after=Decimal("2.5"),
            cac_before=Money("20", "CAD"),
            cac_after=Money("15", "CAD"),
        )
