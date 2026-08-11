from __future__ import annotations

import json

import pytest

from scripts.generate_site_draft_pack import main


def test_cli_json_is_offline_and_safe(capsys):
    main(["--json"])
    report = json.loads(capsys.readouterr().out)
    assert report["site_type"] == "ecommerce_store"
    assert report["read_only"] is True
    assert report["published"] is False


def test_cli_markdown_is_client_readable(capsys):
    main(["--markdown"])
    output = capsys.readouterr().out
    assert "# Site Draft Pack" in output
    assert "## Route Manifest" in output
    assert "## CMS Content Model" in output
    assert "Deployment Blockers" in output


@pytest.mark.parametrize("site_type", ["ecommerce_store", "single_product_landing_page", "category_validation_site", "service_business_website", "manufacturer_catalog_site", "lead_generation_funnel", "campaign_microsite"])
def test_cli_supports_every_site_type(site_type, capsys):
    main(["--site-type", site_type, "--json"])
    report = json.loads(capsys.readouterr().out)
    assert report["site_type"] == site_type
    assert report["route_manifest"]["routes"]


def test_cli_writes_sanitized_export_set(tmp_path, capsys):
    main(["--output", str(tmp_path), "--json"])
    capsys.readouterr()
    names = {path.name for path in tmp_path.iterdir()}
    assert "site_draft_pack.json" in names
    assert "route_manifest.json" in names
    assert "cms_content_model.json" in names
    assert "shopify_theme_draft_payload.json" in names
    assert "webflow_cms_draft_payload.json" in names
    assert "conversion_test_plan.md" in names
    assert "approval_checklist.md" in names
    assert "operator_risk_review.json" in names
    raw = (tmp_path / "site_draft_pack.json").read_text(encoding="utf8")
    assert "CJ_API_KEY" not in raw
    assert "Authorization: Bearer" not in raw


def test_cli_rejects_traversal(capsys):
    with pytest.raises(SystemExit):
        main(["--client-context", r"..\secret.json", "--json"])
    assert "traversal" in capsys.readouterr().err


def test_cli_rejects_secret_like_context(tmp_path, capsys):
    path = tmp_path / "context.json"
    path.write_text(json.dumps({"access_token": "synthetic-secret"}), encoding="utf8")
    with pytest.raises(SystemExit):
        main(["--client-context", str(path), "--json"])
    assert "secret" in capsys.readouterr().err


def test_cli_rejects_non_json_context(tmp_path, capsys):
    path = tmp_path / "context.txt"
    path.write_text("not-json", encoding="utf8")
    with pytest.raises(SystemExit):
        main(["--client-context", str(path), "--json"])
    assert "non-JSON" in capsys.readouterr().err


def test_cli_modes_are_exclusive():
    with pytest.raises(SystemExit):
        main(["--json", "--markdown"])


def test_cli_output_is_deterministic(tmp_path, capsys):
    first, second = tmp_path / "one", tmp_path / "two"
    main(["--output", str(first), "--json"])
    capsys.readouterr()
    main(["--output", str(second), "--json"])
    capsys.readouterr()
    assert (first / "site_draft_pack.json").read_text(encoding="utf8") == (second / "site_draft_pack.json").read_text(encoding="utf8")


def test_cli_does_not_write_without_output(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    main(["--json"])
    capsys.readouterr()
    assert list(tmp_path.iterdir()) == []
