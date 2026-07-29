from scripts.generate_oss_sbom import build_sbom


def test_sbom_is_network_free_and_contains_reviewed_inventory():
    report = build_sbom()
    assert report["format"] == "marketos-oss-sbom-v1"
    assert report["network_access"] is False
    assert report["inventory_errors"] == []
    assert any(item["name"] == "medusa" for item in report["candidates"])
    assert report["python_packages"]
