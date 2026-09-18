from pathlib import Path

from scripts.generate_oss_sbom import build_sbom


def test_sbom_is_network_free_and_contains_reviewed_inventory():
    report = build_sbom()
    assert report["format"] == "marketos-oss-sbom-v2"
    assert report["network_access"] is False
    assert report["inventory_errors"] == []
    assert any(item["name"] == "medusa" for item in report["candidates"])
    assert report["python_packages"]
    manifest = Path(__file__).resolve().parents[1] / "requirements-oss-agents.txt"
    expected = next(line.strip() for line in manifest.read_text(encoding="utf-8").splitlines() if line.startswith("pydantic-ai=="))
    expected_name, expected_version = expected.split("==", maxsplit=1)
    declared = next(item for item in report["declared_requirements"] if item["name"] == expected_name)
    assert declared["specifier"] == f"=={expected_version}"
