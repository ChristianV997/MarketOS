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


class TestCLIEcommerceOperator:
    def test_markdown_output_exit_zero(self, capsys):
        code = cli.main([
            "services", "ecommerce-operator", "--product", "Widget", "--roas", "2.0",
        ])
        out = capsys.readouterr().out
        assert code == 0
        assert "MarketOS E-commerce Validation Experiment" in out

    def test_json_output_contains_readiness_contribution_decision(self, capsys):
        import json
        code = cli.main([
            "services", "ecommerce-operator", "--product", "Widget", "--roas", "2.0",
            "--kill-criteria-json", '{"min_roas": 1.5}', "--json",
        ])
        out = capsys.readouterr().out
        assert code == 0
        data = json.loads(out)
        assert "readiness" in data
        assert "contribution" in data
        assert "decision" in data
        assert "experiment_id" in data

    def test_validation_json_flags_populate_readiness_checklist(self, capsys):
        import json
        code = cli.main([
            "services", "ecommerce-operator", "--product", "Widget", "--roas", "2.0",
            "--validation-json", '{"verdict": "green"}',
            "--unit-economics-json", '{"net_margin_pct": 20}',
            "--supplier-assumptions-json", '{"supplier": "cj"}',
            "--budget-ceiling", "500",
            "--kill-criteria-json", '{"min_roas": 1.5}',
            "--attribution-method", "shopify_ground_truth",
            "--json",
        ])
        data = json.loads(capsys.readouterr().out)
        assert code == 0
        assert data["readiness"]["checklist"]["has_product_validation"] is True
        assert data["readiness"]["checklist"]["has_margin_analysis"] is True


class TestCLICreativeGrowth:
    def test_markdown_output_exit_zero(self, capsys):
        code = cli.main(["services", "creative-growth", "--product", "Widget"])
        out = capsys.readouterr().out
        assert code == 0
        assert out.strip()

    def test_json_output_is_valid_json_no_infinity_literal(self, capsys):
        import json
        code = cli.main(["services", "creative-growth", "--product", "Widget", "--json"])
        out = capsys.readouterr().out
        assert code == 0
        assert "Infinity" not in out and "NaN" not in out
        data = json.loads(out)
        assert data["product_name"] == "Widget"


class TestCLICustomerIntelligence:
    def test_markdown_output_exit_zero(self, capsys):
        code = cli.main(["services", "customer-intelligence", "--business-type", "dental clinic"])
        out = capsys.readouterr().out
        assert code == 0
        assert out.strip()

    def test_json_output_with_vertical(self, capsys):
        import json
        code = cli.main([
            "services", "customer-intelligence", "--business-type", "clinic",
            "--vertical", "clinic_wellness", "--json",
        ])
        out = capsys.readouterr().out
        assert code == 0
        data = json.loads(out)
        assert data["vertical"] == "clinic_wellness"
        assert data["vertical_playbook"] is not None


class TestCLIDigitalProduct:
    def test_markdown_output_exit_zero(self, capsys):
        code = cli.main(["services", "digital-product", "--offer-name", "Playbook", "--price", "99"])
        out = capsys.readouterr().out
        assert code == 0
        assert out.strip()

    def test_json_output_contains_margin_and_validation(self, capsys):
        import json
        code = cli.main([
            "services", "digital-product", "--offer-name", "Playbook",
            "--price", "99", "--target-buyers", "5", "--has-existing-audience", "--json",
        ])
        out = capsys.readouterr().out
        assert code == 0
        data = json.loads(out)
        assert data["margin"]
        assert data["validation"]["verdict"] == "strong"


class TestCLISalesBotSim:
    def test_markdown_output_exit_zero_with_default_script(self, capsys):
        code = cli.main(["services", "sales-bot-sim", "--vertical", "car_sales"])
        out = capsys.readouterr().out
        assert code == 0
        assert "MarketOS Appointment Setter Bot Setup Plan" in out

    def test_json_output_contains_session_and_handoff(self, capsys):
        import json
        code = cli.main(["services", "sales-bot-sim", "--vertical", "car_sales", "--json"])
        data = json.loads(capsys.readouterr().out)
        assert code == 0
        assert "session" in data and "handoff" in data

    def test_repeated_message_flag_drives_scripted_conversation(self, capsys):
        import json
        code = cli.main([
            "services", "sales-bot-sim", "--vertical", "real_estate",
            "--message", "I'm looking to buy a house in Austin",
            "--message", "asap, budget is $500,000",
            "--json",
        ])
        data = json.loads(capsys.readouterr().out)
        assert code == 0
        assert data["session"]["slots"]["intent"] == "buying"


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
