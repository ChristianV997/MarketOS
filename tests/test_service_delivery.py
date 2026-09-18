from __future__ import annotations

import json
from decimal import Decimal

import pytest

from backend.deliverables.registry import DeliverableRegistry
from backend.economics import CurrencyMismatchError, Money, canonical_json
from backend.workspaces.client_workspace import ClientWorkspace
from evaluation.companyos.service_delivery import (
    CANONICAL_SERVICE_PACKAGE_IDS,
    CLIENT_DATA_QUALITY_STATES,
    REQUIRED_CLIENT_DATA_FIELDS,
    assess_client_data_quality,
    build_client_service_deliverable,
    build_service_delivery_plane_report,
    classify_client_value,
    create_engagement,
    default_service_delivery_packages,
    evaluate_engagement_economics,
    get_client_engagement_for_workspace,
    list_client_deliverables_for_workspace,
    new_engagement_id,
    transition_engagement,
)


def packages_by_id():
    return {p.package_id: p for p in default_service_delivery_packages()}


def client_workspace(name="Acme Corp"):
    return ClientWorkspace(name=name, workspace_type="client_service")


def adequate_intake():
    return {name: {"available": True, "as_of_days_ago": 5} for name in REQUIRED_CLIENT_DATA_FIELDS}


# ---------------------------------------------------------------------------
# A. Service package schema
# ---------------------------------------------------------------------------

def test_four_canonical_packages_are_represented_with_required_fields():
    packages = default_service_delivery_packages()
    assert {p.package_id for p in packages} == set(CANONICAL_SERVICE_PACKAGE_IDS)
    for package in packages:
        d = package.to_dict()
        for key in (
            "package_id", "name", "description", "currency", "price_min", "price_max", "billing_model",
            "estimated_delivery_hours", "estimated_labor_cost", "tooling_cost", "optional_pass_through_cost",
            "refund_revision_reserve", "required_client_inputs", "client_eligibility", "deliverables",
            "acceptance_criteria", "expected_outcome", "scope_exclusions", "next_step_relationship",
            "price_evidence_state", "price_evidence_classification",
        ):
            assert key in d, key
        assert d["description"]
        assert d["expected_outcome"]
        assert d["client_eligibility"]
        assert d["price_evidence_classification"] in {"planning_assumption", "validated_price"}


def test_package_report_is_client_safe_and_deterministic():
    a = build_service_delivery_plane_report().to_dict()
    b = build_service_delivery_plane_report().to_dict()
    assert canonical_json(a) == canonical_json(b)
    assert a["read_only"] and not a["network_calls"] and not a["mutated"]


def test_no_second_service_catalog_is_created_packages_delegate_to_canonical_catalog():
    from evaluation.companyos.service_catalog import default_service_catalog, package_map
    catalog = package_map(default_service_catalog())
    for package in default_service_delivery_packages():
        assert package.package == catalog[package.package_id]
        assert package.price_min_money == catalog[package.package_id].price_min_money


# ---------------------------------------------------------------------------
# USD/MXN/CAD separation and price planning assumptions
# ---------------------------------------------------------------------------

def test_currencies_are_never_silently_converted_across_usd_mxn():
    pkg = packages_by_id()["managed-acquisition-cro"]
    with pytest.raises(CurrencyMismatchError):
        evaluate_engagement_economics(
            pkg, fee=Money("20000", "MXN"), ad_spend=Money("10000", "USD"),
            roas_before=Decimal("1"), roas_after=Decimal("2"),
            cac_before=Money("40", "USD"), cac_after=Money("25", "USD"),
        )


def test_currencies_are_never_silently_converted_package_defaults_vs_foreign_fee():
    pkg = packages_by_id()["managed-acquisition-cro"]
    with pytest.raises(CurrencyMismatchError):
        evaluate_engagement_economics(
            pkg, fee=Money("20000", "MXN"), ad_spend=Money("10000", "MXN"),
            roas_before=Decimal("1"), roas_after=Decimal("2"),
            cac_before=Money("400", "MXN"), cac_after=Money("250", "MXN"),
        )


def test_full_mxn_engagement_with_explicit_overrides_computes_without_conversion():
    pkg = packages_by_id()["managed-acquisition-cro"]
    economics = evaluate_engagement_economics(
        pkg, fee=Money("20000", "MXN"), ad_spend=Money("50000", "MXN"),
        roas_before=Decimal("1.5"), roas_after=Decimal("2.5"),
        cac_before=Money("400", "MXN"), cac_after=Money("250", "MXN"),
        labor_cost=Money("9000", "MXN"), tooling_cost=Money("1200", "MXN"),
        pass_through_cost=Money("0", "MXN"), refund_revision_reserve=Money("900", "MXN"),
    )
    assert economics.contribution.currency == "MXN"
    assert economics.service_fee.currency == "MXN"


