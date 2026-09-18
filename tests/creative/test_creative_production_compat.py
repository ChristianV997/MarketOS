from evaluation.creative.adapter import plan_creative_job
from evaluation.creative.contracts import CreativeJobRequest
from evaluation.creative.production_compat import (
    BRIEF_TYPES,
    LAUNCH_DRAFT_SEAM,
    project_job_compat,
    project_launch_draft_compat,
)
from evaluation.creative.workflow import run_named_workflow


def test_launch_draft_seam_never_authorizes_publish():
    draft = run_named_workflow("hydroponics_spanish_education")
    compat = project_launch_draft_compat(draft)
    assert compat["seam"] == LAUNCH_DRAFT_SEAM
    assert compat["launch_authorized"] is False
    assert compat["shopify_status"] == "draft"
    assert compat["medusa_status"] == "draft"
    assert compat["published"] is False
    assert compat["generated"] is False
    assert compat["observed"] is False
    assert compat["live_validated"] is False
    assert compat["governor_spend_authority"] is False
    assert compat["governor_budget_reference_only"] is True
    assert compat["brief_type"] in BRIEF_TYPES
    assert compat["brief_type"] == "product_demonstration"
    assert compat["creative_quality"] == "draft_only"
    assert compat["commercial_validation"] == "not_commercially_validated"


def test_marketplace_card_maps_to_listing_compat():
    draft = run_named_workflow("marketplace_card_exact_sku")
    compat = project_launch_draft_compat(draft)
    assert compat["brief_type"] == "marketplace_card"
    assert compat["product_listing_compatible"] is True


def test_smart_pet_ugc_compat():
    draft = run_named_workflow("smart_pet_support_risk")
    compat = project_launch_draft_compat(draft)
    assert compat["brief_type"] == "ugc_brief"
    assert compat["ugc_brief_compatible"] is True
    assert compat["published"] is False


def test_solar_blocked_still_draft_compat():
    draft = run_named_workflow("solar_security_blocked")
    compat = project_launch_draft_compat(draft)
    assert compat["launch_authorized"] is False
    assert compat["brief_type"] == "video_explainer_brief"


def test_job_compat_uses_same_schema():
    draft = run_named_workflow("product_validation_appendix")
    compat = project_job_compat(draft.job)
    assert compat["schema"] == "MarketOS.CreativeLaunchDraftCompat.v1"
    assert compat["trustos_export_required"] is True
    assert compat["approval_ledger_required"] is True


def test_compat_does_not_require_live_request_fields():
    request = CreativeJobRequest(
        request_id="compat-req-1",
        workspace_id="ws-internal",
        lane="internal",
        offer_id="offer-hydro",
        product_id="prod-hydro",
        market_lane="US",
        channel="marketplace",
        creative_type="product_photo",
        mode="dry_run",
        locale="es-MX",
        claims=("kit educativo",),
        evidence_ids=("ev-hydro-1",),
        prompt_metadata="offline brief",
        reference_asset_ids=(),
        approval_state="approved",
    )
    job = plan_creative_job(request)
    compat = project_job_compat(job)
    assert compat["brief_type"] == "product_photoshoot_brief"
    assert compat["source_governance_ref"].endswith("pending")
    assert compat["launch_authorized"] is False
