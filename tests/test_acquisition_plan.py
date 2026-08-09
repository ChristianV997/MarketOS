from backend.discovery.acquisition_plan import build_acquisition_plan_from_recommendation
from backend.discovery.import_recommendation import ImportRecommendation


def test_plan_contains_manual_steps_and_safety():
    recommendation = ImportRecommendation("r", "w", "supplier_catalog_csv", "supplier", "Supplier", "Need margin", 90, ["margin_proxy"], ["category", "product", "supplier_cost"], [], ["g"])
    plan = build_acquisition_plan_from_recommendation(recommendation, "w")
    assert plan.current_mode == "manual_export_only" and plan.steps and plan.template_paths
    assert "manual" in plan.to_markdown().lower()
    assert plan.connector_stub_name == "supplier_catalog_export_connector"
