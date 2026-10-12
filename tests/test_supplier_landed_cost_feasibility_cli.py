"""Focused tests for the offline landed-cost operator command."""
from __future__ import annotations

import json
from pathlib import Path

from scripts.run_supplier_landed_cost_feasibility import main


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "supplier_feasibility" / "cj_validation_pack_success.json"


def test_cli_emits_deterministic_json_assessment(capsys):
    args = [
        "--input",
        str(FIXTURE),
        "--candidate-id",
        "mini-thermal-printer",
        "--target-price",
        "50",
        "--currency",
        "USD",
        "--generated-at",
        "2026-10-12T00:00:00Z",
    ]
    assert main(args) == 0
    first = json.loads(capsys.readouterr().out)
    assert main(args) == 0
    second = json.loads(capsys.readouterr().out)

    assert first == second
    assert first["schema"] == "MarketOS.SupplierLandedCostFeasibilityCLI.v1"
    assert first["assessment"]["read_only"] is True
    assert first["safety"]["purchase_authorized"] is False
    assert first["supplier_context"]["evidence_mode"] == "fixture"
    assert first["target_price"]["provenance"] == "assumed"
    assert first["target_price"]["evidence_state"] == "assumed"
    assert first["assessment"]["landed_cost_scenarios"]


def test_cli_markdown_is_an_assessment_not_a_purchase_recommendation(capsys):
    assert main(
        [
            "--input",
            str(FIXTURE),
            "--candidate-id",
            "mini-thermal-printer",
            "--target-price",
            "50",
            "--currency",
            "USD",
            "--generated-at",
            "2026-10-12T00:00:00Z",
            "--format",
            "markdown",
        ]
    ) == 0
    output = capsys.readouterr().out
    assert "OFFLINE ASSESSMENT" in output
    assert "purchase" in output.lower()
    assert "Supplier Landed-Cost Feasibility" in output


def test_cli_accepts_existing_manual_csv_evidence(capsys):
    assert main(
        [
            "--input",
            str(ROOT / "tests" / "fixtures" / "supplier_feasibility" / "cj_manual_import.csv"),
            "--input-format",
            "csv",
            "--supplier",
            "cj",
            "--candidate-id",
            "mini-thermal-printer",
            "--target-price",
            "50",
            "--currency",
            "USD",
            "--generated-at",
            "2026-10-12T00:00:00Z",
        ]
    ) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["supplier_context"]["evidence_mode"] == "manual_import"
    assert payload["assessment"]["offer"]["price_evidence"]["provenance"] == "manual_import"


def test_cli_keeps_missing_cost_unavailable(tmp_path, capsys):
    source = tmp_path / "missing.json"
    source.write_text(
        json.dumps(
            {
                "candidate_id": "missing-cost",
                "supplier_product_id": "offer-missing-cost",
                "supplier": "cj",
                "source_type": "fixture_demo",
                "currency": "USD",
                "shipping_cost": "0",
                "shipping_currency": "USD",
                "field_provenance": {"shipping_cost": "observed"},
            }
        ),
        encoding="utf-8",
    )
    assert main(
        [
            "--input",
            str(source),
            "--target-price",
            "50",
            "--currency",
            "USD",
            "--generated-at",
            "2026-10-12T00:00:00Z",
        ]
    ) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["assessment"]["landed_cost_scenarios"] == []
    assert any("quoted_price" in blocker for blocker in payload["assessment"]["blockers"])


def test_cli_preserves_explicit_zero_shipping(tmp_path, capsys):
    source = tmp_path / "zero.json"
    source.write_text(
        json.dumps(
            {
                "candidate_id": "zero-shipping",
                "supplier_product_id": "offer-zero-shipping",
                "supplier": "cj",
                "source_type": "fixture_demo",
                "unit_cost": "10",
                "currency": "USD",
                "shipping_cost": "0",
                "shipping_currency": "USD",
                "field_provenance": {"unit_cost": "observed", "shipping_cost": "observed"},
            }
        ),
        encoding="utf-8",
    )
    assert main(
        [
            "--input",
            str(source),
            "--target-price",
            "50",
            "--currency",
            "USD",
            "--generated-at",
            "2026-10-12T00:00:00Z",
        ]
    ) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["assessment"]["offer"]["goods"]["shipping"]["supplier_shipping"]["amount"] == "0"
    assert payload["assessment"]["landed_cost_scenarios"][0]["result"]["supplier_shipping"]["amount"] == "0"
