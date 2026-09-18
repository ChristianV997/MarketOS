from __future__ import annotations

import json
from dataclasses import replace as _replace
from decimal import Decimal

import pytest

from backend.deliverables.registry import DeliverableRegistry
from backend.economics import CurrencyMismatchError, EvidenceRef, Money
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
from evaluation.companyos.service_delivery_artifact import (
    ARTIFACT_EVIDENCE_CLASSIFICATIONS,
    build_revision_history,
    build_service_delivery_artifact,
    classify_evidence_ref,
    is_duplicate_replay,
    verify_artifact_id,
)


def packages_by_id():
    return {p.package_id: p for p in default_service_delivery_packages()}


def client_workspace(name="Acme Corp"):
    return ClientWorkspace(name=name, workspace_type="client_service")


def adequate_intake():
    return {name: {"available": True, "as_of_days_ago": 5} for name in REQUIRED_CLIENT_DATA_FIELDS}


def _scoped_engagement(package_id: str, client_id: str = "client-1", workspace_name: str = "Acme Corp"):
    pkg = packages_by_id()[package_id]
    engagement = create_engagement(client_id=client_id, workspace=client_workspace(workspace_name), package=pkg, scope="engagement")
    for state in ("screening", "eligible", "scoped", "evidence_collection"):
        engagement = transition_engagement(engagement, state)
    return engagement, pkg


def _build(package_id, *, data_quality=None, econ_kwargs=None, registry=None, **artifact_kwargs):
    engagement, pkg = _scoped_engagement(package_id)
    dq = data_quality if data_quality is not None else assess_client_data_quality(adequate_intake())
    economics = None
    if not dq.data_inadequate:
        kwargs = dict(fee=pkg.price_min_money, ad_spend=Money("2000", pkg.currency), roas_before=Decimal("1.4"), roas_after=Decimal("2.1"), cac_before=Money("22", pkg.currency), cac_after=Money("16", pkg.currency))
        kwargs.update(econ_kwargs or {})
        economics = evaluate_engagement_economics(pkg, **kwargs)
    reg = registry or DeliverableRegistry(path="/tmp/never-written-service-delivery-artifact-test.json")
    deliverable = build_client_service_deliverable(engagement, pkg, economics, dq, recommendation="proceed", registry=reg)
    artifact = build_service_delivery_artifact(engagement, pkg, economics, dq, deliverable, **artifact_kwargs)
    return engagement, pkg, dq, economics, deliverable, artifact


# ---------------------------------------------------------------------------
# Workspace isolation
# ---------------------------------------------------------------------------

def test_artifact_rejects_mismatched_engagement_and_deliverable_workspace():
    engagement, pkg, dq, economics, deliverable, _ = _build("product-validation-sprint")
    other_engagement, _ = _scoped_engagement("product-validation-sprint", client_id="client-2", workspace_name="Other Co")
    with pytest.raises(ValueError, match="different workspaces"):
        build_service_delivery_artifact(other_engagement, pkg, economics, dq, deliverable)


# ---------------------------------------------------------------------------
# Nested secret rejection
# ---------------------------------------------------------------------------

def test_nested_secret_in_observed_values_is_rejected():
    engagement, pkg = _scoped_engagement("product-validation-sprint")
    dq = assess_client_data_quality(adequate_intake())
    economics = evaluate_engagement_economics(pkg, fee=pkg.price_min_money, ad_spend=Money("2000", pkg.currency), roas_before=Decimal("1"), roas_after=Decimal("2"), cac_before=Money("22", pkg.currency), cac_after=Money("16", pkg.currency))
    deliverable = build_client_service_deliverable(engagement, pkg, economics, dq, recommendation="ok", registry=DeliverableRegistry(path="/tmp/never-written-service-delivery-artifact-test-2.json"))
    with pytest.raises(ValueError, match="secret-shaped"):
        build_service_delivery_artifact(engagement, pkg, economics, dq, deliverable, observed_values={"note": {"nested": "leaked sk-live-nested-1234"}})


# ---------------------------------------------------------------------------
# Forged artifact ID
# ---------------------------------------------------------------------------

def test_forged_artifact_id_is_rejected_by_verification():
    _, _, _, _, _, artifact = _build("product-validation-sprint")
    assert verify_artifact_id(artifact.engagement_id, artifact.package_id, artifact.package_version, artifact.artifact_id) is True
    assert verify_artifact_id(artifact.engagement_id, artifact.package_id, artifact.package_version, "artifact-0000000000000000000000") is False
    assert verify_artifact_id("some-other-engagement", artifact.package_id, artifact.package_version, artifact.artifact_id) is False


# ---------------------------------------------------------------------------
# Identity mutation
# ---------------------------------------------------------------------------

