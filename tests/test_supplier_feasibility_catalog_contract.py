"""Supplier Feasibility Catalog CSV Contract Tests.

Validates the contract for local supplier catalog CSV imports:
- Importing documented sample and generated template rows into usable manual evidence records
- Explicit candidate-ID preservation
- Clean display-name / query separation
- Normalization of supplier_cost and lead_time_days
- Truthful manual/unverified status with no live validation, network calls, or mutations
- Fail-closed behavior for malformed or missing candidate identity, secrets, and raw HTML
"""
from __future__ import annotations

import csv
from pathlib import Path

import pytest

from backend.adapters.research.supplier_feasibility import (
    SupplierImportError,
    import_csv,
    normalize_record,
)
from backend.discovery.import_recommendation import _FIELDS
from evaluation.commerce.supplier_feasibility import (
    PROVENANCE,
    SupplierFeasibilityEvidence,
    build_report,
)

ROOT = Path(__file__).resolve().parents[1]
SAMPLE_CSV_PATH = ROOT / "tests" / "fixtures" / "evidence_imports" / "supplier_catalog_sample.csv"


def test_documented_supplier_catalog_sample_imports_usable_manual_record():
    """Documented supplier catalog sample imports with an explicit stable identity."""
    assert SAMPLE_CSV_PATH.is_file(), f"Sample CSV fixture not found at {SAMPLE_CSV_PATH}"
    records = import_csv(SAMPLE_CSV_PATH)
    assert len(records) >= 1, "Expected at least one record imported from documented supplier_catalog_sample.csv"

    record = records[0]
    assert isinstance(record, SupplierFeasibilityEvidence)
    assert record.candidate_id == "candidate-recovery-accessory"
    assert record.unit_cost == pytest.approx(8.50)
    assert record.shipping_cost == pytest.approx(3.00)
    assert record.estimated_landed_cost == pytest.approx(11.50)
    assert record.delivery_min_days == 12
    assert record.delivery_max_days == 12
    assert record.moq == 20
    assert record.evidence_mode == "manual_import"
    assert record.read_only is True
    assert record.network_calls is False
    assert record.mutated is False


def test_generated_supplier_catalog_template_contract(tmp_path):
    """Importing a populated supplier_catalog_csv template imports a valid manual record."""
    required, optional = _FIELDS["supplier_catalog_csv"]
    fieldnames = required + optional

    # Populate template fields with real manual data
    data_file = tmp_path / "catalog_populated.csv"
    row = {
        "category": "home fitness",
        "candidate_id": "candidate-recovery-accessory",
        "product": "recovery accessory",
        "supplier_cost": "8.50",
        "shipping_cost": "3.00",
        "moq": "20",
        "lead_time_days": "12",
        "availability": "available",
        "supplier": "manual",
    }
    with data_file.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerow(row)

    records = import_csv(data_file)
    assert len(records) == 1, "Expected 1 record imported from template-conforming CSV"
    record = records[0]
    assert record.candidate_id == "candidate-recovery-accessory"
    assert record.unit_cost == pytest.approx(8.50)
    assert record.shipping_cost == pytest.approx(3.00)
    assert record.estimated_landed_cost == pytest.approx(11.50)
    assert record.delivery_min_days == 12
    assert record.delivery_max_days == 12
    assert record.moq == 20
    assert record.inventory_status == "in_stock"
    assert record.evidence_mode == "manual_import"


def test_explicit_candidate_id_is_preserved_when_present():
    """Explicit candidate_id must be preserved exactly and not overwritten by display name or product."""
    row = {
        "candidate_id": "CID-RECOVERY-001",
        "product": "High Density Recovery Roller",
        "supplier_cost": "12.50",
        "shipping_cost": "4.00",
        "lead_time_days": "10",
        "supplier": "manual",
    }
    record = normalize_record(row, mode="manual_import")
    assert record is not None
    assert record.candidate_id == "CID-RECOVERY-001"


def test_display_name_and_candidate_id_separation():
    """Display name / product name must populate supplier_title / query without clobbering candidate_id."""
    row = {
        "candidate_id": "SKU-990-REC",
        "product": "High Density Recovery Roller",
        "supplier_title": "Professional High Density Foam Roller 36in",
        "supplier_cost": "15.00",
        "supplier": "manual",
    }
    record = normalize_record(row, mode="manual_import")
    assert record is not None
    assert record.candidate_id == "SKU-990-REC"
    assert record.supplier_title == "Professional High Density Foam Roller 36in"
    assert record.query in {"High Density Recovery Roller", "Professional High Density Foam Roller 36in", "SKU-990-REC"}


def test_product_display_name_without_explicit_id_is_rejected():
    """A mutable display name must not be promoted into stable candidate identity."""
    row = {
        "product": "recovery accessory",
        "supplier_cost": "8.50",
        "shipping_cost": "3.00",
        "lead_time_days": "12",
        "supplier": "manual",
    }
    assert normalize_record(row, mode="manual_import") is None


def test_explicit_zero_costs_remain_distinct_from_missing():
    row = normalize_record(
        {
            "candidate_id": "zero-cost-offer",
            "product": "zero-cost fixture",
            "supplier_cost": "0",
            "shipping_cost": "0",
            "supplier": "manual",
        },
        mode="manual_import",
    )
    assert row is not None
    assert row.unit_cost == 0
    assert row.shipping_cost == 0
    assert row.estimated_landed_cost == 0
    assert row.field_provenance["unit_cost"] == "manual_import"
    assert row.field_provenance["shipping_cost"] == "manual_import"


