from backend.workspaces.org_chart import build_default_workspace_org_chart


def test_org_chart_maps_departments_capabilities_and_boundaries() -> None:
    chart = build_default_workspace_org_chart()
    data = chart.to_dict()
    assert len(data["departments"]) == 9
    assert any(item["name"] == "Market Research" for item in data["departments"])
    assert any(item["capability_id"] == "public_signal_ingestion" for item in data["connector_assignments"])
    assert all("provider_mutation" in item["permission_boundary"]["forbidden_actions"] for item in data["departments"])
