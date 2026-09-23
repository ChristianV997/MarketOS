"""Tests for backend.adapters.research.trade_flows -- the pinned, offline
UN Comtrade bulk-file adapter. Uses a real fixture file, no mocks."""
from pathlib import Path

import pytest

from backend.adapters.research import trade_flows

FIXTURES_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "geographic_opportunity"


class TestNoLiveApiSurface:
    def test_module_imports_no_http_client(self):
        import ast

        source = Path(trade_flows.__file__).read_text()
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


class TestBulkFileImport:
    def test_imports_a_real_comtrade_shaped_fixture(self):
        records = trade_flows.import_un_comtrade_bulk_file(FIXTURES_DIR / "comtrade_bulk_sample.json")
        assert len(records) == 2  # the secret-shaped row and the empty row are dropped

    def test_normalizes_pinned_column_names(self):
        records = trade_flows.import_un_comtrade_bulk_file(FIXTURES_DIR / "comtrade_bulk_sample.json")
        first = next(r for r in records if r["reporter_country"] == "MEX")
        assert first["partner_country"] == "CHN"
        assert first["hs_code"] == "850110"
        assert first["trade_value"] == 500000.0
        assert first["quantity"] == 10000.0
        assert first["source"] == trade_flows.PINNED_SOURCE

    def test_missing_value_and_quantity_stay_none_not_zero(self):
        records = trade_flows.import_un_comtrade_bulk_file(FIXTURES_DIR / "comtrade_bulk_sample.json")
        second = next(r for r in records if r["reporter_country"] == "USA")
        assert second["trade_value"] is None
        assert second["quantity"] is None
        assert "trade_value_unavailable" in second["warnings"]
        assert "quantity_unavailable" in second["warnings"]

    def test_currency_assumption_is_disclosed_not_silent(self):
        records = trade_flows.import_un_comtrade_bulk_file(FIXTURES_DIR / "comtrade_bulk_sample.json")
        assert all("currency_assumed_usd_per_comtrade_convention" in r["warnings"] for r in records)

    def test_secret_shaped_row_is_dropped(self):
        records = trade_flows.import_un_comtrade_bulk_file(FIXTURES_DIR / "comtrade_bulk_sample.json")
        assert all("api_key" not in str(r) for r in records)


class TestPathValidation:
    def test_rejects_path_traversal(self):
        with pytest.raises(trade_flows.TradeFlowImportError):
            trade_flows.validate_input_path("../../etc/passwd.json")

    def test_rejects_unsupported_extension(self, tmp_path):
        bad = tmp_path / "data.txt"
        bad.write_text("{}")
        with pytest.raises(trade_flows.TradeFlowImportError):
            trade_flows.validate_input_path(bad)

    def test_rejects_a_nonexistent_file(self, tmp_path):
        with pytest.raises(trade_flows.TradeFlowImportError):
            trade_flows.validate_input_path(tmp_path / "does_not_exist.json")


class TestRawHtmlRejection:
    def test_rejects_a_file_containing_raw_html(self, tmp_path):
        bad = tmp_path / "bad.json"
        bad.write_text('[{"reporterISO": "MEX", "note": "<html><body>hi</body></html>"}]')
        with pytest.raises(trade_flows.TradeFlowImportError):
            trade_flows.import_un_comtrade_bulk_file(bad)


class TestClientSafeRecord:
    def test_strips_secret_shaped_keys(self):
        record = {"reporter_country": "MEX", "api_key": "sk_live_x"}
        safe = trade_flows.client_safe_record(record)
        assert "api_key" not in safe
        assert safe["reporter_country"] == "MEX"
