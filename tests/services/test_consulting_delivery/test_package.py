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


def test_client_export_normalizes_approval_claim_in_metadata():
    pkg = build_consulting_delivery(
        workspace_id="ws_123",
        package_id="pkg_status_metadata",
        title="Review Test",
        objective="Must be reviewed",
        executive_summary="",
        metadata={"status": "approved"},
    )

    payload = pkg.to_dict()
    canonical = pkg.as_deliverable_package()
    assert payload["status"] == "review_required"
    assert payload["metadata"]["status"] == "review_required"
    assert canonical.status == "review_required"
    assert canonical.metadata["status"] == "review_required"


def test_delivery_status_cannot_be_mutated_after_construction():
    pkg = build_consulting_delivery(
        workspace_id="ws_123",
        package_id="pkg_mutable_status",
        title="Review Test",
        objective="Must be reviewed",
        executive_summary="",
        metadata={},
    )

    pkg.status = "delivered"
    assert pkg.status == "review_required"
    assert pkg.to_dict()["status"] == "review_required"
    assert pkg.as_deliverable_package().status == "review_required"


def test_client_safe_boundary_covers_rendered_sections():
    section = DeliverableSection(
        section_id="section-synthetic-leak",
        title="Synthetic fixture section",
        order=1,
        content_markdown="Synthetic test content.",
        metadata={"internal_prompt": "synthetic fixture only"},
    )

    with pytest.raises(ValueError, match="workspace_isolation_violation"):
        build_consulting_delivery(
            workspace_id="ws_123",
            package_id="pkg_section_leak",
            title="Review Test",
            objective="Must be reviewed",
            executive_summary="",
            metadata={},
            sections=[section],
        )


def test_client_export_rechecks_mutable_nested_metadata():
    pkg = build_consulting_delivery(
        workspace_id="ws_123",
        package_id="pkg_mutated_metadata",
        title="Review Test",
        objective="Must be reviewed",
        executive_summary="",
        metadata={"economics": {"summary": "synthetic safe fixture"}},
    )
    pkg.metadata["economics"] = {"internal_prompt": "synthetic fixture only"}

    with pytest.raises(ValueError, match="workspace_isolation_violation"):
        pkg.as_deliverable_package()


def test_client_export_enforces_size_bound_after_mutation():
    pkg = build_consulting_delivery(
        workspace_id="ws_123",
        package_id="pkg_oversized_after_mutation",
        title="Review Test",
        objective="Must be reviewed",
        executive_summary="",
        metadata={},
        sections=[DeliverableSection("s1", "section", 1, "small")],
    )
    pkg.sections[0].content_markdown = "X" * 600_000

    with pytest.raises(ValueError, match="bounded_output_exceeded"):
        pkg.to_dict()
    with pytest.raises(ValueError, match="bounded_output_exceeded"):
        pkg.as_deliverable_package()
