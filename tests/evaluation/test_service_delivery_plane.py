from __future__ import annotations

from decimal import Decimal

import pytest

from evaluation.companyos.service_delivery_export import (
    project_launch_draft,
    project_managed_acquisition,
    project_product_validation,
    project_unit_economics,
)
from evaluation.companyos.service_delivery_plane import (
    LIFECYCLE,
    ServiceDeliveryError,
    assess_data_quality,
    calculate_service_economics,
    catalog_margins,
    list_priority_packages,
    open_engagement,
    render_client_deliverable,
    resolve_priority_package,
    transition,
    verify_artifact_id,
)


COMPLETE_INTAKE = {
    "orders": 120,
    "revenue": "8400",
    "cac": "18",
    "contribution_margin": "0.35",
    "period_start": "2026-08-01",
    "period_end": "2026-08-31",
    "channel": "paid_social",
    "returns_refunds": "4",
    "ad_spend": "2000",
    "offer_id": "offer-alpha",
    "currency": "USD",
    "roas_before": "1.4",
    "roas_after": "2.1",
    "cac_before": "22",
    "cac_after": "16",
    "evidence_set": ("90-day order extract",),
    "evidence_references": ("ev-orders-001",),
}


def test_priority_packages_reuse_catalog_and_never_fx():
    packages = list_priority_packages()
    assert {item["package_id"] for item in packages} == {
        "product-validation-sprint",
        "unit-economics-diagnostic",
        "launch-draft-pack",
        "managed-acquisition-cro",
    }
    for item in packages:
        assert item["currency"] == "USD"
        assert item["price_evidence_state"] == "planning_assumption"
        assert item["catalog_package_id"]
        assert Decimal(item["price_min"]) <= Decimal(item["price_max"])


def test_unknown_package_and_currency_mismatch_fail_closed():
    with pytest.raises(ServiceDeliveryError):
        resolve_priority_package("secret-second-catalog")
    view = resolve_priority_package("unit-economics-diagnostic")
    with pytest.raises(ServiceDeliveryError, match="FX"):
        calculate_service_economics(view, fee="900", consumed_hours="8", currency="MXN")


def test_data_quality_classifies_and_blocks_optimistic_analysis():
    adequate = assess_data_quality(COMPLETE_INTAKE)
    assert adequate["state"] == "adequate"
    partial = assess_data_quality({**COMPLETE_INTAKE, "cac": None})
    assert partial["state"] == "partial"
    insufficient = assess_data_quality({"offer_id": "x"})
    assert insufficient["state"] == "insufficient"
    stale = assess_data_quality({**COMPLETE_INTAKE, "stale": True})
    assert stale["state"] == "stale"
    blocked = assess_data_quality({**COMPLETE_INTAKE, "currency": "EUR"})
    assert blocked["state"] == "blocked"
    with pytest.raises(ServiceDeliveryError, match="optimistic"):
        transition("evidence_collection", "analysis_in_progress", quality_state="insufficient")


def test_lifecycle_happy_path_and_terminals():
    state = "draft"
    for nxt in (
        "intake_requested",
        "intake_received",
        "data_quality_assessed",
        "evidence_collection",
        "analysis_in_progress",
        "internal_review",
        "client_review",
        "delivered",
        "accepted",
        "renewal_or_upsell",
    ):
        state = transition(state, nxt)
    assert state in LIFECYCLE
    with pytest.raises(ServiceDeliveryError):
        transition("rejected", "delivered")


def test_intake_data_inadequate_never_computes_contribution():
    engagement = open_engagement(
        client_id="client-a",
        workspace_id="ws-client-a",
        package_alias="unit-economics-diagnostic",
        scope="August diagnostic",
        intake={"offer_id": "only"},
        fee="900",
        planned_hours="8",
    )
    assert engagement["delivery_state"] == "data_inadequate"
    assert engagement["contribution"] is None
    with pytest.raises(ServiceDeliveryError, match="inadequate"):
        render_client_deliverable(engagement)


def test_internal_workspace_rejected():
    with pytest.raises(ServiceDeliveryError, match="internal ecommerce"):
        open_engagement(
            client_id="internal-ops",
            workspace_id="internal-core",
            package_alias="product-validation-sprint",
            scope="should fail",
            intake=COMPLETE_INTAKE,
            fee="700",
            planned_hours="8",
        )


