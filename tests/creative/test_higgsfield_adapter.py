from __future__ import annotations

from pathlib import Path

import pytest

from evaluation.creative.adapter import (
    LIVE_PREREQUISITES,
    attach_launch_draft_context,
    detect_optional_sdk,
    governance_gate,
    plan_creative_job,
)
from evaluation.creative.catalog import capability_catalog
from evaluation.creative.contracts import CreativeAdapterError, CreativeJobRequest
from evaluation.creative.drafts import (
    brand_kit_brief,
    explainer_brief,
    marketplace_card_brief,
    product_photo_brief,
    ugc_video_brief,
)
from evaluation.creative.fixtures import FIXTURES


def test_catalog_is_static_and_offline():
    catalog = capability_catalog()
    assert {item["creative_type"] for item in catalog} >= {
        "product_photo",
        "marketplace_card",
        "ugc_video",
        "explainer_video",
        "brand_kit",
        "virality_metadata",
    }
    assert all(item["live_available"] is False for item in catalog)


def test_hydroponics_fixture_does_not_become_live():
    job = plan_creative_job(FIXTURES["hydroponics"])
    assert job.status == "dry_run_complete"
    assert job.evidence_state == "fixture"
    assert job.live_attestation is False
    assert job.to_dict()["published"] is False


def test_smart_pet_manual_import_stays_manual():
    job = plan_creative_job(FIXTURES["smart_pet"])
    assert job.evidence_state == "manual_import"
    assert job.evidence_state != "observed"


def test_solar_blocked_live_cannot_attest():
    job = plan_creative_job(FIXTURES["solar_blocked"])
    assert job.status == "blocked"
    assert job.live_attestation is False


def test_marketplace_and_ugc_briefs_are_draft():
    card = marketplace_card_brief()
    ugc = ugc_video_brief()
    assert card.job.request.creative_type == "marketplace_card"
    assert ugc.job.request.creative_type == "ugc_video"
    assert card.job.to_dict()["live_actions_taken"] is False
    assert explainer_brief().job.request.creative_type == "explainer_video"
    assert brand_kit_brief().job.request.lane == "client"
    assert product_photo_brief().job.request.product_id == "hydroponics-tower"


def test_missing_evidence_and_unsupported_locale():
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
    locale = plan_creative_job(
        CreativeJobRequest(
            request_id="req-locale",
            workspace_id="ws-x",
            lane="internal",
            offer_id="o1",
            product_id="p1",
            market_lane="US",
            channel="marketplace",
            creative_type="product_photo",
            mode="dry_run",
            locale="ja",
            claims=("draft",),
            evidence_ids=("ev-1",),
            prompt_metadata="studio",
            reference_asset_ids=(),
        )
    )
    assert locale.status == "unsupported"


def test_secret_and_html_requests_fail_closed():
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


def test_timeout_and_unavailable_classification():
    timeout = plan_creative_job(FIXTURES["marketplace_card"], simulate="timeout")
    assert timeout.status == "timeout_classified"
    missing = plan_creative_job(FIXTURES["marketplace_card"], simulate="unavailable")
    assert missing.status == "provider_unavailable"


def test_deterministic_replay_and_client_export():
    first = plan_creative_job(FIXTURES["hydroponics"])
    second = plan_creative_job(FIXTURES["hydroponics"])
    assert first.replay == second.replay
    safe = first.client_projection()
    assert "prompt_metadata" not in safe
    assert safe["record_kind"] == "planning_record"
    assert safe["live_attestation"] is False


def test_launch_draft_and_governance_stay_offline():
    job = plan_creative_job(FIXTURES["hydroponics"])
    attached = attach_launch_draft_context(job)
    assert attached["launch_authorized"] is False
    assert attached["shopify_status"] == "draft"
    gate = governance_gate(job)
    assert gate["live_allowed"] is False
    assert "human_approval" in LIVE_PREREQUISITES
    sdk = detect_optional_sdk()
    assert sdk["imported"] is False
    assert sdk["credentials_read"] is False
    assert sdk["usable"] is False


def test_adapter_does_not_vendor_higgsfield_sdk():
    root = Path("evaluation/creative")
    blob = "\n".join(path.read_text(encoding="utf-8") for path in root.glob("*.py"))
    assert "import higgsfield_client" not in blob
    assert "HF_API_KEY" not in blob