def test_full_cad_engagement_computes_independently_of_usd_defaults():
    pkg = packages_by_id()["launch-draft-pack"]
    economics = evaluate_engagement_economics(
        pkg, fee=Money("1800", "CAD"), ad_spend=Money("4000", "CAD"),
        roas_before=Decimal("1"), roas_after=Decimal("1.8"),
        cac_before=Money("50", "CAD"), cac_after=Money("35", "CAD"),
        labor_cost=Money("700", "CAD"), tooling_cost=Money("80", "CAD"),
        pass_through_cost=Money("60", "CAD"), refund_revision_reserve=Money("70", "CAD"),
    )
    assert economics.contribution.currency == "CAD"


def test_price_is_classified_as_planning_assumption_not_a_hidden_validated_price():
    for package in default_service_delivery_packages():
        assert package.price_evidence_classification == "planning_assumption"
        assert package.pricing_evidence_state == "assumed"


# ---------------------------------------------------------------------------
# B. Client intake / engagement lifecycle
# ---------------------------------------------------------------------------

def test_engagement_lifecycle_starts_in_draft_and_advances_forward_only():
    pkg = packages_by_id()["product-validation-sprint"]
    engagement = create_engagement(client_id="client-1", workspace=client_workspace(), package=pkg, scope="widget candidate")
    assert engagement.lifecycle_state == "draft"
    engagement = transition_engagement(engagement, "intake_requested")
    engagement = transition_engagement(engagement, "intake_received")
    assert engagement.history == ("draft", "intake_requested", "intake_received")


def test_invalid_engagement_transition_is_rejected():
    pkg = packages_by_id()["product-validation-sprint"]
    engagement = create_engagement(client_id="client-1", workspace=client_workspace(), package=pkg, scope="x")
    with pytest.raises(ValueError):
        transition_engagement(engagement, "delivered")


def test_engagement_can_be_blocked_and_resumed():
    pkg = packages_by_id()["product-validation-sprint"]
    engagement = create_engagement(client_id="client-1", workspace=client_workspace(), package=pkg, scope="x")
    engagement = transition_engagement(engagement, "intake_requested")
    engagement = transition_engagement(engagement, "blocked")
    engagement = transition_engagement(engagement, "intake_received")
    assert engagement.lifecycle_state == "intake_received"


def test_engagement_requires_client_service_workspace():
    pkg = packages_by_id()["product-validation-sprint"]
    internal_ws = ClientWorkspace(name="Internal", workspace_type="internal")
    with pytest.raises(ValueError):
        create_engagement(client_id="client-1", workspace=internal_ws, package=pkg, scope="x")


def test_engagement_id_is_deterministic_and_workspace_scoped():
    a = new_engagement_id("client-1", "ws-1", "product-validation-sprint", "t1")
    b = new_engagement_id("client-1", "ws-1", "product-validation-sprint", "t1")
    c = new_engagement_id("client-1", "ws-2", "product-validation-sprint", "t1")
    assert a == b
    assert a != c


# ---------------------------------------------------------------------------
# C. Insufficient client data / data-quality gate
# ---------------------------------------------------------------------------

def test_client_lacking_reliable_business_data_is_marked_data_inadequate():
    assessment = assess_client_data_quality({"orders": {"available": True, "as_of_days_ago": 5}})
    assert assessment.data_inadequate is True
    assert set(REQUIRED_CLIENT_DATA_FIELDS) - {"orders"} == set(assessment.missing_fields)


def test_no_intake_at_all_is_unavailable_and_data_inadequate():
    assessment = assess_client_data_quality(None)
    assert assessment.status == "unavailable"
    assert assessment.data_inadequate is True


def test_stale_data_is_flagged_and_data_inadequate():
    intake = adequate_intake()
    intake["orders"] = {"available": True, "as_of_days_ago": 400}
    assessment = assess_client_data_quality(intake, max_age_days=90)
    assert "orders" in assessment.stale_fields
    assert assessment.data_inadequate is True


def test_conflicting_data_is_flagged_and_data_inadequate():
    intake = adequate_intake()
    intake["revenue"] = {"available": True, "as_of_days_ago": 5, "conflicting": True}
    assessment = assess_client_data_quality(intake)
    assert "revenue" in assessment.conflicting_fields
    assert assessment.data_inadequate is True


