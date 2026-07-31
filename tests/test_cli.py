"""Tests for marketos.cli — product-audit and unit-economics subcommands."""
import backend.core.persistence as pers
import pytest
from marketos import cli


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(pers, "STATE_DIR", str(tmp_path))
    from core.signals import signal_engine
    monkeypatch.setattr(signal_engine, "get", lambda force_refresh=False: [])


class TestCLIProductAudit:
    def test_markdown_output_exit_zero(self, capsys):
        code = cli.main(["services", "product-audit", "--product", "Widget"])
        out = capsys.readouterr().out
        assert code == 0
        assert "MarketOS Product & Category Opportunity Audit" in out

    def test_json_output_is_valid_json(self, capsys):
        import json
        code = cli.main(["services", "product-audit", "--product", "Widget", "--json"])
        out = capsys.readouterr().out
        assert code == 0
        data = json.loads(out)
        assert data["product_name"] == "Widget"


class TestCLIUnitEconomics:
    def test_markdown_output_exit_zero(self, capsys):
        code = cli.main([
            "services", "unit-economics", "--product", "Widget",
            "--cost", "10", "--price", "40", "--shipping", "2",
        ])
        out = capsys.readouterr().out
        assert code == 0
        assert "MarketOS Unit Economics Diagnostic" in out

    def test_json_output_contains_break_even_fields(self, capsys):
        import json
        code = cli.main([
            "services", "unit-economics", "--product", "Widget",
            "--cost", "10", "--price", "40", "--json",
        ])
        out = capsys.readouterr().out
        assert code == 0
        data = json.loads(out)
        assert "break_even_cac" in data
        assert "required_roas" in data

    def test_geo_flag_populates_geo_margin(self, capsys):
        import json
        code = cli.main([
            "services", "unit-economics", "--product", "Widget",
            "--cost", "10", "--price", "40", "--geo", "MX", "--json",
        ])
        data = __import__("json").loads(capsys.readouterr().out)
        assert code == 0
        assert data["geo_margin"] is not None


class TestCLIBadArguments:
    def test_missing_required_argument_exits_nonzero_no_traceback(self, capsys):
        code = cli.main(["services", "unit-economics", "--product", "Widget"])
        captured = capsys.readouterr()
        assert code != 0
        assert "Traceback" not in captured.err
        assert "error:" in captured.err

    def test_unknown_subcommand_exits_nonzero(self, capsys):
        code = cli.main(["services", "not-a-real-command"])
        assert code != 0


class TestCLIRuntimeErrorBoundary:
    def test_unexpected_exception_in_dispatch_returns_one_not_traceback(self, monkeypatch, capsys):
        def _boom(*a, **k):
            raise RuntimeError("unexpected failure")
        monkeypatch.setattr(cli, "_cmd_unit_economics", _boom)

        code = cli.main(["services", "unit-economics", "--product", "Widget", "--cost", "10", "--price", "40"])
        captured = capsys.readouterr()

        assert code == 1
        assert "Traceback" not in captured.err
        assert "unexpected failure" in captured.err
