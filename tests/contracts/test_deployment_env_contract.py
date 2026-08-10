import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_deployment_contract_is_machine_readable_and_classifies_secrets():
    contract = json.loads((ROOT / "deploy/mvp/env.contract.json").read_text(encoding="utf-8"))
    variables = {item["name"]: item for item in contract["variables"]}
    assert contract["profile"] == "marketos-mvp-island"
    assert variables["MARKETOS_EVENT_READ_JSONL_PATH"]["required_for"] == "backend"
    assert variables["MARKETOS_PUBLIC_COMMERCE_RUNS"]["default"] == "0"
    assert variables["SUPABASE_SERVICE_ROLE_KEY"]["secret"] is True
    assert variables["SUPABASE_SERVICE_ROLE_KEY"]["browser_allowed"] is False
    assert "SHOPIFY_ACCESS_TOKEN" in contract["forbidden_frontend_secret_names"]


def test_selected_platform_templates_are_present_and_secret_free():
    railway = (ROOT / "deploy/railway/railway.json").read_text(encoding="utf-8")
    render = (ROOT / "deploy/render/render.yaml").read_text(encoding="utf-8")
    vercel = (ROOT / "frontend/vercel.json").read_text(encoding="utf-8")
    assert "uvicorn backend.api:app" in railway
    assert "healthcheckPath" in railway
    assert "uvicorn backend.api:app" in render
    assert "MARKETOS_PUBLIC_COMMERCE_RUNS" in render
    assert '"outputDirectory": "dist"' in vercel
    for content in (railway, render, vercel):
        assert "SERVICE_ROLE_KEY" not in content
        assert "ACCESS_TOKEN" not in content