def test_adequate_data_is_not_data_inadequate():
    assessment = assess_client_data_quality(adequate_intake())
    assert assessment.status == "adequate"
    assert assessment.data_inadequate is False


def test_all_data_quality_states_are_from_the_canonical_set():
    for status in ("adequate", "partial", "stale", "conflicting", "insufficient", "blocked", "unavailable"):
        assert status in CLIENT_DATA_QUALITY_STATES


def test_data_inadequate_client_never_receives_an_optimistic_diagnostic():
    pkg = packages_by_id()["managed-acquisition-cro"]
    engagement = create_engagement(client_id="client-2", workspace=client_workspace("Thin Data Co"), package=pkg, scope="x")
    dq = assess_client_data_quality({"orders": {"available": True}})
    registry = DeliverableRegistry(path="/tmp/never-written-service-delivery-test.json")
    deliverable = build_client_service_deliverable(engagement, pkg, economics=None, data_quality=dq, registry=registry)
    assert deliverable.status == "blocked"
    assert deliverable.sections[0].metadata["derived_values"] == {}
    assert "revenue" in deliverable.missing_evidence


# ---------------------------------------------------------------------------
# D. Service contribution, capacity, fee recovery, client value
# ---------------------------------------------------------------------------

def test_incremental_contribution_matches_the_documented_formula():
    pkg = packages_by_id()["managed-acquisition-cro"]
    economics = evaluate_engagement_economics(
        pkg, fee=Money("1500", "USD"), ad_spend=Money("10000", "USD"),
        roas_before=Decimal("2"), roas_after=Decimal("3"),
        cac_before=Money("40", "USD"), cac_after=Money("25", "USD"),
    )
    margin = Decimal(str(pkg.package.gross_margin_estimate))
    expected = Decimal("10000") * margin * (Decimal("3") - Decimal("2")) - Decimal("1500")
    assert economics.incremental_contribution.amount == expected


def test_orders_required_to_recover_fee_matches_the_documented_formula():
    pkg = packages_by_id()["managed-acquisition-cro"]
    economics = evaluate_engagement_economics(
        pkg, fee=Money("1500", "USD"), ad_spend=Money("10000", "USD"),
        roas_before=Decimal("2"), roas_after=Decimal("3"),
        cac_before=Money("40", "USD"), cac_after=Money("25", "USD"),
    )
    assert economics.orders_required_to_recover_fee == Decimal("1500") / (Decimal("40") - Decimal("25"))


def test_capacity_and_maximum_simultaneous_clients_are_computed():
    pkg = packages_by_id()["unit-economics-cac-roas-diagnostic"]
    economics = evaluate_engagement_economics(
        pkg, fee=Money("1500", "USD"), ad_spend=Money("1000", "USD"),
        roas_before=Decimal("1"), roas_after=Decimal("1"),
        cac_before=Money("20", "USD"), cac_after=Money("20", "USD"),
        delivery_hours=Decimal("20"), capacity_hours=Decimal("160"),
    )
    assert economics.capacity_utilization == Decimal("20") / Decimal("160")
    assert economics.maximum_simultaneous_clients == Decimal("160") / Decimal("20")


def test_required_client_count_for_target_monthly_contribution():
    pkg = packages_by_id()["unit-economics-cac-roas-diagnostic"]
    economics = evaluate_engagement_economics(
        pkg, fee=Money("1500", "USD"), ad_spend=Money("1000", "USD"),
        roas_before=Decimal("1"), roas_after=Decimal("1"),
        cac_before=Money("20", "USD"), cac_after=Money("20", "USD"),
        target_monthly_contribution=Money("10000", "USD"),
    )
    assert economics.required_clients_for_target_monthly_contribution is not None
    assert economics.required_clients_for_target_monthly_contribution > Decimal("0")


def test_client_value_classification_distinguishes_break_even_from_attractive():
    pkg = packages_by_id()["managed-acquisition-cro"]
    break_even = evaluate_engagement_economics(
        pkg, fee=Money("1000", "USD"), ad_spend=Money("1000", "USD"),
        roas_before=Decimal("1"), roas_after=Decimal("1"), cac_before=Money("1", "USD"), cac_after=Money("1", "USD"),
        client_value_created=Money("1000", "USD"),
    )
    attractive = evaluate_engagement_economics(
        pkg, fee=Money("1000", "USD"), ad_spend=Money("1000", "USD"),
        roas_before=Decimal("1"), roas_after=Decimal("1"), cac_before=Money("1", "USD"), cac_after=Money("1", "USD"),
        client_value_created=Money("5000", "USD"),
    )
    below = evaluate_engagement_economics(
        pkg, fee=Money("1000", "USD"), ad_spend=Money("1000", "USD"),
        roas_before=Decimal("1"), roas_after=Decimal("1"), cac_before=Money("1", "USD"), cac_after=Money("1", "USD"),
        client_value_created=Money("200", "USD"),
    )
    assert classify_client_value(break_even) == "break_even"
    assert classify_client_value(attractive) == "attractive"
    assert classify_client_value(below) == "below_break_even"


