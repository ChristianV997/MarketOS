from backend.providers.vendor_router import build_workspace_vendor_plan, list_vendors_by_capability, recommend_vendor_for_capability


def test_mvp_routes_required_categories_deterministically() -> None:
    first = build_workspace_vendor_plan("mvp")
    assert first == build_workspace_vendor_plan("mvp")
    selected = {row["capability_id"]: row["recommended_vendor_id"] for row in first["recommendations"]}
    assert selected["database_auth_storage"] == "supabase"
    assert selected["frontend_hosting"] == "vercel"
    assert selected["backend_hosting"] in {"railway", "render"}
    assert selected["public_signal_ingestion"] == "google_news_rss"
    assert selected["analytics"] == "posthog"
    assert selected["error_tracking"] == "sentry"
    assert selected["landing_page_builder"] in {"pagefly", "gempages"}
    assert selected["video_ad_generation"] == "creatify"
    assert selected["ai_model_routing"] in {"cloudflare_ai_gateway", "vercel_ai_gateway", "openrouter"}


def test_deferred_vendors_are_not_selected_when_safe_use_now_exists() -> None:
    choice = recommend_vendor_for_capability("video_ad_generation")
    assert choice.recommended_vendor_id == "creatify"
    assert "pencil" in choice.alternatives
    assert all(item.vendor_id != "pencil" or item.use_stage.value == "defer" for item in list_vendors_by_capability("video_ad_generation"))
