"""Tests for services.geographic_opportunity.cli -- the deterministic,
offline operator entry point. Exercises main() end-to-end against a real
fixture file on disk (no mocks), asserting it never performs network I/O
and produces identical output for identical inputs.
"""
import ast
import json
from pathlib import Path

import pytest

from services.geographic_opportunity import cli

FIXTURES_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "geographic_opportunity" / "offers"


class TestNoLiveNetworkSurface:
    def test_module_imports_no_http_client(self):
        source = Path(cli.__file__).read_text()
        tree = ast.parse(source)
        imported_names = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.Import, ast.ImportFrom))
            for alias in node.names
        }
        assert "requests" not in imported_names
        assert "httpx" not in imported_names
        assert "urllib" not in imported_names
        assert "socket" not in imported_names


class TestGeneratedAtIsRequired:
    def test_omitting_generated_at_exits_nonzero(self):
        with pytest.raises(SystemExit):
            cli.build_arg_parser().parse_args([str(FIXTURES_DIR / "goods_offer.json")])


class TestJsonOutput:
    def test_main_prints_deterministic_json_to_stdout(self, capsys):
        exit_code = cli.main([str(FIXTURES_DIR / "goods_offer.json"), "--generated-at", "2026-02-10T00:00:00Z"])
        assert exit_code == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["candidate_id"] == "cand-fixture-goods"
        assert payload["read_only"] is True
        assert payload["network_calls"] is False
        assert payload["mutated"] is False

    def test_identical_invocation_produces_identical_json(self, capsys):
        cli.main([str(FIXTURES_DIR / "goods_offer.json"), "--generated-at", "2026-02-10T00:00:00Z"])
        first = capsys.readouterr().out
        cli.main([str(FIXTURES_DIR / "goods_offer.json"), "--generated-at", "2026-02-10T00:00:00Z"])
        second = capsys.readouterr().out
        assert first == second

    def test_writes_to_an_output_file_instead_of_stdout_when_requested(self, tmp_path, capsys):
        out_path = tmp_path / "report.json"
        exit_code = cli.main(
            [str(FIXTURES_DIR / "goods_offer.json"), "--generated-at", "2026-02-10T00:00:00Z", "--output", str(out_path)]
        )
        assert exit_code == 0
        assert capsys.readouterr().out == ""
        payload = json.loads(out_path.read_text())
        assert payload["candidate_id"] == "cand-fixture-goods"


class TestMarkdownOutput:
    def test_main_prints_markdown_with_expected_sections(self, capsys):
        exit_code = cli.main(
            [str(FIXTURES_DIR / "goods_offer.json"), "--generated-at", "2026-02-10T00:00:00Z", "--format", "markdown"]
        )
        assert exit_code == 0
        text = capsys.readouterr().out
        assert text.startswith("# Geographic Opportunity Report: cand-fixture-goods")
        assert "## Blockers" in text
        assert "## Landed-cost scenarios" in text
        assert "## Destination/source comparison" in text
        assert "## Evidence quality summary" in text
        assert "- fingerprint: " in text

    def test_unknown_geography_fixture_markdown_shows_no_scenarios(self, capsys):
        cli.main([str(FIXTURES_DIR / "unknown_offer.json"), "--generated-at", "2026-02-10T00:00:00Z", "--format", "markdown"])
        text = capsys.readouterr().out
        assert "geography_kind=unknown" in text
        assert "- (none -- see blockers above)" in text


class TestUnsupportedFormatRejected:
    def test_render_rejects_an_unsupported_format(self):
        from services.geographic_opportunity.report import build_geographic_opportunity_report
        from services.geographic_opportunity.serialization import offer_from_dict

        from .conftest import GENERATED_AT

        offer = offer_from_dict(json.loads((FIXTURES_DIR / "goods_offer.json").read_text()))
        report = build_geographic_opportunity_report(offer, generated_at=GENERATED_AT)
        with pytest.raises(ValueError):
            cli.render(report, "yaml")
