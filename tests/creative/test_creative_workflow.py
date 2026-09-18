from __future__ import annotations

from dataclasses import replace

import pytest

from evaluation.creative.adapter import plan_creative_job
from evaluation.creative.contracts import CreativeAdapterError, CreativeJobRequest
from evaluation.creative.fixtures import WORKFLOW_FIXTURES
from evaluation.creative.workflow import (
    SOURCE_GOVERNANCE_REF,
    compose_draft,
    hydroponics_spanish_education,
    launch_draft_compat,
    managed_acquisition_variants,
    marketplace_card_exact_sku,
    product_validation_appendix,
    run_named_workflow,
    smart_pet_support_risk,
    solar_security_blocked,
)


def test_safe_hydroponics_spanish_draft():
    draft = hydroponics_spanish_education()
    assert draft.locale == "es-MX"
    assert draft.language == "es"
    assert draft.sku_variant == "HYDRO-TOWER-MX-12L"
    assert draft.draft_status == "draft_ready"
    assert draft.commercial_validation == "not_commercially_validated"
    assert draft.job.evidence_state != "observed"
    assert draft.source_governance_ref == SOURCE_GOVERNANCE_REF
    safe = draft.client_projection()
    assert "prompt_metadata" not in str(safe["job"])
    assert safe["published"] is False


def test_safe_smart_pet_support_risk_draft():
    draft = smart_pet_support_risk()
    assert draft.brief_type == "ugc_brief"
    assert draft.job.evidence_state == "manual_import"
    assert draft.job.live_attestation is False


def test_blocked_solar_security_missing_compliance():
    draft = solar_security_blocked()
    assert draft.draft_status != "draft_ready"
    assert "compliance_certificate" in draft.missing_evidence
    assert draft.client_export_allowed is False
    with pytest.raises(CreativeAdapterError):
        draft.client_projection()


def test_marketplace_card_requires_exact_sku():
    ok = marketplace_card_exact_sku()
    assert ok.sku_variant
    assert ok.draft_status == "draft_ready"
    request = replace(WORKFLOW_FIXTURES["marketplace_sku"], sku_variant="")
    blocked = compose_draft(request, workflow_id="wf-sku-missing", package_alias="Launch Draft Pack", brief_type="marketplace_card")
    assert blocked.job.status == "missing_evidence"
    assert "exact_sku_variant" in blocked.missing_evidence


def test_product_validation_and_acquisition_variants():
    appendix = product_validation_appendix()
    assert appendix.package_alias == "Product Validation Sprint"
    first, second = managed_acquisition_variants()
    assert first.content_angle != second.content_angle
    assert second.locale == "en-CA"
    assert run_named_workflow("product_validation_appendix").workflow_id == appendix.workflow_id


def test_unsupported_model():
    with pytest.raises(CreativeAdapterError):
        CreativeJobRequest(
            request_id="req-model",
            workspace_id="ws-x",
            lane="internal",
            offer_id="o1",
            product_id="p1",
            market_lane="US",
            channel="marketplace",
            creative_type="product_photo",
            mode="dry_run",
            locale="en",
            claims=("draft",),
            evidence_ids=("ev-1",),
            prompt_metadata="studio",
            reference_asset_ids=(),
            model_id="higgsfield.live.soul-v2",
        )


def test_negative_gates():
    missing = plan_creative_job(
        CreativeJobRequest(
            request_id="req-missing",
            workspace_id="ws-x",
            lane="internal",
            offer_id="o1",
            product_id="p1",
            market_lane="US",
            channel="marketplace",
            creative_type="product_photo",
            mode="dry_run",
            locale="en",
            claims=("draft",),
            evidence_ids=(),
            prompt_metadata="studio",
            reference_asset_ids=(),
        )
    )
    assert missing.status == "missing_evidence"
    blocked = compose_draft(
        replace(WORKFLOW_FIXTURES["hydroponics_es"], claims=("medical health benefit draft",)),
        workflow_id="wf-claim",
        package_alias="Launch Draft Pack",
        brief_type="product_demonstration",
    )
    assert blocked.draft_status == "blocked"
    with pytest.raises(CreativeAdapterError):
        CreativeJobRequest(
            request_id="req-secret",
            workspace_id="ws-x",
            lane="internal",
            offer_id="o1",
            product_id="p1",
            market_lane="US",
            channel="marketplace",
            creative_type="product_photo",
            mode="dry_run",
            locale="en",
            claims=("draft",),
            evidence_ids=("ev-1",),
            prompt_metadata="use api_key now",
            reference_asset_ids=(),
        )
    with pytest.raises(CreativeAdapterError):
        CreativeJobRequest(
            request_id="req-html",
            workspace_id="ws-x",
            lane="internal",
            offer_id="o1",
            product_id="p1",
            market_lane="US",
            channel="marketplace",
            creative_type="product_photo",
            mode="dry_run",
            locale="en",
            claims=("<script>alert(1)</script>",),
            evidence_ids=("ev-1",),
            prompt_metadata="studio",
            reference_asset_ids=(),
        )
    with pytest.raises(CreativeAdapterError):
        CreativeJobRequest(
            request_id="req-path",
            workspace_id="../escape",
            lane="internal",
            offer_id="o1",
            product_id="p1",
            market_lane="US",
            channel="marketplace",
            creative_type="product_photo",
            mode="dry_run",
            locale="en",
            claims=("draft",),
            evidence_ids=("ev-1",),
            prompt_metadata="studio",
            reference_asset_ids=(),
        )
    mismatch = compose_draft(
        replace(WORKFLOW_FIXTURES["hydroponics_es"], client_workspace_id="ws-other-client"),
        workflow_id="wf-mismatch",
        package_alias="Launch Draft Pack",
        brief_type="product_demonstration",
    )
    assert "client/workspace mismatch" in mismatch.job.errors
    live = plan_creative_job(WORKFLOW_FIXTURES["hydroponics_es"], simulate="live")
    assert live.status == "blocked"
    unapproved = compose_draft(
        replace(WORKFLOW_FIXTURES["hydroponics_es"], approval_state="not_requested"),
        workflow_id="wf-unapproved",
        package_alias="Launch Draft Pack",
        brief_type="product_demonstration",
    )
    assert unapproved.client_export_allowed is False
    stale = compose_draft(
        replace(WORKFLOW_FIXTURES["hydroponics_es"], evidence_freshness="stale"),
        workflow_id="wf-stale",
        package_alias="Launch Draft Pack",
        brief_type="product_demonstration",
    )
    assert stale.draft_status == "blocked"


def test_deterministic_replay_and_launch_draft_compat():
    first = hydroponics_spanish_education()
    second = hydroponics_spanish_education()
    assert first.job.replay == second.job.replay
    attached = launch_draft_compat(first)
    assert attached["launch_authorized"] is False
    assert attached["shopify_status"] == "draft"
    assert attached["governor_role"] == "planning_budget_reference_only"
    assert attached["source_governance_ref"] == SOURCE_GOVERNANCE_REF
