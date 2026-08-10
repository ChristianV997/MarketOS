"""Unit tests for scripts/run_phase1_live_validation.py's new diagnostic
logic (_diagnose_reachability) — the one genuinely new piece of code this
harness adds (everything else is a thin call-through to already-tested
entrypoints). Imported directly via importlib since it's a top-level
script, not a package module."""
from __future__ import annotations

import importlib.util
import socket
from pathlib import Path
from unittest.mock import patch

import pytest
import requests

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "run_phase1_live_validation.py"

spec = importlib.util.spec_from_file_location("run_phase1_live_validation", SCRIPT_PATH)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class TestDiagnoseReachability:
    def test_dry_run_never_performs_network_io(self):
        with patch("socket.getaddrinfo", side_effect=AssertionError("must not resolve DNS in dry-run")):
            result = mod._diagnose_reachability("example.com", allow_network=False)
        assert result["checked"] is False
        assert result["failure_mode"] == "not_attempted"

    def test_dns_failure_classified_correctly(self):
        with patch("socket.getaddrinfo", side_effect=socket.gaierror("Name or service not known")):
            result = mod._diagnose_reachability("nonexistent.invalid", allow_network=True)
        assert result["failure_mode"] == "dns_failure"
        assert result["dns_resolved"] is False

    def test_proxy_block_classified_correctly(self):
        with patch("socket.getaddrinfo", return_value=[(2, 1, 6, "", ("93.184.216.34", 0))]):
            with patch.object(requests, "head", side_effect=requests.exceptions.ProxyError("Tunnel connection failed: 403 Forbidden")):
                result = mod._diagnose_reachability("example.com", allow_network=True)
        assert result["failure_mode"] == "proxy_block"
        assert result["dns_resolved"] is True
        assert result["resolved_ip"] == "93.184.216.34"

    def test_timeout_classified_correctly(self):
        with patch("socket.getaddrinfo", return_value=[(2, 1, 6, "", ("93.184.216.34", 0))]):
            with patch.object(requests, "head", side_effect=requests.exceptions.ConnectTimeout("timed out")):
                result = mod._diagnose_reachability("example.com", allow_network=True)
        assert result["failure_mode"] == "timeout"

    def test_tls_error_classified_correctly(self):
        with patch("socket.getaddrinfo", return_value=[(2, 1, 6, "", ("93.184.216.34", 0))]):
            with patch.object(requests, "head", side_effect=requests.exceptions.SSLError("certificate verify failed")):
                result = mod._diagnose_reachability("example.com", allow_network=True)
        assert result["failure_mode"] == "tls_error"

    def test_generic_connection_error_classified_correctly(self):
        with patch("socket.getaddrinfo", return_value=[(2, 1, 6, "", ("93.184.216.34", 0))]):
            with patch.object(requests, "head", side_effect=requests.exceptions.ConnectionError("connection refused")):
                result = mod._diagnose_reachability("example.com", allow_network=True)
        assert result["failure_mode"] == "connection_error"

    def test_redirect_classified_correctly(self):
        class _Response:
            status_code = 302
        with patch("socket.getaddrinfo", return_value=[(2, 1, 6, "", ("93.184.216.34", 0))]):
            with patch.object(requests, "head", return_value=_Response()):
                result = mod._diagnose_reachability("example.com", allow_network=True)
        assert result["failure_mode"] == "redirect_rejected"

    def test_reachable_classified_correctly(self):
        class _Response:
            status_code = 200
        with patch("socket.getaddrinfo", return_value=[(2, 1, 6, "", ("93.184.216.34", 0))]):
            with patch.object(requests, "head", return_value=_Response()):
                result = mod._diagnose_reachability("example.com", allow_network=True)
        assert result["failure_mode"] == "reachable"
        assert result["http_status"] == 200


class TestFieldStatusSummary:
    def test_groups_fields_by_status(self):
        summary = mod._field_status_summary({"title": "observed", "price": "observed", "sku": "missing"})
        assert summary == {"observed": ["title", "price"], "missing": ["sku"]}

    def test_empty_field_status(self):
        assert mod._field_status_summary({}) == {}


class TestHostname:
    def test_extracts_lowercase_hostname(self):
        assert mod._hostname("https://WWW.Example.COM/product/x") == "www.example.com"

    def test_empty_url(self):
        assert mod._hostname("") == ""
