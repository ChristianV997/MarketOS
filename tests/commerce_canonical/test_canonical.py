from backend.economics.kernel import EvidenceRef

from evaluation.commerce.canonical import (
    BusinessModel,
    CommercialOwnership,
    CompetitionSnapshot,
    OwnershipAssignment,
    ServiceEngagement,
    WorkspaceReplayContext,
    launch_blockers_for_ownership,
)


def test_ownership_assignment_rejects_unknown_role():
    try:
        OwnershipAssignment("not_a_real_role", "Someone")
    except ValueError as exc:
        assert "unknown ownership role" in str(exc)
    else:
        raise AssertionError("expected ValueError for unknown role")


def test_unknown_ownership_is_unknown_everywhere():
    ownership = CommercialOwnership.unknown()
    assert ownership.unknown_roles == (
        "merchant_of_record",
        "fulfillment_owner",
        "warranty_owner",
        "return_owner",
        "support_owner",
        "payment_collection_owner",
    )
    assert not ownership.fully_known
    assert launch_blockers_for_ownership(ownership) == (
        "unknown_fulfillment_owner",
        "unknown_merchant_of_record",
        "unknown_payment_collection_owner",
        "unknown_return_owner",
        "unknown_support_owner",
        "unknown_warranty_owner",
    )


def test_known_ownership_has_no_blockers():
    known = CommercialOwnership(
        merchant_of_record=OwnershipAssignment("merchant_of_record", "Acme"),
        fulfillment_owner=OwnershipAssignment("fulfillment_owner", "Acme 3PL"),
        warranty_owner=OwnershipAssignment("warranty_owner", "Supplier"),
        return_owner=OwnershipAssignment("return_owner", "Acme"),
        support_owner=OwnershipAssignment("support_owner", "Acme"),
        payment_collection_owner=OwnershipAssignment("payment_collection_owner", "Acme"),
    )
    assert known.fully_known
    assert launch_blockers_for_ownership(known) == ()


def test_competition_snapshot_flags_dominance_and_saturation():
    dominated = CompetitionSnapshot(
        candidate_id="c1", lane_id="lane-1", observed_offer_count=300,
        saturation_score=0.9, dominant_retailer="BigCo", dominant_retailer_share=0.7,
    )
    assert dominated.retailer_dominance_risk
    assert dominated.oversaturated

    healthy = CompetitionSnapshot(
        candidate_id="c2", lane_id="lane-1", observed_offer_count=10,
        saturation_score=0.2, dominant_retailer_share=0.1,
    )
    assert not healthy.retailer_dominance_risk
    assert not healthy.oversaturated


def test_service_engagement_reports_data_inadequate_status():
    engagement = ServiceEngagement(
        engagement_id="eng-1", package_id="pkg-1", client_name="Client",
        stage="proposed", economics=None, data_adequate=False, reasons=("missing_ad_spend",),
        context=WorkspaceReplayContext(workspace_id="ws-1", replay_id="run-1"),
    )
    data = engagement.to_dict()
    assert data["status"] == "data_inadequate"
    assert data["reasons"] == ["missing_ad_spend"]
    assert data["context"] == {"workspace_id": "ws-1", "replay_id": "run-1"}


def test_business_model_enum_is_closed():
    assert {item.value for item in BusinessModel} == {
        "retail_margin", "commission", "affiliate", "lead_generation",
    }


def test_evidence_reference_is_the_kernel_evidence_ref():
    # EvidenceReference must be an alias, not a second competing schema.
    from evaluation.commerce.canonical import EvidenceReference
    assert EvidenceReference is EvidenceRef
    ref = EvidenceReference("ev-1", evidence_state="observed")
    assert isinstance(ref, EvidenceRef)
