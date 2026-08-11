from __future__ import annotations

import json

from scripts import check_phase1_supplier_readonly_access as preflight


def test_preflight_is_structured_and_redacted(monkeypatch, capsys):
    for key in ("CJ_EMAIL", "CJ_API_KEY", "MARKETOS_SUPPLIER_AUTH_READONLY", "MARKETOS_SUPPLIER_PROVIDER"):
        monkeypatch.delenv(key, raising=False)
    assert preflight.main(["--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "credential_missing"
    assert report["credentials_exposed"] is False
    assert report["mutated"] is False
    assert "CJ_API_KEY" in report["next_action"]


def test_preflight_without_network_gate_never_probes(monkeypatch):
    monkeypatch.setenv("CJ_EMAIL", "fixture@example.invalid")
    monkeypatch.setenv("CJ_API_KEY", "fixture-secret")
    monkeypatch.setenv("MARKETOS_SUPPLIER_AUTH_READONLY", "1")
    monkeypatch.setattr(preflight.CjReadOnlySupplierAdapter, "search", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("network")))
    assert preflight.main(["--json"]) == 0


def test_provider_selection_is_explicit(monkeypatch, capsys):
    monkeypatch.delenv("MARKETOS_SUPPLIER_PROVIDER", raising=False)
    assert preflight.main(["--provider", "zendrop", "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "provider_mismatch"