def test_identity_mutated_engagement_is_rejected_before_artifact_is_built():
    engagement, pkg, dq, economics, deliverable, _ = _build("product-validation-sprint")
    forged = _replace(engagement, workspace_id="some-other-clients-workspace")
    with pytest.raises(ValueError, match="forged or tampered"):
        build_service_delivery_artifact(forged, pkg, economics, dq, deliverable)


# ---------------------------------------------------------------------------
# Duplicate replay
# ---------------------------------------------------------------------------

def test_duplicate_replay_detects_identical_content_not_just_identity():
    engagement, pkg, dq, economics, deliverable, artifact_a = _build("product-validation-sprint")
    deliverable_b = build_client_service_deliverable(engagement, pkg, economics, dq, recommendation="proceed", registry=DeliverableRegistry(path="/tmp/never-written-service-delivery-artifact-test-3.json"))
    artifact_b = build_service_delivery_artifact(engagement, pkg, economics, dq, deliverable_b)
    assert is_duplicate_replay(artifact_a, artifact_b) is True

    advanced = transition_engagement(engagement, "analysis")
    deliverable_c = build_client_service_deliverable(advanced, pkg, economics, dq, recommendation="proceed", registry=DeliverableRegistry(path="/tmp/never-written-service-delivery-artifact-test-4.json"))
    artifact_c = build_service_delivery_artifact(advanced, pkg, economics, dq, deliverable_c)
    assert artifact_c.artifact_id == artifact_a.artifact_id  # same engagement+package identity
    assert artifact_c.replay_hash != artifact_a.replay_hash  # different lifecycle state content
    assert is_duplicate_replay(artifact_a, artifact_c) is False


# ---------------------------------------------------------------------------
# Revision ordering
# ---------------------------------------------------------------------------

def test_revision_history_ordering_is_stable_and_faithful_to_transitions():
    engagement, pkg = _scoped_engagement("product-validation-sprint")
    engagement = transition_engagement(engagement, "analysis")
    engagement = transition_engagement(engagement, "draft_ready")
    engagement = transition_engagement(engagement, "client_review")
    engagement = transition_engagement(engagement, "revision_requested")
    history = build_revision_history(engagement)
    assert [item.lifecycle_state for item in history] == list(engagement.history)
    assert [item.index for item in history] == list(range(len(engagement.history)))
    revision_flags = [item.is_revision_cycle for item in history]
    assert revision_flags[-1] is True
    assert sum(revision_flags) == 1


# ---------------------------------------------------------------------------
# data_inadequate blocking / missing evidence
# ---------------------------------------------------------------------------

def test_data_inadequate_engagement_blocks_with_no_optimistic_economics():
    engagement, pkg = _scoped_engagement("unit-economics-cac-roas-diagnostic")
    dq = assess_client_data_quality({"revenue": {"available": True}})
    assert dq.data_inadequate is True
    deliverable = build_client_service_deliverable(engagement, pkg, None, dq, registry=DeliverableRegistry(path="/tmp/never-written-service-delivery-artifact-test-5.json"))
    artifact = build_service_delivery_artifact(engagement, pkg, None, dq, deliverable)
    assert "client_data_inadequate" in artifact.blockers
    assert artifact.contribution_reference is None
    assert artifact.client_value_classification == "unknown"
    assert set(dq.missing_fields) <= set(artifact.missing_evidence)


# ---------------------------------------------------------------------------
# client-value classification
# ---------------------------------------------------------------------------

def test_client_value_classification_flows_into_the_artifact():
    _, _, _, _, _, artifact = _build("managed-acquisition-cro", econ_kwargs={"client_value_created": Money("9000", "USD")})
    assert artifact.client_value_classification in {"attractive", "acceptable", "break_even", "below_break_even", "below_minimum_acceptable", "unknown"}
    assert artifact.client_value_classification == "attractive"


# ---------------------------------------------------------------------------
# Currency mismatch (fail closed, never mixed)
# ---------------------------------------------------------------------------

def test_currency_mismatch_fails_closed_before_an_artifact_can_be_built():
    engagement, pkg = _scoped_engagement("managed-acquisition-cro")
    with pytest.raises(CurrencyMismatchError):
        evaluate_engagement_economics(pkg, fee=Money("20000", "MXN"), ad_spend=Money("10000", "USD"), roas_before=Decimal("1"), roas_after=Decimal("2"), cac_before=Money("40", "USD"), cac_after=Money("25", "USD"))


def test_artifact_currency_is_always_internally_consistent():
    _, _, _, _, _, artifact = _build("launch-draft-pack")
    assert artifact.fee["currency"] == artifact.currency
    assert artifact.tooling_cost["currency"] == artifact.currency
    assert artifact.pass_through_cost["currency"] == artifact.currency