def test_contribution_fee_recovery_and_capacity():
    view = resolve_priority_package("unit-economics-diagnostic")
    econ = calculate_service_economics(
        view,
        fee="900",
        consumed_hours="10",
        ad_spend="2000",
        contribution_margin="0.35",
        roas_before="1.4",
        roas_after="2.1",
        cac_before="22",
        cac_after="16",
        capacity_hours="160",
        target_monthly_contribution="4000",
    )
    expected_incremental = (Decimal("2000") * Decimal("0.35") * Decimal("0.7") - Decimal("900")).quantize(
        Decimal("0.01")
    )
    assert econ.incremental_contribution == expected_incremental
    assert econ.orders_required_to_recover_fee == Decimal("150.00")
    assert econ.max_simultaneous_clients == 8
    assert econ.required_clients > 0
    assert econ.client_break_even is False
    assert econ.minimum_acceptable_value is False
    assert econ.evidence_state == "planning_assumption"


def test_secret_shaped_intake_and_revision_path():
    with pytest.raises(ServiceDeliveryError, match="secret"):
        open_engagement(
            client_id="client-a",
            workspace_id="ws-client-a",
            package_alias="launch-draft-pack",
            scope="ghp_abcdefghijklmnopqrstuvwxyz1234",
            intake=COMPLETE_INTAKE,
            fee="1100",
            planned_hours="14",
        )
    assert transition("delivered", "revision_requested") == "revision_requested"
    assert transition("revision_requested", "analysis_in_progress") == "analysis_in_progress"


def test_workspace_isolation_forged_id_and_cross_client():
    a = open_engagement(
        client_id="client-a",
        workspace_id="ws-client-a",
        package_alias="product-validation-sprint",
        scope="SKU review",
        intake=COMPLETE_INTAKE,
        fee="700",
        planned_hours="8",
    )
    b = open_engagement(
        client_id="client-b",
        workspace_id="ws-client-b",
        package_alias="product-validation-sprint",
        scope="SKU review",
        intake=COMPLETE_INTAKE,
        fee="700",
        planned_hours="8",
    )
    assert a["artifact_id"] != b["artifact_id"]
    assert verify_artifact_id(a["workspace_id"], a["engagement_id"], a["service_package"]["package_id"], a["artifact_id"])
    forged = dict(a)
    forged["artifact_id"] = b["artifact_id"]
    with pytest.raises(ServiceDeliveryError, match="forged"):
        render_client_deliverable(forged)
    with pytest.raises(ServiceDeliveryError, match="cross-workspace"):
        render_client_deliverable(a, other_workspace="ws-client-b")


def test_client_safe_projections_are_deterministic_planning_records():
    kwargs = {
        "client_id": "client-a",
        "workspace_id": "ws-client-a",
        "scope": "September pack",
        "intake": COMPLETE_INTAKE,
        "fee": "900",
        "planned_hours": "10",
        "requesting_workspace": "ws-client-a",
    }
    reports = (
        project_product_validation(**kwargs),
        project_unit_economics(**kwargs),
        project_launch_draft(**kwargs),
        project_managed_acquisition(**kwargs),
    )
    for report in reports:
        assert report["schema"] == "MarketOS.ClientServiceDeliverable.v1"
        assert report["record_kind"] == "planning_record"
        assert report["confidence"] == "planning_only"
        assert report["currency"] == "USD"
        assert "prompt" not in str(report).lower()
        assert report["isolation"]["workspace_scoped"] is True
    with pytest.raises(ServiceDeliveryError, match="client A cannot read client B"):
        project_unit_economics(**{**kwargs, "requesting_workspace": "ws-client-b"})


def test_catalog_margins_consume_finance_planner():
    margins = catalog_margins()
    assert margins
    assert {item.package_id for item in margins} >= {
        "product-opportunity-report",
        "finance-planning-dashboard",
        "launch-draft-pack",
        "managed-marketing-cro",
    }


def test_forbidden_keys_stripped_from_export():
    engagement = open_engagement(
        client_id="client-a",
        workspace_id="ws-client-a",
        package_alias="managed-acquisition-cro",
        scope="CRO review",
        intake={**COMPLETE_INTAKE, "internal_prompt": "never export", "heuristic": "hidden"},
        fee="1800",
        planned_hours="24",
    )
    report = render_client_deliverable(engagement)
    blob = str(report).lower()
    assert "never export" not in blob
    assert "hidden" not in blob