def test_minimum_acceptable_value_multiple_is_distinguished_from_attractive():
    pkg = packages_by_id()["managed-acquisition-cro"]
    economics = evaluate_engagement_economics(
        pkg, fee=Money("1000", "USD"), ad_spend=Money("1000", "USD"),
        roas_before=Decimal("1"), roas_after=Decimal("1"), cac_before=Money("1", "USD"), cac_after=Money("1", "USD"),
        client_value_created=Money("1500", "USD"), minimum_acceptable_value_multiple=Decimal("1.2"),
    )
    assert classify_client_value(economics) == "acceptable"


# ---------------------------------------------------------------------------
# Deliverable acceptance / revision state
# ---------------------------------------------------------------------------

def test_completed_deliverable_supports_the_full_delivered_accepted_path():
    pkg = packages_by_id()["product-validation-sprint"]
    engagement = create_engagement(client_id="client-3", workspace=client_workspace("Bright Co"), package=pkg, scope="widget")
    for state in ("intake_requested", "intake_received", "data_quality_assessed", "evidence_collection", "analysis_in_progress", "internal_review", "client_review", "delivered", "accepted"):
        engagement = transition_engagement(engagement, state)
    assert engagement.lifecycle_state == "accepted"


def test_revision_requested_returns_to_analysis_not_forward_to_delivered():
    pkg = packages_by_id()["product-validation-sprint"]
    engagement = create_engagement(client_id="client-3", workspace=client_workspace("Bright Co"), package=pkg, scope="widget")
    for state in ("intake_requested", "intake_received", "data_quality_assessed", "evidence_collection", "analysis_in_progress", "internal_review", "client_review", "delivered", "revision_requested"):
        engagement = transition_engagement(engagement, state)
    assert engagement.lifecycle_state == "revision_requested"
    with pytest.raises(ValueError):
        transition_engagement(engagement, "accepted")
    engagement = transition_engagement(engagement, "analysis_in_progress")
    assert engagement.lifecycle_state == "analysis_in_progress"


# ---------------------------------------------------------------------------
# F. Workspace isolation and safe export
# ---------------------------------------------------------------------------

def test_one_client_cannot_read_another_clients_engagement():
    pkg = packages_by_id()["product-validation-sprint"]
    engagement_a = create_engagement(client_id="client-a", workspace=client_workspace("A Co"), package=pkg, scope="x")
    registry = {engagement_a.engagement_id: engagement_a}
    assert get_client_engagement_for_workspace(registry, workspace_id=engagement_a.workspace_id, engagement_id=engagement_a.engagement_id) is not None
    assert get_client_engagement_for_workspace(registry, workspace_id="some-other-clients-workspace", engagement_id=engagement_a.engagement_id) is None


def test_report_exports_are_workspace_scoped_no_cross_client_leakage():
    pkg = packages_by_id()["product-validation-sprint"]
    dq = assess_client_data_quality(adequate_intake())
    registry = DeliverableRegistry(path="/tmp/never-written-service-delivery-test-2.json")

    engagement_a = create_engagement(client_id="client-a", workspace=client_workspace("Company A"), package=pkg, scope="x")
    econ_a = evaluate_engagement_economics(pkg, fee=Money("750", "USD"), ad_spend=Money("1000", "USD"), roas_before=Decimal("1"), roas_after=Decimal("2"), cac_before=Money("10", "USD"), cac_after=Money("8", "USD"))
    build_client_service_deliverable(engagement_a, pkg, econ_a, dq, recommendation="A", registry=registry)

    engagement_b = create_engagement(client_id="client-b", workspace=client_workspace("Company B"), package=pkg, scope="y")
    econ_b = evaluate_engagement_economics(pkg, fee=Money("750", "USD"), ad_spend=Money("1000", "USD"), roas_before=Decimal("1"), roas_after=Decimal("2"), cac_before=Money("10", "USD"), cac_after=Money("8", "USD"))
    build_client_service_deliverable(engagement_b, pkg, econ_b, dq, recommendation="B", registry=registry)

    a_view = list_client_deliverables_for_workspace(registry, workspace_id=engagement_a.workspace_id)
    b_view = list_client_deliverables_for_workspace(registry, workspace_id=engagement_b.workspace_id)
    assert len(a_view) == 1 and a_view[0].metadata["client_id"] == "client-a"
    assert len(b_view) == 1 and b_view[0].metadata["client_id"] == "client-b"
    assert a_view[0].package_id != b_view[0].package_id