# ---------------------------------------------------------------------------
# Unsupported lifecycle transition
# ---------------------------------------------------------------------------

def test_unsupported_transition_is_rejected_and_artifact_still_reflects_last_valid_state():
    engagement, pkg = _scoped_engagement("product-validation-sprint")
    with pytest.raises(ValueError):
        transition_engagement(engagement, "delivered")
    dq = assess_client_data_quality(adequate_intake())
    economics = evaluate_engagement_economics(pkg, fee=pkg.price_min_money, ad_spend=Money("2000", pkg.currency), roas_before=Decimal("1"), roas_after=Decimal("2"), cac_before=Money("22", pkg.currency), cac_after=Money("16", pkg.currency))
    deliverable = build_client_service_deliverable(engagement, pkg, economics, dq, recommendation="ok", registry=DeliverableRegistry(path="/tmp/never-written-service-delivery-artifact-test-6.json"))
    artifact = build_service_delivery_artifact(engagement, pkg, economics, dq, deliverable)
    assert artifact.lifecycle_state == "evidence_collection"


# ---------------------------------------------------------------------------
# Export redaction
# ---------------------------------------------------------------------------

def test_artifact_export_status_reflects_redaction():
    engagement, pkg = _scoped_engagement("product-validation-sprint")
    dq = assess_client_data_quality(adequate_intake())
    economics = evaluate_engagement_economics(pkg, fee=pkg.price_min_money, ad_spend=Money("2000", pkg.currency), roas_before=Decimal("1"), roas_after=Decimal("2"), cac_before=Money("22", pkg.currency), cac_after=Money("16", pkg.currency))
    leaky_deliverable = build_client_service_deliverable(
        engagement, pkg, economics, dq,
        observed_facts=("leaked Bearer sk-live-artifact-secret-1",), recommendation="ok",
        registry=DeliverableRegistry(path="/tmp/never-written-service-delivery-artifact-test-7.json"),
    )
    artifact = build_service_delivery_artifact(engagement, pkg, economics, dq, leaky_deliverable)
    assert artifact.safe_export_status == "redacted"
    assert "sk-live-artifact-secret-1" not in json.dumps(artifact.to_dict())

    clean_deliverable = build_client_service_deliverable(engagement, pkg, economics, dq, recommendation="ok", registry=DeliverableRegistry(path="/tmp/never-written-service-delivery-artifact-test-8.json"))
    clean_artifact = build_service_delivery_artifact(engagement, pkg, economics, dq, clean_deliverable)
    assert clean_artifact.safe_export_status == "client_safe"


# ---------------------------------------------------------------------------
# Fixture/manual evidence never becomes live proof
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("evidence_state", ("fixture", "simulated", "assumed", "stale", "rejected", "missing", "unknown"))
def test_non_live_evidence_states_never_classify_as_live_validated(evidence_state):
    ref = EvidenceRef("ev-1", source_type="test", evidence_state=evidence_state)
    classification = classify_evidence_ref(ref)
    assert classification != "live_validated"
    assert classification in ARTIFACT_EVIDENCE_CLASSIFICATIONS


def test_supplier_tier_cannot_launder_fixture_evidence_into_live_validated():
    ref = EvidenceRef("ev-1", source_type="supplier_claim", evidence_state="fixture")
    assert classify_evidence_ref(ref, supplier_tier="documented") == "supplier_documented"
    # A supplier tier can only apply to non-live-adjacent base classifications;
    # it can never be used to relabel evidence as live_validated.
    live_ref = EvidenceRef("ev-2", source_type="supplier_claim", evidence_state="live_readonly")
    assert classify_evidence_ref(live_ref, supplier_tier="documented") == "live_validated"


def test_only_genuinely_live_kernel_states_classify_as_live_adjacent():
    assert classify_evidence_ref(EvidenceRef("e", evidence_state="live_readonly")) == "live_validated"
    assert classify_evidence_ref(EvidenceRef("e", evidence_state="verified")) == "sample_verified"


# ---------------------------------------------------------------------------
# Package/version compatibility
# ---------------------------------------------------------------------------

def test_mismatched_package_and_engagement_is_rejected():
    engagement, pkg = _scoped_engagement("product-validation-sprint")
    wrong_pkg = packages_by_id()["launch-draft-pack"]
    dq = assess_client_data_quality(adequate_intake())
    # Build a valid deliverable for the *matching* package, then try to
    # build the artifact against a *different* package -- exercising the
    # artifact function's own identity guard directly, independent of
    # build_client_service_deliverable's separate (and equally real) guard.
    deliverable = build_client_service_deliverable(engagement, pkg, None, dq, registry=DeliverableRegistry(path="/tmp/never-written-service-delivery-artifact-test-9.json"))
    with pytest.raises(ValueError, match="do not match"):
        build_service_delivery_artifact(engagement, wrong_pkg, None, dq, deliverable)