def test_manual_metadata_cannot_upgrade_evidence_or_field_provenance():
    row = normalize_record(
        {
            "candidate_id": "manual-offer",
            "product": "manual product",
            "supplier_cost": "4.00",
            "evidence_mode": "live_readonly",
            "field_provenance": {"unit_cost": "live_readonly"},
            "supplier": "manual",
        },
        mode="manual_import",
    )
    assert row is not None
    assert row.evidence_mode == "manual_import"
    assert row.field_provenance["unit_cost"] == "manual_import"
    assert "evidence_mode_overridden" in row.warnings
    assert "field_provenance_overridden" in row.warnings


def test_unknown_supplier_display_name_is_rejected():
    row = normalize_record(
        {
            "candidate_id": "unknown-supplier-offer",
            "product": "manual product",
            "supplier": "Acme Supplier Display Name",
            "supplier_cost": "4.00",
        },
        mode="manual_import",
    )
    assert row is None


@pytest.mark.parametrize(
    "cost_val,expected_cost",
    [
        ("8.50", 8.50),
        ("$12.50", 12.50),
        ("USD 14.99", 14.99),
        (" 9.00 ", 9.00),
        (15.25, 15.25),
        ("€11.00", 11.00),
    ],
)
def test_supplier_cost_normalization(cost_val, expected_cost):
    """`supplier_cost` field alias must normalize to numeric unit_cost."""
    row = {
        "candidate_id": "test-cost-norm",
        "supplier_cost": cost_val,
        "supplier": "manual",
    }
    record = normalize_record(row, mode="manual_import")
    assert record is not None
    assert record.unit_cost == pytest.approx(expected_cost)


@pytest.mark.parametrize(
    "lead_time_val,expected_min,expected_max",
    [
        ("12", 12, 12),
        ("12 days", 12, 12),
        ("7-14", 7, 14),
        ("7–14 days", 7, 14),
        ("10-15 business days", 10, 15),
        (14, 14, 14),
        (None, None, None),
        ("", None, None),
    ],
)
def test_lead_time_days_normalization(lead_time_val, expected_min, expected_max):
    """`lead_time_days` field alias must normalize to min/max delivery days."""
    row = {
        "candidate_id": "test-lead-time-norm",
        "lead_time_days": lead_time_val,
        "supplier": "manual",
    }
    record = normalize_record(row, mode="manual_import")
    assert record is not None
    assert (record.delivery_min_days, record.delivery_max_days) == (expected_min, expected_max)


def test_truthful_manual_unverified_status_with_no_mutation(tmp_path):
    """Catalog imports must retain truthful manual_import status, valid provenance, and no mutation."""
    csv_file = tmp_path / "truthful_import.csv"
    csv_file.write_text(
        "candidate_id,product,supplier_cost,shipping_cost,lead_time_days,supplier\n"
        "CID-001,Yoga Mat,10.00,2.50,5-10,manual\n",
        encoding="utf-8",
    )
    records = import_csv(csv_file)
    assert len(records) == 1
    record = records[0]

    # Verification: manual import mode, truthful provenance
    assert record.evidence_mode == "manual_import"
    assert record.read_only is True
    assert record.network_calls is False
    assert record.mutated is False

    # Provenance checking: no false live or mutated claims
    for field_name, prov in record.field_provenance.items():
        assert prov in PROVENANCE
        assert prov not in {"live_readonly", "mutated", "observed"}, (
            f"Field {field_name} has invalid claim: {prov}"
        )

    # Report build check: preserves manual status and safety warnings
    report = build_report([record], target_sell_prices={"CID-001": 25.0}).to_dict()
    assert report["read_only"] is True
    assert report["network_calls"] is False
    assert report["mutated"] is False
    assert any(
        "supplier_feasibility_is_not_live_supplier_authorization" in w
        for w in report.get("warnings", [])
    )


@pytest.mark.parametrize(
    "empty_row",
    [
        {"supplier_cost": "8.50", "lead_time_days": "12", "supplier": "manual"},
        {"candidate_id": "", "product": "", "supplier_cost": "8.50", "supplier": "manual"},
        {"candidate_id": "   ", "product": "  ", "supplier_cost": "8.50", "supplier": "manual"},
    ],
)
def test_missing_or_empty_candidate_identity_fails_closed(empty_row):
    """Rows without an explicit stable identity must fail closed (return None)."""
    assert normalize_record(empty_row, mode="manual_import") is None


def test_malformed_csv_rows_fail_closed(tmp_path):
    """CSV containing only rows without candidate identity imports 0 records."""
    csv_file = tmp_path / "malformed_identity.csv"
    csv_file.write_text(
        "category,product,supplier_cost,shipping_cost,lead_time_days,supplier\n"
        "fitness,,8.50,3.00,12,manual\n"
        "fitness,   ,10.00,2.00,10,manual\n",
        encoding="utf-8",
    )
    records = import_csv(csv_file)
    assert records == [], "Malformed/missing identity rows must be dropped"


def test_raw_html_in_catalog_csv_is_rejected(tmp_path):
    """Raw HTML in catalog CSV is rejected fail-closed."""
    csv_file = tmp_path / "html_injection.csv"
    csv_file.write_text(
        "category,product,supplier_cost,shipping_cost,lead_time_days,supplier\n"
        "fitness,<script>alert('xss')</script>,8.50,3.00,12,manual\n",
        encoding="utf-8",
    )
    with pytest.raises(SupplierImportError, match="raw HTML"):
        import_csv(csv_file)
