import pytest
from services.consulting_delivery.package import ConsultingDeliveryPackage, build_consulting_delivery
from backend.deliverables.package import DeliverableSection

def test_build_consulting_delivery_safe_fields():
    pkg = build_consulting_delivery(
        workspace_id="ws_123",
        package_id="pkg_abc",
        title="Strategy Review",
        objective="Analyze market",
        executive_summary="Looks good.",
        metadata={
            "evidence_matrix": {"market": "strong"},
            "internal_prompt": "You are an AI", # this should be scrubbed before leakage check
            "blockers": ["supplier_unavailable"]
        }
    )
    # Metadata should only contain allowed keys
    assert "evidence_matrix" in pkg.metadata
    assert "blockers" in pkg.metadata
    assert "internal_prompt" not in pkg.metadata
    # Human approval checklist is injected
    assert "human_approval_checklist" in pkg.metadata

def test_build_consulting_delivery_workspace_leakage_rejected():
    with pytest.raises(ValueError, match="workspace_isolation_violation"):
        build_consulting_delivery(
            workspace_id="ws_123",
            package_id="pkg_abc",
            title="Strategy Review",
            objective="Analyze market",
            executive_summary="Looks good.",
            metadata={
                "evidence_matrix": {"market": "sk-" + "live-1234567890abcdef"}, # simulated credential leak
            }
        )

def test_build_consulting_delivery_cross_workspace_rejected():
    with pytest.raises(ValueError, match="cross_workspace_leakage"):
        build_consulting_delivery(
            workspace_id="ws_123",
            package_id="pkg_abc",
            title="Strategy Review",
            objective="Analyze market",
            executive_summary="Looks good.",
            metadata={
                "workspace_id": "ws_999", # Mismatch
            }
        )

def test_deterministic_fingerprint():
    pkg1 = build_consulting_delivery(
        workspace_id="ws_123",
        package_id="pkg_abc",
        title="Strategy Review",
        objective="Analyze market",
        executive_summary="Looks good.",
        metadata={"blockers": []},
        sections=[DeliverableSection("s1", "A", 2, "content A"), DeliverableSection("s2", "B", 1, "content B")]
    )
    pkg2 = build_consulting_delivery(
        workspace_id="ws_123",
        package_id="pkg_abc",
        title="Strategy Review",
        objective="Analyze market",
        executive_summary="Looks good.",
        metadata={"blockers": []},
        sections=[DeliverableSection("s2", "B", 1, "content B"), DeliverableSection("s1", "A", 2, "content A")]
    )
    assert pkg1.compute_fingerprint() == pkg2.compute_fingerprint()

def test_fallback_when_no_sections():
    pkg = build_consulting_delivery(
        workspace_id="ws_123",
        package_id="pkg_abc",
        title="Strategy Review",
        objective="Analyze market",
        executive_summary="Looks good.",
        metadata={}
    )
    assert len(pkg.sections) == 1
    assert pkg.sections[0].title == "Summary"
    assert pkg.sections[0].content_markdown == "Awaiting complete report data."

def test_review_required_is_explicit():
    pkg = build_consulting_delivery(
        workspace_id="ws_123",
        package_id="pkg_abc",
        title="Strategy Review",
        objective="Analyze market",
        executive_summary="Looks good.",
        metadata={}
    )
    assert pkg.status == "review_required"
    assert pkg.metadata.get("review_required") is True
    assert pkg.metadata["human_approval_checklist"]["legal_review_completed"] is False

def test_rendering_to_markdown_and_json():
    pkg = build_consulting_delivery(
        workspace_id="ws_123",
        package_id="pkg_abc",
        title="Consulting Action Plan",
        objective="Validate widget strategy",
        executive_summary="The widget market is highly fragmented.",
        metadata={"blockers": []},
        sections=[DeliverableSection("s1", "Market Findings", 1, "Findings text.")]
    )

    # Test JSON structure
    data = pkg.to_dict()
    assert data["title"] == "Consulting Action Plan"
    assert data["package_type"] == "client_consulting_deliverable"
    assert len(data["sections"]) == 1

    # Test Markdown structure via DeliverablePackage adapter
    canonical = pkg.as_deliverable_package()
    md = canonical.to_markdown()
    assert "# Consulting Action Plan" in md
    assert "The widget market is highly fragmented." in md
    assert "1. Market Findings" in md
    assert "Findings text." in md


def test_missing_money_handling():
    # If the report was missing money inputs, they are simply omitted or not injected
    # as unverified assumptions. Here we test passing an empty economics block.
    pkg = build_consulting_delivery(
        workspace_id="ws_123",
        package_id="pkg_money",
        title="Eco review",
        objective="Find margins",
        executive_summary="None found",
        metadata={
            "economics": {} # Should not crash
        }
    )
    assert pkg.metadata["economics"] == {}

def test_large_artifact_size_avoidance():
    # Demonstrating the fingerprint consistency. Large payload checks are
    # already handled downstream, but we ensure our JSON format is clean.
    long_text = "A" * 100000
    pkg = build_consulting_delivery(
        workspace_id="ws_123",
        package_id="pkg_large",
        title="Large Test",
        objective="Avoid crashing",
        executive_summary="Huge",
        metadata={},
        sections=[DeliverableSection("s1", "Huge Section", 1, long_text)]
    )
    assert len(pkg.to_dict()["sections"][0]["content_markdown"]) == 100000

def test_status_remains_review_required():
    pkg = build_consulting_delivery(
        workspace_id="ws_123",
        package_id="pkg_abc",
        title="Review Test",
        objective="Must be reviewed",
        executive_summary="",
        metadata={"status": "draft"} # Should be forced to review_required
    )
    assert pkg.status == "review_required"


def test_direct_package_construction_cannot_claim_approval_or_delivery():
    for status in ("approved", "delivered"):
        pkg = ConsultingDeliveryPackage(
            package_id="pkg_unsafe-status",
            workspace_id="ws_123",
            title="Review Test",
            objective="Must be reviewed",
            executive_summary="",
            status=status,
        )
        assert pkg.status == "review_required"
        assert pkg.metadata["review_required"] is True