def test_artifact_ids_cannot_be_forged_across_clients():
    pkg = packages_by_id()["product-validation-sprint"]
    ws_a = client_workspace("Company A")
    ws_b = client_workspace("Company B")
    engagement_a = create_engagement(client_id="client-a", workspace=ws_a, package=pkg, scope="x", created_at="t1")
    engagement_b = create_engagement(client_id="client-b", workspace=ws_b, package=pkg, scope="x", created_at="t1")
    assert engagement_a.engagement_id != engagement_b.engagement_id


def test_client_safe_deliverable_never_includes_internal_or_credential_fields():
    pkg = packages_by_id()["product-validation-sprint"]
    engagement = create_engagement(client_id="client-safe", workspace=client_workspace("Safe Co"), package=pkg, scope="x")
    dq = assess_client_data_quality(adequate_intake())
    econ = evaluate_engagement_economics(pkg, fee=Money("750", "USD"), ad_spend=Money("1000", "USD"), roas_before=Decimal("1"), roas_after=Decimal("2"), cac_before=Money("10", "USD"), cac_after=Money("8", "USD"))
    registry = DeliverableRegistry(path="/tmp/never-written-service-delivery-test-3.json")
    deliverable = build_client_service_deliverable(
        engagement, pkg, econ, dq,
        observed_facts=("leaked Bearer sk-internal-secret-42", "unrelated client note: other_client order #123"),
        recommendation="ok", registry=registry,
    )
    blob = json.dumps(deliverable.to_dict())
    assert "sk-internal-secret-42" not in blob
    assert "other_client" not in blob
    assert deliverable.metadata["leakage_findings"] >= 1


def test_service_reports_remain_offline_planning_records():
    package_report = build_service_delivery_plane_report().to_dict()
    assert package_report["network_calls"] is False and package_report["mutated"] is False
    pkg = packages_by_id()["product-validation-sprint"]
    engagement = create_engagement(client_id="client-x", workspace=client_workspace(), package=pkg, scope="x")
    assert engagement.network_calls is False and engagement.mutated is False and engagement.read_only is True


def test_deterministic_report_rendering_is_stable_across_calls():
    pkg = packages_by_id()["product-validation-sprint"]
    engagement = create_engagement(client_id="client-y", workspace=client_workspace("Stable Co"), package=pkg, scope="x", created_at="fixed-t")
    dq = assess_client_data_quality(adequate_intake())
    econ = evaluate_engagement_economics(pkg, fee=Money("750", "USD"), ad_spend=Money("1000", "USD"), roas_before=Decimal("1"), roas_after=Decimal("2"), cac_before=Money("10", "USD"), cac_after=Money("8", "USD"))
    registry_1 = DeliverableRegistry(path="/tmp/never-written-service-delivery-test-4.json")
    registry_2 = DeliverableRegistry(path="/tmp/never-written-service-delivery-test-5.json")
    d1 = build_client_service_deliverable(engagement, pkg, econ, dq, recommendation="ok", generated_at="fixed-t", registry=registry_1)
    d2 = build_client_service_deliverable(engagement, pkg, econ, dq, recommendation="ok", generated_at="fixed-t", registry=registry_2)
    assert d1.package_id == d2.package_id
    assert canonical_json(d1.sections[0].metadata) == canonical_json(d2.sections[0].metadata)


# ---------------------------------------------------------------------------
# Backward compatibility
# ---------------------------------------------------------------------------

def test_existing_service_catalog_module_is_untouched_and_still_importable():
    from evaluation.companyos.service_catalog import default_service_catalog, package_map
    packages = default_service_catalog()
    assert len(packages) == 11
    mapped = package_map(packages)
    assert mapped["product-validation-sprint"] is mapped["product-opportunity-report"]


def test_existing_service_catalog_economics_helper_is_unaffected():
    from evaluation.companyos.service_catalog import default_service_catalog, service_package_economics
    package = next(item for item in default_service_catalog() if item.package_id == "launch-draft-pack")
    result = service_package_economics(
        package, price=Money("1000", "USD"), ad_spend=Money("5000", "USD"),
        roas_before=Decimal("1"), roas_after=Decimal("2"), cac_before=Money("30", "USD"), cac_after=Money("20", "USD"),
        capacity_hours=Decimal("40"),
    )
    assert result.incremental_contribution.amount == Decimal("2900.00")