def test_package_version_bump_changes_artifact_identity():
    _, pkg, dq, economics, deliverable, artifact = _build("product-validation-sprint")
    bumped_pkg = _replace(pkg, package_version="v2")
    assert verify_artifact_id(artifact.engagement_id, artifact.package_id, "v2", artifact.artifact_id) is False
    assert verify_artifact_id(artifact.engagement_id, bumped_pkg.package_id, bumped_pkg.package_version, artifact.artifact_id) is False


# ---------------------------------------------------------------------------
# Four service-package examples: draft-ready vs commercially validated,
# and inadequate-client-data blocking, for every priority package.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("package_id", ("product-validation-sprint", "unit-economics-cac-roas-diagnostic", "launch-draft-pack", "managed-acquisition-cro"))
def test_package_example_draft_ready_is_not_commercially_validated(package_id):
    engagement, pkg, dq, economics, deliverable, artifact = _build(
        package_id,
        evidence_refs=(EvidenceRef("ev-fixture-1", source_type="fixture_import", evidence_state="fixture"),),
    )
    assert artifact.evidence_classifications == ("fixture",)
    # A draft built entirely from fixture evidence must never present as
    # commercially/live validated, regardless of how favorable the economics
    # figures happen to look.
    assert "live_validated" not in artifact.evidence_classifications
    assert artifact.data_quality_state in {"adequate", "partial", "stale", "conflicting"}


@pytest.mark.parametrize("package_id", ("product-validation-sprint", "unit-economics-cac-roas-diagnostic", "launch-draft-pack", "managed-acquisition-cro"))
def test_package_example_commercially_validated_uses_live_evidence(package_id):
    _, pkg, dq, economics, deliverable, artifact = _build(
        package_id,
        evidence_refs=(EvidenceRef("ev-live-1", source_type="order_export", evidence_state="live_readonly"),),
    )
    assert artifact.evidence_classifications == ("live_validated",)
    assert artifact.contribution_reference is not None


@pytest.mark.parametrize("package_id", ("product-validation-sprint", "unit-economics-cac-roas-diagnostic", "launch-draft-pack", "managed-acquisition-cro"))
def test_package_example_inadequate_client_data_holds_not_optimistic(package_id):
    engagement, pkg = _scoped_engagement(package_id)
    dq = assess_client_data_quality({"revenue": {"available": True}})
    assert dq.data_inadequate is True
    deliverable = build_client_service_deliverable(engagement, pkg, None, dq, registry=DeliverableRegistry(path=f"/tmp/never-written-service-delivery-artifact-test-example-{package_id}.json"))
    artifact = build_service_delivery_artifact(engagement, pkg, None, dq, deliverable)
    assert artifact.data_quality_state in {"partial", "insufficient", "unavailable"}
    assert artifact.contribution_reference is None
    assert "client_data_inadequate" in artifact.blockers
    assert artifact.next_human_action  # a real next action is always present, even when blocked


# ---------------------------------------------------------------------------
# Backward compatibility
# ---------------------------------------------------------------------------

def test_artifact_module_does_not_alter_existing_service_delivery_behavior():
    from evaluation.companyos.service_delivery import default_service_delivery_packages as packages_fn
    packages = packages_fn()
    assert len(packages) == 4
    assert all(isinstance(p.package_version, str) for p in packages)


def test_deterministic_report_rendering_is_stable_across_independent_builds():
    _, pkg, dq, economics, _, artifact_a = _build("product-validation-sprint")
    engagement, pkg2 = _scoped_engagement("product-validation-sprint")
    dq2 = assess_client_data_quality(adequate_intake())
    econ2 = evaluate_engagement_economics(pkg2, fee=pkg2.price_min_money, ad_spend=Money("2000", pkg2.currency), roas_before=Decimal("1.4"), roas_after=Decimal("2.1"), cac_before=Money("22", pkg2.currency), cac_after=Money("16", pkg2.currency))
    deliverable_b = build_client_service_deliverable(engagement, pkg2, econ2, dq2, recommendation="proceed", registry=DeliverableRegistry(path="/tmp/never-written-service-delivery-artifact-test-10.json"))
    artifact_b = build_service_delivery_artifact(engagement, pkg2, econ2, dq2, deliverable_b)
    assert json.dumps(artifact_a.to_dict(), sort_keys=True) == json.dumps(artifact_b.to_dict(), sort_keys=True)
